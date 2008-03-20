#!/usr/bin/env python

import sys, os
import gtk

sys.path.append(os.environ['BCM_PATH'])

from mxdc.gui.ActiveWidgets import *
from bcm.devices.positioners import Positioner



def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(2)
    win.set_title("ActiveWidget Test")
    my_p = Positioner('michel:H3:setCurrentC')
    my_e = PositionerLabel(my_p)
    win.add(my_e)
    win.show_all()

    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()


if __name__ == '__main__':
    main()
