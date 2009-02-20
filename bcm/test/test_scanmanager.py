#!/usr/bin/env python

#from twisted.internet import glib2reactor
#glib2reactor.install()
#from twisted.internet import reactor
import gtk
import gobject
from bcm.utils import converter
from bcm.utils import gtkexcepthook
from mxdc.widgets.scanmanager import ScanManager

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
        gobject.threads_init()
        gtk.main()
    finally:
        print "Quiting..."
