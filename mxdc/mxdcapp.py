#from twisted.internet import glib2reactor
#glib2reactor.install()
#from twisted.internet import reactor

import gtk, gobject
import sys, os
import logging

sys.path.append(os.environ['BCM_PATH'])

from gui.Splash import Splash
from gui.AppWindow import AppWindow
from bcm.beamline import PX

# set up logging to file
try:
    logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s : %(message)s',
                    datefmt='%a, %d %b %Y %H:%M:%S',
                    filename='/tmp/mxdc.log',
                    filemode='a')
except:
    logging.basicConfig()
    lgr= logging.getLogger('')
    lgr.setLevel(logging.DEBUG)
    hdlr = logging.handlers.RotatingFileHandler('/tmp/mxdc', "a", 5000, 3)
    fmt = logging.Formatter('%(asctime)s %(levelname)s : %(message)s', "%x %X")
    hdlr.setFormatter(fmt)
    lgr.addHandler(hdlr)

    
# define a Handler which writes INFO messages or higher to the sys.stderr
console = logging.StreamHandler()
console.setLevel(logging.NOTSET)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s : %(message)s')
console.setFormatter(formatter)
logging.getLogger('').addHandler(console)


class AppClass(object):
    def __init__(self):
        img_file = os.environ['BCM_PATH'] + '/mxdc/gui/images/splash.png'
        logo_file = os.environ['BCM_PATH'] + '/mxdc/gui/images/logo.png'
        icon_file = os.environ['BCM_PATH'] + '/mxdc/gui/images/icon.png'
        self.beamline = PX('08id1.conf')
        self.splash = Splash(img_file, self.beamline,
            icon=icon_file, logo=logo_file, color='#ead3f4')
        gobject.idle_add(self.run)
                 
    def run(self):
        self.beamline.setup()
        self.splash.hide()
        self.main_window = AppWindow(self.beamline)
        
        return False

if __name__ == "__main__":
    app = AppClass()
    gtk.main()
