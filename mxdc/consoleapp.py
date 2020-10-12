import logging
import os
import sys
import signal
import gi

from datetime import datetime
from IPython.terminal.embed import InteractiveShellEmbed
from traitlets.config import Config

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gio, GLib
from twisted.internet import gtk3reactor
gtk3reactor.install()


from mxdc import conf
from mxdc.utils.log import get_module_logger
from mxdc.utils import gui, misc
from mxdc.widgets import dialogs
from mxdc.controllers import scanplot, common
from mxdc.beamlines import build_beamline
from twisted.internet import reactor

USE_TWISTED = True
MXDC_PORT = misc.get_free_tcp_port()  # 9898
VERSION = "2020.02"
COPYRIGHT = "Copyright (c) 2006-{}, Canadian Light Source, Inc. All rights reserved.".format(datetime.now().year)

logger = get_module_logger(__name__)


class AppBuilder(gui.Builder):
    gui_roots = {
        'data/scanplot': ['scan_window',]
    }


class Application(Gtk.Application):
    def __init__(self, **kwargs):
        super(Application, self).__init__(application_id="org.mxdc.console", **kwargs)
        self.builder = None
        self.window = None
        self.terminal = None
        self.ipshell = None
        self.shell_vars = []
        self.shell_config = Config()
        # initialize beamline
        self.beamline = build_beamline(console=True)

        self.resource_data = GLib.Bytes.new(misc.load_binary_data(os.path.join(conf.SHARE_DIR, 'mxdc.gresource')))
        self.resources = Gio.Resource.new_from_data(self.resource_data)
        Gio.resources_register(self.resources)
        self.connect('shutdown', self.on_shutdown)

    def do_startup(self, *args):
        Gtk.Application.do_startup(self, *args)
        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self.on_quit)
        self.add_action(action)

    def do_activate(self, *args):
        self.builder = AppBuilder()
        self.window = self.builder.scan_window
        self.window.set_deletable(False)
        self.plot = scanplot.ScanPlotter(self.builder)
        self.log_viewer = common.LogMonitor(self.builder.scan_log, font='Candara 7')
        log_handler = common.GUIHandler(self.log_viewer)
        log_handler.setLevel(logging.NOTSET)
        formatter = logging.Formatter('%(asctime)s [%(name)s] %(message)s', '%b/%d %H:%M:%S')
        log_handler.setFormatter(formatter)
        logging.getLogger('').addHandler(log_handler)
        dialogs.MAIN_WINDOW = self.window
        self.window.present()
        if self.beamline.is_ready():
            self.shell()
        else:
            self.beamline.connect('ready', self.shell)

    def shell(self, *args, **kwargs):
        import numpy
        from mxdc.engines.scripting import get_scripts
        from mxdc.engines.scanning import AbsScan, AbsScan2, RelScan, RelScan2, GridScan, SlewScan, SlewGridScan
        from mxdc.utils import fitting
        from mxdc.com.ca import PV

        self.shell_config.InteractiveShellEmbed.colors = 'Neutral'
        self.shell_config.InteractiveShellEmbed.color_info = True
        self.shell_config.InteractiveShellEmbed.true_color = True
        self.shell_config.InteractiveShellEmbed.banner2 = '{} Beamline Console\n'.format(self.beamline.name)
        bl = self.beamline

        plot = self.plot
        fit = self.plot.fit
        self.shell_vars = {'plot': plot, 'fit': fit}
        self.builder.scan_beamline_lbl.set_text(bl.name)
        self.ipshell = InteractiveShellEmbed.instance(config=self.shell_config)
        self.ipshell.magic('%gui gtk3')
        self.ipshell()
        print('Stopping ...')
        self.window.destroy()

        reactor.stop()

    def on_quit(self, *args, **kwargs):
        self.quit()

    def on_shutdown(self, *args):
        logger.info('Stopping ...')
        self.ipshell.dummy_mode = True
        self.beamline.cleanup()

        _log = logging.getLogger('')
        for h in _log.handlers:
            _log.removeHandler(h)


class ConsoleApp(object):
    def __init__(self):
        self.application = Application()

    def run(self):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.application.quit)
        if USE_TWISTED:
            reactor.registerGApplication(self.application)
            reactor.run()
        else:
            self.application.run(sys.argv)



