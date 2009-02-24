import gtk, gobject
import sys, os
import logging

from zope.component import globalSiteManager as gsm
from mxdc.widgets.collectmanager import CollectManager
from mxdc.widgets.scanmanager import ScanManager
from mxdc.widgets.hutchmanager import HutchManager
from mxdc.widgets.textviewer import TextViewer, GUIHandler
from bcm.utils.log import get_module_logger, log_to_console
from bcm.beamline.interfaces import IBeamline
from StatusPanel import StatusPanel

_logger = get_module_logger('mxdc')
SHARE_DIR = os.path.join(os.path.dirname(__file__), 'share')

class AppWindow(gtk.Window):
    def __init__(self):
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self.set_position(gtk.WIN_POS_CENTER)
        icon_file = os.path.join(SHARE_DIR, 'icon.png')
        pixbuf = gtk.gdk.pixbuf_new_from_file(icon_file)        
        self.set_icon (pixbuf)
        
        #associate beamline devices
        self.beamline = gsm.getUtility(IBeamline, 'bcm.beamline')

        self.scan_manager = ScanManager()
        self.collect_manager = CollectManager()
        self.scan_manager.connect('create-run', self.on_create_run)
        
        self.hutch_manager = HutchManager()
        self.status_panel = StatusPanel(self.beamline)
        
        main_vbox = gtk.VBox(False,0)
        main_vbox.pack_end(self.status_panel, expand = False, fill = False)
        
        notebook = gtk.Notebook()
        notebook.append_page(self.hutch_manager, tab_label=gtk.Label('  Beamline Setup  '))
        notebook.append_page(self.collect_manager, tab_label=gtk.Label('  Collect Data '))
        notebook.append_page(self.scan_manager, tab_label=gtk.Label('  MAD Scan  '))
        notebook.set_border_width(6)

        main_vbox.pack_start(notebook, expand=False, fill=True)
        self.add(main_vbox)
       
        self.show_all()
            
    def on_create_run(self, obj=None, arg=None):
        run_data = self.scan_manager.get_run_data()
        self.collect_manager.add_run( run_data )
        
