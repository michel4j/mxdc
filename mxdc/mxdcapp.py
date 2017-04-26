from twisted.internet import gtk2reactor

gtk2reactor.install()

from bcm.service import mxdctools
from bcm.beamline.mx import MXBeamline
from bcm.utils import mdns
from bcm.utils.log import get_module_logger, log_to_console
from bcm.utils.misc import get_project_name
from bcm.utils.clients import MxDCClient
from mxdc.AppWindow import AppWindow
from mxdc.widgets import dialogs
from mxdc.utils import excepthook
from twisted.internet import reactor
from twisted.spread import pb
import os
import time
import warnings
import gobject
import gtk

MXDC_PORT = 9898
SERVICE_DATA = {
    'user': get_project_name(),
    'started': time.asctime(time.localtime()),
    'beamline': os.environ.get('BCM_BEAMLINE', 'SIM')
}

warnings.simplefilter("ignore")
excepthook.install()
_logger = get_module_logger('mxdc')


class MXDCApp(object):
    def run_local(self):
        # Create application window
        self.main_window = AppWindow()
        self.beamline = MXBeamline()
        self.remote_mxdc = MxDCClient()
        self.remote_mxdc.connect('active', self.service_found)
        self.main_window.connect('destroy', self.do_quit)
        self.main_window.run()

    def service_found(self, obj, state):
        if state:
            data = self.remote_mxdc.service_data
            msg = 'On <i>%s</i>, by user <i>%s</i> since <i>%s</i>. Only one instance permitted!' % (
                data['host'], data['data']['user'], data['data']['started']
            )

            if self.beamline.config['admin_group'] in os.getgroups():
                msg += '\n\nDo you want to shut it down?'
                response = dialogs.yesno('MXDC Already Running', msg)
                if response == gtk.RESPONSE_YES:
                    self.remote_mxdc.perspective.callRemote('shutdown')
                else:
                    self.do_quit()
            else:
                self.provider_failure()
        else:
            # broadcast after a short while if remote MxDC shuts down
            gobject.timeout_add(1000, self.broadcast_service)

    def broadcast_service(self):
        self.provider = mdns.Provider(
            'MXDC Client (%s)' % self.beamline.name,
            '_mxdc._tcp', MXDC_PORT, SERVICE_DATA, unique=True
        )
        self.provider.connect('collision', lambda x: self.provider_failure())
        self.provider.connect('running', lambda x: self.provider_success())
        self.service = mxdctools.MXDCService(None)
        reactor.listenTCP(MXDC_PORT, pb.PBServerFactory(mxdctools.IPerspectiveMXDC(self.service)))

    def provider_failure(self):
        dialogs.error(
            'MXDC Already Running',
            'An instance of MXDC is already running on the local network. Only one instance permitted.'
        )
        self.do_quit()

    def provider_success(self):
        _logger.info(
            'Local MXDC instance {}@{} since {}'.format(
                SERVICE_DATA['user'], SERVICE_DATA['beamline'], SERVICE_DATA['started']
            )
        )

    def do_quit(self, obj=None):
        _logger.info('Stopping ...')
        reactor.stop()


def main():
    try:
        _ = os.environ['BCM_CONFIG_PATH']
        _logger.info('Starting MXDC (%s)... ' % os.environ['BCM_BEAMLINE'])
    except:
        _logger.error('Could not find Beamline Control Module environment variables.')
        _logger.error('Please make sure MXDC is properly installed and configured.')
        reactor.stop()

    app = MXDCApp()
    app.run_local()


if __name__ == "__main__":
    log_to_console()
    # log_to_file(os.path.join(os.environ['HOME'], 'mxdc.log'))

    reactor.callWhenRunning(main)
    reactor.run()
