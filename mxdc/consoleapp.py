import os
import sys
import threading
import gi
import time

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gio, GObject
from mxdc import conf
from mxdc.utils.log import get_module_logger
from mxdc.utils import gui
from mxdc.widgets import dialogs
from mxdc.controllers import scanplot
from mxdc.beamlines.mx import MXBeamline

logger = get_module_logger(__name__)


class AppBuilder(gui.Builder):
    gui_roots = {
        'data/scanplot': ['scan_window',]
    }


class ConsoleApp(object):
    def __init__(self):
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
        Gtk.main_quit()
        sys.exit()

    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setName(self.__class__.__name__)
        worker_thread.start()
        time.sleep(1)
        self.shell()
        Gtk.main_quit()

    def run(self):
        self.resources = Gio.Resource.load(os.path.join(conf.SHARE_DIR, 'mxdc.gresource'))
        Gio.resources_register(self.resources)

        self.builder = AppBuilder()
        self.window = self.builder.scan_window

        dialogs.MAIN_WINDOW = self.window
        self.window.connect("destroy", lambda x: Gtk.main_quit())
        self.plot = scanplot.ScanPlotter(self.builder)
        self.window.show_all()

        try:
            Gtk.main()
        finally:
            logger.info('Stopping...')
