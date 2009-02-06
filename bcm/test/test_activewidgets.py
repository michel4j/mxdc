#!/usr/bin/env python

import sys
import os
import gtk
from mxdc.widgets.misc import *
from bcm.device.misc import Positioner



def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(2)
    win.set_title("ActiveWidget Test")
    my_p = Positioner('michel:H3:setCurrentC')
    my_p.units = 'mA'
    my_e = ActiveLabel(my_p, '%0.3f')
    win.add(my_e)
    win.show_all()

    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()


if __name__ == '__main__':
    main()
