import logging
import os
import sys
import warnings
from datetime import datetime

import gi

warnings.simplefilter("ignore")
gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, Gio
from twisted.internet import gtk3reactor

gtk3reactor.install()

from mxdc import conf
from mxdc.beamlines.mx import MXBeamline
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import identifier_slug
from mxdc.widgets.HutchWindow import AppWindow
from mxdc.utils import excepthook, misc
from mxdc.services import clients
from twisted.internet import reactor

USE_TWISTED = True
MXDC_PORT = misc.get_free_tcp_port()  # 9898
VERSION = "2017.10"
COPYRIGHT = "Copyright (c) 2006-{}, Canadian Light Source, Inc. All rights reserved.".format(datetime.now().year)

logger = get_module_logger(__name__)


class Application(Gtk.Application):
    def __init__(self, **kwargs):
        super(Application, self).__init__(application_id="org.mxdc.hutch", **kwargs)
        self.window = None
        self.settings_active = False
        self.resources = Gio.Resource.load(os.path.join(conf.SHARE_DIR, 'mxdc.gresource'))
        Gio.resources_register(self.resources)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        action = Gio.SimpleAction.new("about", None)
        action.connect("activate", self.on_about)
        self.add_action(action)

        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self.on_quit)
        self.add_action(action)

        action = Gio.SimpleAction.new("help", None)
        action.connect("activate", self.on_help)
        self.add_action(action)

    def do_activate(self):
        # We only allow a single window and raise any existing ones
        if not self.window:
            # Windows are associated with the application
            self.window = AppWindow(application=self, title='Hutch Viewer')
            self.window.connect('destroy', lambda x: self.quit())
            self.start()
        self.window.present()

    def on_about(self, action, param):
        authors = [
            "Michel Fodje",
            "Kathryn Janzen",
            "Kevin Anderson",
            "Cuylar Conly"
        ]
        name = 'MxDC Hutch Viewer'
        about = Gtk.AboutDialog(transient_for=self.window, modal=True)
        about.set_program_name(name)
        about.set_version(VERSION)
        about.set_copyright(COPYRIGHT)
        about.set_comments("Program for macromolecular crystallography data acquisition.")
        about.set_website("http://cmcf.lightsource.ca")
        about.set_authors(authors)
        about.set_logo(self.window.get_icon())
        about.present()

    def on_help(self, action, param):
        import webbrowser
        url = os.path.join(conf.DOCS_DIR, 'index.html')
        webbrowser.open(url, autoraise=True)

    def on_quit(self, action, param):
        self.quit()

    def start(self):
        self.beamline = MXBeamline()
        self.hook = excepthook.ExceptHook(
            emails=self.beamline.config['bug_report'], exit_function=exit_main_loop
        )
        self.hook.install()
        self.find_service()
        self.window.setup()

    def find_service(self):
        self.remote_mxdc = None
        self.service_type = '_mxdc_{}._tcp'.format(identifier_slug(self.beamline.name))
        self.remote_mxdc = clients.MxDCClientFactory(self.service_type)()

    def quit(self):
        logger.info('Stopping ...')
        if self.remote_mxdc and self.remote_mxdc.is_active():
            self.remote_mxdc.leave()
        clear_loggers()
        super(Application, self).quit()


def clear_loggers():
    # disconnect all log handlers first
    logger = logging.getLogger('')
    for h in logger.handlers:
        logger.removeHandler(h)


def exit_main_loop():
    clear_loggers()
    reactor.stop()


class HutchApp(object):
    def __init__(self):
        self.application = Application()

    def run(self):
        if USE_TWISTED:
            reactor.registerGApplication(self.application)
            reactor.run()
        else:
            self.application.run(sys.argv)
