import sys
import os
import logging
import warnings
warnings.simplefilter("ignore")

from twisted.internet import gtk2reactor
gtk2reactor.install()
from twisted.internet import reactor

import gtk
import gobject
gobject.threads_init()

from bcm.beamline.mx import MXBeamline
from twisted.spread import pb
from bcm.beamline.remote import BeamlineClient
from bcm.utils.log import get_module_logger, log_to_console, log_to_file
#from mxdc.utils import gtkexcepthook
from mxdc.AppWindow import AppWindow

_logger = get_module_logger('mxdc')

class MXDCApp(object):
    def run_local(self, config):
        self.main_window = AppWindow()
        beamline = MXBeamline(config)
        self.main_window.connect('destroy', self.do_quit)
        self.main_window.run()
        return False
    
    def run_remote(self):
        self.main_window = AppWindow()
        beamline = BeamlineClient()
        self.main_window.connect('destroy', self.do_quit)
        beamline.connect('ready', lambda x, y: self.main_window.run())
        factory = pb.PBClientFactory()
        reactor.connectTCP("localhost", 8880, factory)
        deferred = factory.getRootObject()
        deferred.addCallback(beamline.setup)
    
    def do_quit(self, obj):
        _logger.info('Stopping...')
        reactor.stop()
        #gtk.main_quit()

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
    log_to_file(os.path.join(os.environ['HOME'],'mxdc.log'))
        
    reactor.callWhenRunning(main)
    reactor.run()
    #gtk.main()
