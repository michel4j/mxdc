#!/usr/bin/env python

import threading
import gtk, gobject
import sys, os
from random import *
import time

gobject.threads_init()

from ImgViewer import ImgViewer
from CollectManager import CollectManager
from HutchManager import HutchManager
from StatusPanel import StatusPanel
from LogView import LogView
from ScanManager import ScanManager
from LogServer import LogServer
from Beamline import init_beamline

class AppClass:
    def __init__(self):
        self.splash = gtk.Window()
        self.splash.set_size_request(480,300)
        self.splash.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_SPLASHSCREEN)
        self.splash.set_gravity(gtk.gdk.GRAVITY_CENTER)
        self.splash_frame = gtk.Frame()
        self.splash_frame.set_shadow_type(gtk.SHADOW_OUT)
        self.img = gtk.Image()
        self.img.show()
        self.img.set_from_file(sys.path[0] + '/images/splash.png')
        vbox = gtk.VBox(False,0)
        vbox.pack_start(self.img, expand=False, fill=False)
        self.splash_frame.add( vbox )
        self.pbar = gtk.ProgressBar()
        vbox.pack_end(self.pbar)
        self.splash.add(self.splash_frame)
        self.splash.set_position(gtk.WIN_POS_CENTER)        
        self.win = gtk.Window()
        self.win.set_position(gtk.WIN_POS_CENTER)
        self.splash.set_transient_for(self.win)
        self.splash.show_all()
        self.win.connect("destroy", lambda x: gtk.main_quit())
        self.win.set_title("MX Data Collector")
        self.splash.connect('map-event', self.run)
        
        # create configuration directory if none exists
        config_dir = os.environ['HOME'] + '/.mxdc'
        if not os.access( config_dir , os.R_OK):
            if os.access( os.environ['HOME'], os.W_OK):
                os.mkdir( config_dir )
        
    def on_create_run(self, obj=None, arg=None):
        run_data = self.scan_manager.get_run_data()
        self.collect_manager.add_run( run_data )
    
    def run(self, obj=None, arg=None):
        while gtk.events_pending():
            gtk.main_iteration()
        win = gtk.Window(gtk.WINDOW_TOPLEVEL)
        win.set_position(gtk.WIN_POS_CENTER)
        gtk.window_set_auto_startup_notification(False)
        init_beamline(self.pbar)
        self.scan_manager = ScanManager()
        self.collect_manager = CollectManager()
        self.scan_manager.connect('create-run', self.on_create_run)
        self.hutch_manager = HutchManager()
        self.status_panel = StatusPanel()
        self.general_log = LogView(label='Log')
        self.general_log.set_expanded(True)
        LogServer.connect('log', self.general_log.on_log)

        main_vbox = gtk.VBox(False,0)
        main_vbox.pack_end(self.status_panel, expand = False, fill = False)
        main_vbox.pack_end(self.general_log, expand=True, fill=True)
        notebook = gtk.Notebook()
        notebook.append_page(self.hutch_manager, tab_label=gtk.Label('Beamline Setup'))
        notebook.append_page(self.collect_manager, tab_label=gtk.Label('Data Collection'))
        notebook.append_page(self.scan_manager, tab_label=gtk.Label('Fluorescence Scans'))
        notebook.set_border_width(6)

        main_vbox.pack_start(notebook, expand=False, fill=True)
        main_vbox.show_all()
        self.win.add(main_vbox)
        gtk.window_set_auto_startup_notification(False)        
        self.win.show()
        while gtk.events_pending():
            gtk.main_iteration()
        gobject.timeout_add(100, self.splash.hide)

    def stop(self):
        self.scan_manager.stop()
        self.collect_manager.stop()
        self.hutch_manager.stop()

if __name__ == "__main__":
    try:
        app = AppClass()
        gtk.main()
    finally:
        app.stop()
        sys.exit()
