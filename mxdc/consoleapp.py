import os
import sys
import threading
import gi
import time
import logging
from twisted.internet import gtk3reactor
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gio, GObject

gtk3reactor.install()

from mxdc import conf
from mxdc.utils.log import get_module_logger
from mxdc.utils import gui
from mxdc.widgets import dialogs, textviewer
from mxdc.controllers import scanplot, common
from mxdc.beamlines.mx import MXBeamline
from twisted.internet import reactor

logger = get_module_logger(__name__)


class AppBuilder(gui.Builder):
    gui_roots = {
        'data/scanplot': ['scan_window',]
    }


class ConsoleApp(object):
    def __init__(self):
        self.stopped = False
        self.start()

    def shell(self):
        from IPython import embed
        from mxdc.engines.scripting import get_scripts
        from mxdc.engines.scanning import AbsScan, AbsScan2, RelScan, RelScan2, GridScan, CntScan
        from mxdc.utils import fitting
        import numpy
        bl = MXBeamline(console=True)
        plot = self.plot
        GObject.idle_add(self.builder.scan_beamline_lbl.set_text, bl.name)
        embed()
        GObject.timeout_add(1000, self.quit)

    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setName(self.__class__.__name__)
        worker_thread.setDaemon(True)
        worker_thread.start()
        GObject.idle_add(self.setup)
        self.shell()
        time.sleep(2)
        sys.exit()

    def setup(self):
        self.resources = Gio.Resource.load(os.path.join(conf.SHARE_DIR, 'mxdc.gresource'))
        Gio.resources_register(self.resources)

        self.builder = AppBuilder()
        self.window = self.builder.scan_window

        self.log_viewer = common.LogMonitor(self.builder.scan_log, 'Candara 7')
        log_handler = textviewer.GUIHandler(self.log_viewer)
        log_handler.setLevel(logging.NOTSET)
        formatter = logging.Formatter('%(asctime)s [%(name)s] %(message)s', '%b/%d %H:%M:%S')
        log_handler.setFormatter(formatter)
        logging.getLogger('').addHandler(log_handler)

        dialogs.MAIN_WINDOW = self.window
        self.plot = scanplot.ScanPlotter(self.builder)
        self.window.show_all()

    def run(self):
        Gtk.main()

    def quit(self):
        print("Stopping ...")
        self.window.destroy()
        Gtk.main_quit()

