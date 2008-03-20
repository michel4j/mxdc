from bcm.tools.Scanner import scan
from bcm.devices.detectors import *
from bcm.devices.positioners import *

import gtk, gobject


def do_scan():
    det = Counter('michel:PM3:intensityM')
    pos = Positioner('michel:H3:setCurrentC')
    scan(pos, -1.5, -1.8, 20, det, 1.0)
    
gobject.idle_add(do_scan)

gtk.main()
