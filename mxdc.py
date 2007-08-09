#!/usr/bin/env python

import gtk, gobject
import sys, os
from random import *
import time

from ImgViewer import ImgViewer
from CollectManager import CollectManager
from HutchManager import HutchManager
from StatusPanel import StatusPanel
from LogView import LogView
from ScanManager import ScanManager


def update_values(manager, status_panel, log_view):
    status = ['IDLE','BUSY','ERROR','RUN']
    hutch = ['OPEN','CLOSED']
    stv = {}
    posv = {}
    stv['status'] = choice(status)
    stv['hutch'] = choice(hutch)
    stv['shutter'] = choice(hutch)
    stv['energy'] = "%0.5f" % (randrange(4000,18500,1)/1.0e3)
    stv['flux'] = "%0.2e" % (randrange(1,10,1)/1.0e6)
    status_panel.update_values(stv)
    
    posv['distance'] = "%0.2f" % randrange(50,600,1)
    posv['twotheta'] = "%0.2f" % randrange(0,45,1)
    posv['angle'] = "%0.2f" % randrange(0,360,1)
    manager.update_values(posv)

    text = "%s status received from client." % stv['status']
    log_view.log(text)
    return True

def on_create_run(sm, cm):
    cm.add_run( sm.get_run_data() )
    return True
    
def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_title("MX Data Collector Demo")

    scan_manager = ScanManager()
    collect_manager = CollectManager()
    scan_manager.connect('create-run', on_create_run, collect_manager)
    hutch_manager = HutchManager()
    image_viewer = ImgViewer()
    status_panel = StatusPanel()
    general_log = LogView(label='Log')
    general_log.set_expanded(True)

    main_vbox = gtk.VBox(False,0)
    main_hbox = gtk.HBox(False,6)
    main_hbox.set_border_width(6)
    sub_vbox = gtk.VBox(False,0)
    sub_vbox.pack_start(image_viewer, expand = False, fill = False)
    main_hbox.pack_start(sub_vbox,expand = False, fill = False)
    main_hbox.pack_end(collect_manager)
    main_vbox.pack_end(status_panel, expand = False, fill = False)
    main_vbox.pack_end(general_log)
    notebook = gtk.Notebook()
    notebook.append_page(hutch_manager, tab_label=gtk.Label('Beamline Setup'))
    notebook.append_page(main_hbox, tab_label=gtk.Label('Data Collection'))
    notebook.set_border_width(6)

    main_vbox.pack_start(notebook)
    win.add(main_vbox)
    win.show_all()
    notebook.append_page(scan_manager, tab_label=gtk.Label('Fluorescence Scans'))
    
    win.show_all()
    try:
        gtk.main()
    finally:
        hutch_manager.sample_viewer.videothread.stop()
        sys.exit()
        

if __name__ == "__main__":
    main()
