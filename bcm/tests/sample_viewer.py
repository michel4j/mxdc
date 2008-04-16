#!/usr/bin/env python

import os, sys
import gtk
sys.path.append(os.environ['BCM_PATH'])

from bcm.beamline import PX
from mxdc.gui import SampleViewer

def main():

    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("SampleViewer")
    book = gtk.Notebook()
    win.add(book)
    bl = PX('08id1-sample.conf')
    bl.setup()
    myviewer = SampleViewer(bl)
    book.append_page(myviewer, tab_label=gtk.Label('Sample Viewer') )
    win.show_all()

    try:
        gtk.main()
    finally:
        myviewer.video.stop()


if __name__ == '__main__':
    main()
