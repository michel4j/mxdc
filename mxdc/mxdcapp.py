import gi
gi.require_version('Gtk', '3.0')
from twisted.internet import gtk3reactor
gtk3reactor.install()

from mxdc.service import mxdctools
from mxdc.beamline.mx import MXBeamline
from mxdc.utils import mdns
from mxdc.utils.log import get_module_logger, log_to_console
from mxdc.utils.misc import get_project_name
from mxdc.AppWindow import AppWindow
from mxdc.widgets import dialogs
from mxdc.utils import excepthook
from twisted.internet import reactor
from twisted.spread import pb
import os
import time
import warnings
from gi.repository import GObject
from gi.repository import Gtk

MXDC_PORT = 9999
SERVICE_DATA = {
    'user': get_project_name(), 
    'started': time.asctime(time.localtime()),
    'beamline': os.environ.get('MXDC_BEAMLINE', 'SIM')
}

warnings.simplefilter("ignore")
#excepthook.install()
_logger = get_module_logger('mxdc')

class MXDCApp(object):
    def __init__(self):
        self.remote_mxdc = None
        
    def run_local(self):
        self.main_window = AppWindow()
        self.beamline = MXBeamline()
        self.main_window.connect('destroy', self.do_quit)
        if SERVICE_DATA['beamline'] == 'SIM':
            self.main_window.run()
            return False       
        try:
            self.browser = mdns.Browser('_mxdc._tcp')
            self.browser.connect('added', self.service_found)
            self.browser.connect('removed', self.service_removed)
            GObject.timeout_add(2500, self.broadcast_service) # broadcast after a short while
            self.main_window.run()
        except mdns.mDNSError:
            self.provider_failure()
        return False
    
    def broadcast_service(self):
        if self.remote_mxdc is None:
            self.provider = mdns.Provider('MXDC Client (%s)' % os.environ.get('MXDC_BEAMLINE', 'SIM'), '_mxdc._tcp', MXDC_PORT, SERVICE_DATA, unique=True)
            self.provider.connect('collision', lambda x: self.provider_failure())
            self.service = mxdctools.MXDCService(None)       
            reactor.listenTCP(MXDC_PORT, pb.PBServerFactory(mxdctools.IPerspectiveMXDC(self.service)))
        else:
            self.provider_failure()
        
    def service_found(self, obj, instance):
        self._service_data = instance
        data = self._service_data['data']
        _logger.info('MxDC running on `%s`, by `%s` since `%s` .' % (instance['host'], data['user'], data['started'] ))    
        self.factory = pb.PBClientFactory()
        self.factory.getRootObject().addCallbacks(self._remote_mxdc_success, self._remote_mxdc_failed)
        reactor.connectTCP(self._service_data['address'],
                           self._service_data['port'], self.factory)
        
    def service_removed(self, obj, instance):
        self.remote_mxdc = None
        self.broadcast_service()
            
    def do_quit(self, obj=None):
        _logger.info('Stopping...')
        reactor.stop()

    def provider_success(self):
        pass

    def provider_failure(self):
        try:
            msg = 'On <i>%s</i>, by user <i>%s</i> since <i>%s</i>. Only one instance permitted!' % (self._service_data['host'], 
                        self._service_data['data']['user'], self._service_data['data']['started'])
        except:
            msg = "Unidentified remote MxDC instance found"
        if self.beamline.config['admin_group'] in os.getgroups():
            msg += '\n\nDo you want to shut it down?'
            response = dialogs.yesno('MXDC Already Running', msg)
            print response
            if response == Gtk.ResponseType.YES and self.remote_mxdc is not None:
                self.remote_mxdc.callRemote('shutdown')
                #GObject.timeout_add(2000, self.broadcast_service) # broadcast after a short while
            else:
                self.do_quit()
        else:
            dialogs.error('MXDC Already Running', msg)
            self.do_quit()
    
    def _rshutdown_success(self):
        self.provider = mdns.Provider('MXDC Client (%s)' % os.environ.get('MXDC_BEAMLINE', 'SIM'), '_mxdc._tcp', MXDC_PORT, SERVICE_DATA, unique=True)
    
    def _rshutdown_failure(self, failure):
        r = failure.trap(pb.PBConnectionLost)
        if r == pb.PBConnectionLost:
            self._rshutdown_success()
        else:
            _logger.error('Remote Shutdown Failed')
            self.do_quit()
        
    def _remote_mxdc_success(self, perspective):
        self.remote_mxdc = perspective
    
    def _remote_mxdc_failed(self, failure):
        _logger.error('An instance of MXDC is already running on the local network. Only one instance permitted.')
        dialogs.error('MXDC Already Running', 'An instance of MXDC is already running on the local network. Only one instance permitted.')
        self.do_quit()
        
def main():
    try:
        _ = os.environ['MXDC_CONFIG_PATH']
        _logger.info('Starting MXDC (%s)... ' % os.environ['MXDC_BEAMLINE'])
    except:
        _logger.error('Could not find Beamline Control Module environment variables.')
        _logger.error('Please make sure MXDC is properly installed and configured.')
        reactor.stop()
        
    app = MXDCApp()
    app.run_local()

if __name__ == "__main__":
    #log_to_console()
    #log_to_file(os.path.join(os.environ['HOME'], 'mxdc.log'))
        
    reactor.callWhenRunning(main)
    reactor.run()
