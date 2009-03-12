#!/usr/bin/env python

import warnings
warnings.simplefilter("ignore")
import sys, os
import logging
import time

from twisted.internet import glib2reactor
glib2reactor.install()
from twisted.internet import reactor

import gtk
import gobject

from bcm.beamline.mx import MXBeamline
from bcm.utils.log import get_module_logger
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.utils import gtkexcepthook

_logger = get_module_logger('ImageViewer')

def main():

    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    
    win.set_title("Diffraction Image Viewer")
    myviewer = ImageViewer(800)
    win.add(myviewer)
    win.show_all()
    gtk.main()


if __name__ == '__main__':
    try:
        main()
    finally:
        _logger.info('Stopping...')

