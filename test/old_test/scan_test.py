from bcm.tools.scanning import scan
from bcm.devices.detectors import *
from bcm.devices.positioners import *
from mxdc.gui.Plotter import Plotter

import gtk, gobject


def do_scan():
    det = Counter('michel:PM3:intensityM')
    pos = Positioner('michel:H3:setCurrentC')
    scan.setup(pos, -1.5, -1.8, 20, det, 1.0)
    scan.run()
    scan.fit()

win = gtk.Window()
win.set_size_request(640,480)
plt = Plotter()
win.add(plt)
scan.set_plotter(plt)
win.connect('destroy', lambda x: gtk.main_quit())
win.show_all()

gobject.idle_add(do_scan)

gtk.main()
