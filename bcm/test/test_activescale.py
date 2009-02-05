#!/usr/bin/env python

import gtk
import gobject

from bcm.device.motor import VMEMotor
from bcm.beamline.mx import MXBeamline

from mxdc.widgets.misc import *

def main():

    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("Motor Test")

    config_file = '/home/michel/Code/eclipse-ws/beamline-control-module/etc/08id1.conf'
    bl = MXBeamline(config_file)
        
    mtr = MotorEntry(bl.goniometer.omega, 'Omega')
    #lbl = ActiveLabel(bl.goniometer.omega)
    sc1 = ActiveHScale(bl.sample_backlight)
    sc2 = ActiveHScale(bl.sample_sidelight)
    vbox = gtk.VBox()
    
    win.add(vbox)
    vbox.pack_start(mtr)
    #vbox.pack_start(lbl)
    vbox.pack_start(sc1)
    vbox.pack_start(sc2)
    win.show_all()

    try:
        gtk.main()
    finally:
        print 'Stopping'


if __name__ == '__main__':
    main()
