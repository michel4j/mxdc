import sys
import os
import logging
import warnings
import time
import gtk
import gobject
import gc

warnings.simplefilter("ignore")

from twisted.internet import gtk2reactor
gtk2reactor.install()
from twisted.internet import reactor

from bcm.beamline.mx import MXBeamline
from twisted.spread import pb
from bcm.beamline.remote import BeamlineClient
from bcm.utils.log import get_module_logger, log_to_console, log_to_file
from mxdc.widgets.dialogs import error
from bcm.utils import mdns
from bcm.utils.misc import get_project_name
#from mxdc.utils import gtkexcepthook
from mxdc.AppWindow import AppWindow

_logger = get_module_logger('mxdc')

class MXDCApp(object):
    def provider_success(self, config):
        _ = MXBeamline(config)
        self.main_window.connect('destroy', self.do_quit)
        self.main_window.run()

    def provider_failure(self):
        _logger.error('An instance of MXDC is already running on the local network. Only one instance permitted.')
        error('MXDC Already Running', 'An instance of MXDC is already running on the local network. Only one instance permitted.')
        self.do_quit()

    def run_local(self, config):
        self.main_window = AppWindow()
        _service_data = {'user': get_project_name(), 
                         'started': time.asctime(time.localtime()),
                         'beamline': os.environ.get('BCM_BEAMLINE', 'sim')}
        try:
            self.provider = mdns.Provider('MXDC Client (%s)' % os.environ.get('BCM_BEAMLINE', 'sim'), '_mxdc._tcp', 9999, _service_data, unique=True)
            self.provider.connect('running', lambda x: self.provider_success(config))
            self.provider.connect('collision', lambda x: self.provider_failure())

        except mdns.mDNSError:
            self.provider_failure()
        return False
    
    def found_existing(self, obj, instance):
        data = instance['data']
        if data.get('beamline') == os.environ.get('BCM_BEAMLINE', 'sim'):
            _logger.info('MxDC is running on `%s` and was started`%s` by user `%s`.' % (instance['host'], data['started'], data['user'] ))    
        
        
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
        config = os.path.join(os.environ['BCM_CONFIG_PATH'],
                              os.environ['BCM_CONFIG_FILE'])
        _logger.info('Starting MXDC ... ')
        _logger.info('Local configuration: "%s"' % os.environ['BCM_CONFIG_FILE'])
        #beamline = MXBeamline(config)
    except:
        _logger.error('Could not find Beamline Control Module environment variables.')
        _logger.error('Please make sure MXDC is properly installed and configured.')
        reactor.stop()
        
    app = MXDCApp()
    app.run_local(config)
    #app.run_remote()

if __name__ == "__main__":
    log_to_console()
    #log_to_file(os.path.join(os.environ['HOME'],'mxdc.log'))
        
    reactor.callWhenRunning(main)
    reactor.run()
