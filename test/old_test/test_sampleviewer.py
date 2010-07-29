#!/usr/bin/env python

import warnings
warnings.simplefilter("ignore")
import gtk, gobject
import sys, os
import logging
import time

from bcm.beamline.mx import MXBeamline
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.misc import CryojetWidget
from bcm.utils import gtkexcepthook
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
    config_file = '/media/seagate/beamline-control-module/etc/08id1.conf'
    bl = MXBeamline(config_file)
    
    myviewer = SampleViewer()
    myviewer.show_all()
    #cryo_controller = CryojetWidget(bl.cryojet)
    #cryo_align = gtk.Alignment(0.5,0.5, 0, 0)
    #cryo_align.set_border_width(12)
    #cryo_align.add(cryo_controller)
    #cryo_controller.set_border_width(6)

    book.append_page(myviewer, tab_label=gtk.Label(' Sample Camera ') )
    #book.append_page(cryo_align, tab_label=gtk.Label(' Cryojet Control '))
    win.add(book)
    win.show_all()
    gtk.threads_init()
    gtk.main()


if __name__ == '__main__':
    main()