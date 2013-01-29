#!/usr/bin/env python

#import gi
#import gi.pygtkcompat

#gi.pygtkcompat.enable() 
#gi.pygtkcompat.enable_gtk(version='3.0')

import warnings
warnings.simplefilter("ignore")
import sys, os
import logging

import gtk
import gobject

from bcm.utils.log import get_module_logger, log_to_console
from mxdc.widgets.imageviewer import ImageViewer

_logger = get_module_logger('ImageViewer')

def main():

    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    
    win.set_title("Diffraction Image Viewer")
    myviewer = ImageViewer(800)
    win.add(myviewer)
    win.show_all()
    if len(sys.argv) >= 2:
        myviewer.open_image(os.path.abspath(sys.argv[1]))  
    gtk.main()


if __name__ == '__main__':
    try:
        log_to_console()
        main()
    finally:
        _logger.info('Stopping...')

