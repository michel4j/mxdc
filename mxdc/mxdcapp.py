from twisted.internet import gtk2reactor
gtk2reactor.install()

#from mxdc.utils import gtkexcepthook
from bcm.beamline.mx import MXBeamline
from bcm.beamline.remote import BeamlineClient
from bcm.utils import mdns
from bcm.utils.log import get_module_logger, log_to_console, log_to_file
from bcm.utils.misc import get_project_name
from mxdc.AppWindow import AppWindow
from mxdc.widgets.dialogs import error
from twisted.internet import reactor
from twisted.spread import pb
import gc
import gobject
import gtk
import logging
import os
import sys
import time
import warnings

warnings.simplefilter("ignore")
_logger = get_module_logger('mxdc')

class MXDCApp(object):
    def provider_success(self):
        _ = MXBeamline()
        self.main_window.connect('destroy', self.do_quit)
        self.main_window.run()

    def provider_failure(self):
        _logger.error('An instance of MXDC is already running on the local network. Only one instance permitted.')
        error('MXDC Already Running', 'An instance of MXDC is already running on the local network. Only one instance permitted.')
        self.do_quit()

    def run_local(self):
        self.main_window = AppWindow()
        _service_data = {'user': get_project_name(), 
                         'started': time.asctime(time.localtime()),
                         'beamline': os.environ.get('BCM_BEAMLINE', 'SIM')}

        if _service_data['beamline'] == 'SIM':
            self.provider_success()
            return False
        
        try:
            self.browser = mdns.Browser('_mxdc._tcp')
            self.browser.connect('added', self.found_existing)
            self.provider = mdns.Provider('MXDC Client (%s)' % os.environ.get('BCM_BEAMLINE', 'SIM'), '_mxdc._tcp', 9999, _service_data, unique=True)
            self.provider.connect('running', lambda x: self.provider_success())
            self.provider.connect('collision', lambda x: self.provider_failure())

        except mdns.mDNSError:
            self.provider_failure()
        return False
    
    def found_existing(self, obj, instance):
        data = instance['data']
        if data.get('beamline') == os.environ.get('BCM_BEAMLINE', 'sim'):
            _logger.info('MxDC running on `%s`, by `%s` since `%s` .' % (instance['host'], data['user'], data['started'] ))    
        
        
    def run_remote(self):
        self.main_window = AppWindow()
        beamline = BeamlineClient()
        self.main_window.connect('destroy', self.do_quit)
        beamline.connect('ready', lambda x, y: self.main_window.run())
        factory = pb.PBClientFactory()
        reactor.connectTCP("localhost", 8880, factory)
        deferred = factory.getRootObject()
        deferred.addCallback(beamline.setup)
    
    def do_quit(self, obj=None):
        _logger.info('Stopping...')
        reactor.stop()
        gc.collect()
        
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
    #app.run_remote()

if __name__ == "__main__":
    log_to_console()
    log_to_file(os.path.join(os.environ['HOME'], 'mxdc.log'))
        
    reactor.callWhenRunning(main)
    reactor.run()
