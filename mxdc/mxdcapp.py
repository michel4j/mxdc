import sys
import os
import logging
import warnings
warnings.simplefilter("ignore")

import gtk
import gobject
from twisted.internet import glib2reactor
glib2reactor.install()
from twisted.internet import reactor

from bcm.beamline.mx import MXBeamline
from bcm.utils.log import get_module_logger
from mxdc.utils import gtkexcepthook
from mxdc.widgets.splash import Splash
from mxdc.AppWindow import AppWindow

_logger = get_module_logger('mxdc')

class MXDCApp(object):
    def __init__(self, config):
        splash_duration = 1
        self._config_file = config
        self.splash = Splash(duration=splash_duration, color='#fffffe')
        self.splash.set_version('2.5.9')
        gobject.timeout_add(splash_duration * 1000, self.run)
                 
    def run(self):
        self.beamline = MXBeamline(self._config_file)
        self.main_window = AppWindow()
        self.main_window.connect('destroy', self.do_quit)
        self.main_window.show_all()
        self.splash.win.hide()
        return False
    
    def do_quit(self, obj):
        _logger.info('Stopping...')
        reactor.stop()
        #gtk.main_quit()

if __name__ == "__main__":
    try:
        config = os.path.join(os.environ['BCM_CONFIG_PATH'],
                              os.environ['BCM_CONFIG_FILE'])
    except:
        _logger.error('Could not fine Beamline Control Module environment variables.')
        _logger.error('Please make sure MXDC is properly installed and configured.')
        sys.exit(1)
    app = MXDCApp(config)
    reactor.run()
    #gtk.main()
