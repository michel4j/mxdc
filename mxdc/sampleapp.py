#!/usr/bin/env python

import warnings
warnings.simplefilter("ignore")
import sys, os
import logging
import time

from twisted.internet import glib2reactor
glib2reactor.install()
from twisted.internet import reactor

from gi.repository import Gtk
from gi.repository import GObject

from mxdc.beamline.mx import MXBeamline
from mxdc.utils.log import get_module_logger
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.misc import CryojetWidget

_logger = get_module_logger('sampleviewer')
    
def main():

    win = Gtk.Window()
    win.connect("destroy", lambda x: reactor.stop())
    win.set_border_width(6)
    win.set_size_request(800,540)
    
    win.set_title("SampleViewer")
    book = Gtk.Notebook()
    #win.add(book)
    try:
        _ = os.environ['MXDC_CONFIG_PATH']
    except:
        _logger.error('Could not fine Beamline Control Module environment variables.')
        _logger.error('Please make sure MXDC is properly installed and configured.')
        sys.exit(1)
    bl = MXBeamline()
    
    myviewer = SampleViewer()
    myviewer.show_all()
    cryo_controller = CryojetWidget(bl.cryojet)
    cryo_align = Gtk.Alignment.new(0.5,0.5, 0, 0)
    cryo_align.set_border_width(12)
    cryo_align.add(cryo_controller)
    cryo_controller.set_border_width(6)

    book.append_page(myviewer, tab_label=Gtk.Label(label=' Sample Camera ') )
    book.append_page(cryo_align, tab_label=Gtk.Label(label=' Cryojet Control '))
    win.add(book)
    win.show_all()


if __name__ == '__main__':
    try:
        reactor.callWhenRunning(main)
        reactor.run()
    finally:
        _logger.info('Stopping...')

