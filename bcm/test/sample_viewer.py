#!/usr/bin/env python

import warnings
warnings.simplefilter("ignore")
import gtk, gobject
import sys, os
import logging

from bcm.beamline.mx import MXBeamline
from mxdc.gui.SampleViewer import SampleViewer
from mxdc.gui.ActiveWidgets import CryojetWidget
#from bcm.utils.log import log_to_console
#log_to_console()

# set up logging to file

def main():

    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("SampleViewer")
    book = gtk.Notebook()
    #win.add(book)
    config_file = '/home/michel/Code/eclipse-ws/beamline-control-module/etc/08id1.conf'
    bl = MXBeamline(config_file)
    
    myviewer = SampleViewer(bl)
    cryo_controller = CryojetWidget(bl.cryojet, bl.cryo_x)
    cryo_align = gtk.Alignment(0.5,0.5, 0, 0)
    cryo_align.set_border_width(12)
    cryo_align.add(cryo_controller)
    cryo_controller.set_border_width(6)

    book.append_page(myviewer, tab_label=gtk.Label(' Sample Camera ') )
    book.append_page(cryo_align, tab_label=gtk.Label(' Cryojet Control '))
    win.add(book)
    win.show_all()

    try:
        gtk.main()
    finally:
        myviewer.video.stop()


if __name__ == '__main__':
    main()
