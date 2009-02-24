from twisted.internet import glib2reactor
glib2reactor.install()
from twisted.internet import reactor
import warnings
warnings.simplefilter("ignore")
import gtk, gobject
import sys, os, signal
import logging

SHARE_DIR = os.path.join(os.path.dirname(__file__), 'share')

from mxdc.widgets.splash import Splash
from AppWindow import AppWindow
from bcm.beamline.mx import MXBeamline
from bcm.utils.log import get_module_logger, log_to_console

_logger = get_module_logger('mxdc')

class AppClass(object):
    def __init__(self):
        img_file = os.path.join(SHARE_DIR, 'splash.png')
        logo_file = os.path.join(SHARE_DIR, 'logo.png')
        icon_file = os.path.join(SHARE_DIR, 'icon.png')
        self._config_file = os.path.join(os.environ['BCM_CONFIG_PATH'], '08id1.conf')
        self.splash = Splash(img_file, duration=1.0, icon=icon_file, logo=logo_file, color='#ead3f4')
        self.splash.set_version('2.5.9')
        gobject.idle_add(self.run)
                 
    def run(self):
        self.beamline = MXBeamline(self._config_file)
        self.main_window = AppWindow()
        self.main_window.connect('destroy',self.do_quit)
        self.main_window.show_all()
        return False
    
    def do_quit(self, obj):
        _logger.info('Stopping...')
        reactor.stop()

if __name__ == "__main__":
    app = AppClass()
    #gtk.main()
    #os.kill(os.getpid(),signal.SIGKILL)
    reactor.run()
