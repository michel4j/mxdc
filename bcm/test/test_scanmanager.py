#!/usr/bin/env python

from twisted.internet import glib2reactor
glib2reactor.install()
from twisted.internet import reactor
import gtk
from bcm.utils import converter
from mxdc.widgets.scanmanager import ScanManager

gtk.threads_init()

def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: reactor.stop())
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
