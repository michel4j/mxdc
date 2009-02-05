#!/usr/bin/env python

import gtk
import sys
import os
from mxdc.widgets.imageviewer import ImgViewer

def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(6)
    win.set_title("ImgViewer Demo")
    myview = ImgViewer()
    hbox = gtk.HBox(False)
    hbox.pack_start(myview)
    win.add(hbox)
    win.show_all()
    
    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()

if __name__ == '__main__':
    main()
