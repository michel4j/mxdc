import gtk, gobject
import gtk.glade
import sys, os
import logging

from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from mxdc.widgets.collectmanager import CollectManager
from mxdc.widgets.scanmanager import ScanManager
from mxdc.widgets.hutchmanager import HutchManager
from mxdc.widgets.screeningmanager import ScreenManager
from bcm.utils.log import get_module_logger, log_to_console
from mxdc.widgets.splash import Splash
from mxdc.widgets.statuspanel import StatusPanel

_logger = get_module_logger('mxdc')
SHARE_DIR = os.path.join(os.path.dirname(__file__), 'share')

class AppWindow(gtk.Window):
    def __init__(self):
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self.set_position(gtk.WIN_POS_CENTER)
        icon_file = os.path.join(SHARE_DIR, 'icon.png')
        pixbuf = gtk.gdk.pixbuf_new_from_file(icon_file)        
        self.set_icon (pixbuf)
        
        self.splash = Splash(version='3.0.0', color='#fffffe')
        self.splash.win.set_transient_for(self)
        while gtk.events_pending():
            gtk.main_iteration()
        
    def run(self):
        gobject.timeout_add(1000, lambda: self.splash.win.hide())         
        self.scan_manager = ScanManager()
        self.collect_manager = CollectManager()
        self.scan_manager.connect('create-run', self.on_create_run)       
        self.hutch_manager = HutchManager()
        self.screen_manager = ScreenManager()
        self.status_panel = StatusPanel()
        
        self._xml = gtk.glade.XML(os.path.join(SHARE_DIR, 'mxdc_main.glade'), 'mxdc_main')
        self.main_frame = self._xml.get_widget('main_frame')
        self.mxdc_main = self._xml.get_widget('mxdc_main')
        self.quit_cmd = self._xml.get_widget('quit_command')
        self.about_cmd = self._xml.get_widget('about_cmd')
        self.quit_cmd.connect('activate', lambda x: self._do_quit() )
        self.about_cmd.connect('activate', lambda x:  self._do_about() )
        
        notebook = gtk.Notebook()
        notebook.append_page(self.hutch_manager, tab_label=gtk.Label('  Beamline Setup  '))
        notebook.append_page(self.collect_manager, tab_label=gtk.Label('  Data Collection '))
        notebook.append_page(self.scan_manager, tab_label=gtk.Label('  Fluorescence Scans  '))
        notebook.append_page(self.screen_manager, tab_label=gtk.Label('  Screening  '))
        #self.screen_manager.set_sensitive(False)
        notebook.set_border_width(6)

        self.main_frame.add(notebook)
        self.mxdc_main.pack_start(self.status_panel, expand = False, fill = False)
        #self.status_bar.pack_end(gtk.Label('Beamline'))
        self.add(self.mxdc_main)
        self.show_all()
        
    def _do_quit(self):
        self.hide()
        self.emit('destroy')
             
    def _do_about(self):
        authors = [
            "Michel Fodje (maintainer)",
            "Kevin Anderson",
            ]
        about = gobject.new(gtk.AboutDialog, name="MX Data Collector",
                            version="3.0.0 RC3", copyright="(C) Canadian Light Source, Inc",
                            comments="Program for macromolecular crystallography data acquisition.",
                            authors=authors)
        about.connect('destroy', lambda x: about.destroy())
        about.set_transient_for(self)
        about.show()

    def on_create_run(self, obj=None, arg=None):
        run_data = self.scan_manager.get_run_data()
        self.collect_manager.add_run( run_data )
        
