import gtk, gobject
from CollectManager import CollectManager
from HutchManager import HutchManager
from StatusPanel import StatusPanel
from ScanManager import ScanManager
from LogView import LogView


class MainWindow(object):
    def __init__(self, beamline):
        self.win = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.win.set_position(gtk.WIN_POS_CENTER)
        
        self.beamline = beamline
        
        self.scan_manager = ScanManager(self.beamline)
        self.collect_manager = CollectManager(self.beamline)
        self.scan_manager.connect('create-run', self.on_create_run)
        
        self.hutch_manager = HutchManager(self.beamline)
        self.status_panel = StatusPanel(self.beamline)
        self.general_log = LogView(label='Log')
        self.general_log.set_expanded(True)

        main_vbox = gtk.VBox(False,0)
        main_vbox.pack_end(self.status_panel, expand = False, fill = False)
        main_vbox.pack_end(self.general_log, expand=True, fill=True)
        
        notebook = gtk.Notebook()
        notebook.append_page(self.hutch_manager, tab_label=gtk.Label('Beamline Setup'))
        notebook.append_page(self.collect_manager, tab_label=gtk.Label('Data Collection'))
        notebook.append_page(self.scan_manager, tab_label=gtk.Label('Fluorescence Scans'))
        notebook.set_border_width(6)

        main_vbox.pack_start(notebook, expand=False, fill=True)
        self.win.add(main_vbox)
        
        self.win.connect('destroy', self.on_destroy)
        self.win.connect('destroy', lambda x: gtk.main_quit())
        self.win.show_all()
        
    def on_destroy(self, obj=None):
        self.scan_manager.stop()
        self.collect_manager.stop()
        self.hutch_manager.stop()

    def on_create_run(self, obj=None, arg=None):
        run_data = self.scan_manager.get_run_data()
        self.collect_manager.add_run( run_data )
