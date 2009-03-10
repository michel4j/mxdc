#!/usr/bin/env python

import warnings
warnings.simplefilter("ignore")
import gtk, gobject
import sys, os
import logging
import time

from twisted.internet import glib2reactor
glib2reactor.install()
from twisted.internet import reactor

from bcm.beamline.mx import MXBeamline
from bcm.utils.log import get_module_logger
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.misc import CryojetWidget
from mxdc.utils import gtkexcepthook

_logger = get_module_logger('sampleviewer')

def main():

    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(6)
    win.set_size_request(800,540)
    
    win.set_title("SampleViewer")
    book = gtk.Notebook()
    #win.add(book)
    try:
        config = os.path.join(os.environ['BCM_CONFIG_PATH'],
                              os.environ['BCM_CONFIG_FILE'])
    except:
        _logger.error('Could not fine Beamline Control Module environment variables.')
        _logger.error('Please make sure MXDC is properly installed and configured.')
        sys.exit(1)
    bl = MXBeamline(config)
    
    myviewer = SampleViewer()
    myviewer.show_all()
    cryo_controller = CryojetWidget(bl.cryojet)
    cryo_align = gtk.Alignment(0.5,0.5, 0, 0)
    cryo_align.set_border_width(12)
    cryo_align.add(cryo_controller)
    cryo_controller.set_border_width(6)

    book.append_page(myviewer, tab_label=gtk.Label(' Sample Camera ') )
    book.append_page(cryo_align, tab_label=gtk.Label(' Cryojet Control '))
    win.add(book)
    win.show_all()
    gtk.main()


if __name__ == '__main__':
    try:
        main()
    finally:
        _logger.info('Stopping...')

