import gi

gi.require_version('Gtk', '3.0')
from twisted.internet import gtk3reactor

gtk3reactor.install()
from mxdc.conf import settings
from mxdc.services import server
from mxdc.beamlines.mx import MXBeamline
from mxdc.utils import mdns
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import get_project_name, identifier_slug
from mxdc.widgets.HutchWindow import AppWindow
from mxdc.widgets import dialogs
from mxdc.utils import excepthook, misc
from mxdc.services import clients
from twisted.internet import reactor
from twisted.spread import pb
import os
import time
import warnings
import logging
from gi.repository import Gtk, GObject

USE_TWISTED = True
MXDC_PORT = misc.get_free_tcp_port() #9898

warnings.simplefilter("ignore")

logger = get_module_logger(__name__)


class HutchApp(object):
    def run(self):
        run_main_loop(self.start)

    def start(self):
        # Create application window
        self.session_active = False
        self.main_window = AppWindow()
        self.beamline = MXBeamline()

        self.hook = excepthook.ExceptHook(
            emails=self.beamline.config['bug_report'], exit_function=exit_main_loop
        )
        self.hook.install()

        self.find_service()
        self.main_window.connect('destroy', self.do_quit)
        self.main_window.run()

    def find_service(self):
        self.remote_mxdc = None
        self.service_type = '_mxdc_{}._tcp'.format(identifier_slug(self.beamline.name))
        self.remote_mxdc = clients.MxDCClientFactory(self.service_type)()



    def do_quit(self, obj=None):
        logger.info('Stopping ...')
        exit_main_loop()


def run_main_loop(func):
    if USE_TWISTED:
        reactor.callWhenRunning(func)
        reactor.run()
    else:
        GObject.idle_add(func)
        Gtk.main()


def clear_loggers():
    # disconnect all log handlers first
    logger = logging.getLogger('')
    for h in logger.handlers:
        logger.removeHandler(h)


def exit_main_loop():
    clear_loggers()
    if USE_TWISTED:
        reactor.stop()
    else:
        Gtk.main_quit()


