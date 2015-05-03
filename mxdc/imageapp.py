#!/usr/bin/env python

from gi.repository import Gdk
from gi.repository import Gtk
from mxdc.utils.log import get_module_logger, log_to_console
from mxdc.widgets.imageviewer import ImageViewer
import sys, os

_logger = get_module_logger('ImageViewer')

def main():

    win = Gtk.Window()
    win.connect("destroy", lambda x: Gtk.main_quit())
    
    win.set_title("Diffraction Image Viewer")
    myviewer = ImageViewer(int(Gdk.Screen.height() * 0.75))
    win.add(myviewer)
    win.show_all()
    if len(sys.argv) >= 2:
        myviewer.open_image(os.path.abspath(sys.argv[1]))  
    Gtk.main()


if __name__ == '__main__':
    try:
        log_to_console()
        main()
    finally:
        _logger.info('Stopping...')
