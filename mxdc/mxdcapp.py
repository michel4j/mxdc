from twisted.internet import glib2reactor
glib2reactor.install()
from twisted.internet import reactor
import warnings
warnings.simplefilter("ignore")
import gtk, gobject
import sys, os, signal
import logging

sys.path.append(os.environ['BCM_PATH'])

from gui.Splash import Splash
from gui.AppWindow import AppWindow
from bcm.beamline.mx import MXBeamline

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
    #hdlr = logging.RotatingFileHandler('/tmp/mxdc', "a", 5000, 3)
    #fmt = logging.Formatter('%(asctime)s %(levelname)s : %(message)s', "%x %X")
    #hdlr.setFormatter(fmt)
    #lgr.addHandler(hdlr)

    
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
        self.beamline = MXBeamline('08id1.conf')
        rev_file = os.environ['BCM_PATH'] + '/bcm/config/revision.txt'
        _f = file(rev_file)
        _raw = _f.readlines()
        rev = _raw[8].split()[3]
        rev_date = _raw[9].split()[3]
        self.splash = Splash(img_file, self.beamline,
            icon=icon_file, logo=logo_file, color='#ead3f4')
        self.splash.set_revision(rev, rev_date)
        gobject.idle_add(self.run)
                 
    def run(self):
        self.beamline.setup()
        self.splash.hide()
        self.main_window = AppWindow(self.beamline)
        self.main_window.connect('destroy',self.do_quit)
        return False
    
    def do_quit(self, obj):
        logging.getLogger('').log(0,'Stopping...')
        reactor.stop()

if __name__ == "__main__":
    app = AppClass()
    #gtk.main()
    #os.kill(os.getpid(),signal.SIGKILL)
    reactor.run()
