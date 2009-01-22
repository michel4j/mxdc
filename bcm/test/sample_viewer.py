#!/usr/bin/env python

import warnings
warnings.simplefilter("ignore")
import gtk, gobject
import sys, os
import logging

sys.path.append(os.environ['BCM_PATH'])

from bcm.beamline import PX
from mxdc.gui.SampleViewer import SampleViewer
from mxdc.gui.ActiveWidgets import CryojetWidget

# set up logging to file
try:
    logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s : %(message)s',
                    datefmt='%a, %d %b %Y %H:%M:%S',
                    filename='/tmp/mxdc_sample.log',
                    filemode='a')
except:
    logging.basicConfig()
    lgr= logging.getLogger('')
    lgr.setLevel(logging.DEBUG)
    #hdlr = logging.RotatingFileHandler('/tmp/mxdc', "a", 5000, 3)
    #fmt = logging.Formatter('%(asctime)s %(levelname)s : %(message)s', "%x %X")
    #hdlr.setFormatter(fmt)
    #lgr.addHandler(hdlr)

    
# define a Handler which writes INFO messages or higher to the sys.stderr
console = logging.StreamHandler()
console.setLevel(logging.NOTSET)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s : %(message)s')
console.setFormatter(formatter)
logging.getLogger('').addHandler(console)

def main():

    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("SampleViewer")
    book = gtk.Notebook()
    #win.add(book)
    bl = PX('08id1-sample.conf')
    bl.setup()
    
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
