import gtk, gobject
import sys, os

sys.path.append(os.environ['BCM_PATH'])

from gui.Splash import Splash
from gui.AppWindow import AppWindow
from bcm.beamline import PX

class AppClass(object):
    def __init__(self):
        img_file = os.environ['BCM_PATH'] + '/mxdc/gui/images/splash.png'
        logo_file = os.environ['BCM_PATH'] + '/mxdc/gui/images/logo.png'
        icon_file = os.environ['BCM_PATH'] + '/mxdc/gui/images/icon.png'
        self.beamline = PX('08id1.conf')
        self.splash = Splash(img_file, self.beamline,
            icon=icon_file, logo=logo_file, color='#d3a5e7')
        gobject.idle_add(self.run)
                 
    def run(self):
        self.beamline.setup()
        self.splash.hide()
        self.main_window = AppWindow(self.beamline)
        
        return False

if __name__ == "__main__":
    app = AppClass()
    gtk.main()
