#!/usr/bin/env python

import gtk
from bcm.utils import converter
from mxdc.ScanManager import ScanManager

def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(2)
    win.set_title("Periodic Table Demo")
    sm = ScanManager()
    win.add(sm)
    win.show_all()
                    

if __name__ == '__main__':
    try:
        main()
        gtk.main()
    finally:
        print "Quiting..."
