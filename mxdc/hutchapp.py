'''
Created on Jun 2, 2010

@author: michel
'''
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
from mxdc.widgets.hutchmanager import HutchManager
from mxdc.widgets.misc import CryojetWidget
#from mxdc.utils import gtkexcepthook

_logger = get_module_logger('hutchviewer')

def main():

    win = gtk.Window()
    win.connect("destroy", lambda x: reactor.stop())
    win.set_border_width(6)
    win.set_size_request(1167,815)
    
    win.set_title("HutchViewer")
 
    try:
        config = os.path.join(os.environ['BCM_CONFIG_PATH'],
                              os.environ['BCM_CONFIG_FILE'])
    except:
        _logger.error('Could not fine Beamline Control Module environment variables.')
        _logger.error('Please make sure MXDC is properly installed and configured.')
        sys.exit(1)
    bl = MXBeamline(config)
    
    myviewer = HutchManager()
    myviewer.show_all()

    win.add(myviewer)
    win.show_all()


if __name__ == '__main__':
    try:
        reactor.callWhenRunning(main)
        reactor.run()
    finally:
        _logger.info('Stopping...')

