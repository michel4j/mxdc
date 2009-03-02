import time
import gtk
import gobject

from bcm.device.detector import MXCCDImager
from bcm.utils.log import log_to_console

log_to_console()

def test():
    det = MXCCDImager('BL08ID1:CCD', 3072, 0.007234)
    det.wait()

gobject.idle_add(test)
gtk.main()

