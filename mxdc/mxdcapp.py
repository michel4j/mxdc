from twisted.internet import gtk2reactor

gtk2reactor.portableInstall()

from bcm.service import mxdctools
from bcm.beamline.mx import MXBeamline
from bcm.utils import mdns
from bcm.utils.log import get_module_logger, log_to_console
from bcm.utils.misc import get_project_name, identifier_slug
from bcm.utils.clients import MxDCClient
from mxdc.AppWindow import AppWindow
from mxdc.widgets import dialogs
from mxdc.utils import excepthook
from twisted.internet import reactor
from twisted.spread import pb
import os
import time
import warnings
import gtk

USE_TWISTED = True
MXDC_PORT = 9898

warnings.simplefilter("ignore")

_logger = get_module_logger('mxdc')


class MXDCApp(object):
    def run_local(self):
        # Create application window
        self.main_window = AppWindow()
        self.beamline = MXBeamline()
        self.service_type = '_mxdc_{}._tcp'.format(identifier_slug(self.beamline.name))
        self.service_data = {
            'user': get_project_name(),
            'started': time.asctime(time.localtime()),
            'beamline': self.beamline.name
        }
        self.remote_mxdc = MxDCClient(self.service_type)
        self.remote_mxdc.connect('active', self.service_found)
        self.remote_mxdc.connect('health', self.service_failed)
        self.main_window.connect('destroy', self.do_quit)
        self.main_window.run()

    def service_found(self, obj, state):
        if state:
            data = self.remote_mxdc.service_data
            msg = 'On <i>%s</i>, by user <i>%s</i> since <i>%s</i>. Only one instance permitted!' % (
                data['host'], data['data']['user'], data['data']['started']
            )

            if set(self.beamline.config['admin_groups']) & set(os.getgroups()):
                msg += '\n\nDo you want to shut it down?'
                response = dialogs.yesno('MXDC Already Running', msg)
                if response == gtk.RESPONSE_YES:
                    d = self.remote_mxdc.service.callRemote('shutdown')
                    d.addErrback(self.on_close_connection)
                else:
                    self.do_quit()
            else:
                self.provider_failure()

    def service_failed(self, obj, state):
        if state:
            # broadcast after emote MxDC shuts down
            _logger.info('Starting MxDC service discovery ...')
            self.broadcast_service()

    def broadcast_service(self):
        self.provider = mdns.Provider(
            'MXDC Client (%s)' % self.beamline.name,
            self.service_type, MXDC_PORT, self.service_data, unique=True
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


    def on_close_connection(self, reason):
        _logger.warning('Remote MxDC instance terminated.')

    def provider_success(self):
        _logger.info(
            'Local MXDC instance {}@{} since {}'.format(
                self.service_data['user'], self.beamline.name, self.service_data['started']
            )
        )

    def do_quit(self, obj=None):
        _logger.info('Stopping ...')
        exit_main_loop()


def run_main_loop(func):
    if USE_TWISTED:
        reactor.callWhenRunning(func)
        reactor.run()
    else:
        gtk.idle_add(func)
        gtk.main()


def exit_main_loop():
    if USE_TWISTED:
        reactor.stop()
    else:
        gtk.main_quit()


def main():
    try:
        _ = os.environ['BCM_CONFIG_PATH']
        _logger.info('Starting MXDC (%s)... ' % os.environ['BCM_BEAMLINE'])
    except:
        _logger.error('Could not find Beamline Control Module environment variables.')
        _logger.error('Please make sure MXDC is properly installed and configured.')
        exit_main_loop()

    app = MXDCApp()
    app.run_local()


if __name__ == "__main__":
    log_to_console()
    #excepthook.install(exit_main_loop)
    run_main_loop(main)
