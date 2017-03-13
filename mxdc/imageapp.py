#!/usr/bin/env python
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
from mxdc.utils.log import get_module_logger, log_to_console
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.widgets import dialogs
import sys, os

_logger = get_module_logger('ImageViewer')

def main():

    win = Gtk.Window()
    dialogs.MAIN_WINDOW = win
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
