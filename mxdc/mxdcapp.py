import sys
import os
import logging
import warnings
warnings.simplefilter("ignore")

import gtk
import gobject
gobject.threads_init()
from twisted.internet import glib2reactor
glib2reactor.install()
from twisted.internet import reactor

from bcm.utils.log import get_module_logger
from mxdc.utils import gtkexcepthook
from mxdc.AppWindow import AppWindow

_logger = get_module_logger('mxdc')

class MXDCApp(object):
    def __init__(self, config):
        self._config_file = config
        self.run()
                 
    def run(self):
        self.main_window = AppWindow(self._config_file)
        self.main_window.connect('destroy', self.do_quit)
        self.main_window.show_all()
        return False
    
    def do_quit(self, obj):
        _logger.info('Stopping...')
        #reactor.stop()
        gtk.main_quit()

if __name__ == "__main__":
    try:
        config = os.path.join(os.environ['BCM_CONFIG_PATH'],
                              os.environ['BCM_CONFIG_FILE'])
    except:
        _logger.error('Could not fine Beamline Control Module environment variables.')
        _logger.error('Please make sure MXDC is properly installed and configured.')
        sys.exit(1)
    app = MXDCApp(config)
    #reactor.run()
    gtk.main()
