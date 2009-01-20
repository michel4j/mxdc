import gtk, gobject
import sys, os

from CollectManager import CollectManager
from StatusPanel import StatusPanel
from ScanManager import ScanManager
from HutchManager import HutchManager
from SampleManager import SampleManager
from LogView import LogView, GUIHandler
import logging

class AppWindow(gtk.Window):
    def __init__(self, beamline):
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self.set_position(gtk.WIN_POS_CENTER)
        icon_file = os.environ['BCM_PATH'] + '/mxdc/gui/images/icon.png'
        pixbuf = gtk.gdk.pixbuf_new_from_file(icon_file)        
        self.set_icon (pixbuf)
        
        self.beamline = beamline
        self.scan_manager = ScanManager(self.beamline)
        self.collect_manager = CollectManager(self.beamline)
        self.scan_manager.connect('create-run', self.on_create_run)
        
        self.hutch_manager = HutchManager(self.beamline)
        #self.sample_manager = SampleManager(self.beamline)
        self.status_panel = StatusPanel(self.beamline)
        self.general_log = LogView(label='Log')
        self.general_log.set_expanded(False)
        self.log_handler = GUIHandler(self.general_log)
        self.log_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s %(name)-15s: %(levelname)-8s %(message)s')
        self.log_handler.setFormatter(formatter)
        logging.getLogger('').addHandler(self.log_handler)
        
        main_vbox = gtk.VBox(False,0)
        main_vbox.pack_end(self.status_panel, expand = False, fill = False)
        main_vbox.pack_end(self.general_log, expand=True, fill=True)
        
        notebook = gtk.Notebook()
        notebook.append_page(self.hutch_manager, tab_label=gtk.Label('  Beamline Setup  '))
        #notebook.append_page(self.sample_manager, tab_label=gtk.Label('  Sample  '))
        notebook.append_page(self.collect_manager, tab_label=gtk.Label('  Collect Data '))
        notebook.append_page(self.scan_manager, tab_label=gtk.Label('  MAD Scan  '))
        notebook.set_border_width(6)

        main_vbox.pack_start(notebook, expand=False, fill=True)
        self.add(main_vbox)
       
        self.connect('destroy', self.on_destroy)
        self.show_all()
            
    def on_destroy(self, obj=None):
        self.scan_manager.stop()
        self.collect_manager.stop()
        self.hutch_manager.stop()

    def on_create_run(self, obj=None, arg=None):
        run_data = self.scan_manager.get_run_data()
        self.collect_manager.add_run( run_data )
        
