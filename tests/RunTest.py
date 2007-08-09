#!/usr/bin/env python

import time, sys
from numpy import *
from RunManager import RunManager
import gobject, gtk

def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    #win.set_default_size(100,100)
    win.set_border_width(2)
    win.set_title("Run Widget Demo")
    myrun = RunManager()
    win.add(myrun)
    win.show()

    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()


if __name__ == '__main__':
    main()
