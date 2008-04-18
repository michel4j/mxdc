import gtk, gobject
import sys, os

sys.path.append(os.environ['BCM_PATH'])

from gui.Splash import Splash
from gui.AppWindow import AppWindow
from bcm.beamline import PX

class AppClass(object):
    def __init__(self):
        self.img_file = os.environ['BCM_PATH'] + '/mxdc/gui/images/splash.png'
        self.beamline = PX('08id1.conf')
        self.splash = Splash(self.img_file, self.beamline)
        gobject.idle_add(self.run)
                 
    def run(self):
        self.beamline.setup()
        self.splash.hide()
        self.main_window = AppWindow(self.beamline)
        return False

if __name__ == "__main__":
    app = AppClass()
    gtk.main()
