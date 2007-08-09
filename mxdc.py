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


def on_create_run(sm, cm):
    cm.add_run( sm.get_run_data() )
    return True
    
def main():
    gtk.window_set_auto_startup_notification(True)    
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_title("MX Data Collector")
    
    config_dir = os.environ['HOME'] + '/.mxdc'
    if not os.access( config_dir , os.R_OK):
        if os.access( os.environ['HOME'], os.W_OK):
            os.mkdir( config_dir )
            
    scan_manager = ScanManager()
    collect_manager = CollectManager()
    scan_manager.connect('create-run', on_create_run, collect_manager)
    hutch_manager = HutchManager()
    status_panel = StatusPanel()
    general_log = LogView(label='Log')
    general_log.set_expanded(True)
    LogServer.connect('log', general_log.on_log)

    main_vbox = gtk.VBox(False,0)
    main_vbox.pack_end(status_panel, expand = False, fill = False)
    main_vbox.pack_end(general_log, expand=True, fill=True)
    notebook = gtk.Notebook()
    notebook.append_page(hutch_manager, tab_label=gtk.Label('Beamline Setup'))
    notebook.append_page(collect_manager, tab_label=gtk.Label('Data Collection'))
    notebook.set_border_width(6)

    main_vbox.pack_start(notebook, expand=False, fill=True)
    win.add(main_vbox)
    win.show_all()
    notebook.append_page(scan_manager, tab_label=gtk.Label('Fluorescence Scans'))
    
    win.show_all()
    try:
        gtk.window_set_auto_startup_notification(True)    
        gtk.main()
    finally:
        scan_manager.stop()
        hutch_manager.stop()
        collect_manager.stop()
        sys.exit()
        

if __name__ == "__main__":
    main()
