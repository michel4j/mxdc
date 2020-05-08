import logging
import os
import signal
import sys
import warnings
from datetime import datetime

import gi

warnings.simplefilter("ignore")
gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, Gio, GLib, Gdk
from twisted.internet import gtk3reactor

gtk3reactor.install()

from mxdc import conf

from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import identifier_slug
from mxdc.controllers import common, chat
from mxdc.controllers import samples, setup, status
from mxdc.widgets import dialogs

from mxdc.utils import excepthook, misc, gui
from mxdc.services import clients
from mxdc.beamlines import build_beamline
from twisted.internet import reactor
from . import version

USE_TWISTED = True
MXDC_PORT = misc.get_free_tcp_port()  # 9898

VERSION = version.get_version()
COPYRIGHT = "Copyright (c) 2006-{}, Canadian Light Source, Inc. All rights reserved.".format(datetime.now().year)

logger = get_module_logger(__name__)


class AppBuilder(gui.Builder):
    gui_roots = {
        'data/mxdc_hutch': [
            'app_window', 'chat_avatars_pop'
        ]
    }

    def __init__(self):
        super(AppBuilder, self).__init__()
        self.notifier = common.AppNotifier(
            self.notification_lbl,
            self.notification_revealer,
            self.notification_btn
        )
        self.status_monitor = common.StatusMonitor(self)
        self.main_stack.connect('notify::visible-child', self.on_page_switched)

    def on_page_switched(self, stack, params):
        stack.child_set(stack.props.visible_child, needs_attention=False)


class Application(Gtk.Application):
    def __init__(self, dark=False, **kwargs):
        super(Application, self).__init__(application_id="org.mxdc.hutch", **kwargs)
        self.window = None
        self.settings_active = False
        self.dark_mode = dark
        self.resource_data = GLib.Bytes.new(misc.load_binary_data(os.path.join(conf.SHARE_DIR, 'mxdc.gresource')))
        self.resources = Gio.Resource.new_from_data(self.resource_data)
        Gio.resources_register(self.resources)
        gui.register_icons()
        self.connect('shutdown', self.on_shutdown)

    def do_startup(self):
        Gtk.Application.do_startup(self)

        # build GUI
        self.builder = AppBuilder()

        # initialize beamline
        self.beamline = build_beamline()
        logger.info('Starting HutchViewer ({})... '.format(self.beamline.name))
        self.hook = excepthook.ExceptHook(
            name='HutchViewer',
            emails=self.beamline.config['bug_report'], exit_function=self.quit
        )
        # self.hook.install()
        self.find_service()

    def do_activate(self):
        # We only allow a single window and raise any existing ones
        if not self.window:
            self.window = self.builder.app_window
            self.window.connect('destroy', self.on_quit)

            #app_settings = self.window.get_settings()
            app_settings = Gtk.Settings.get_default()
            app_settings.props.gtk_enable_animations = True
            app_settings.props.gtk_application_prefer_dark_theme = self.dark_mode

            css = Gtk.CssProvider()
            with open(os.path.join(conf.SHARE_DIR, 'styles.less'), 'rb') as handle:
                css_data = handle.read()
                css.load_from_data(css_data)
            style = self.window.get_style_context()
            style.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            dialogs.MAIN_WINDOW = self.window

            # setup panels
            self.samples = samples.HutchSamplesController(self.builder)
            self.hutch_manager = setup.SetupController(self.builder)
            self.status_panel = status.StatusPanel(self.builder)
            self.chat = chat.ChatController(self.builder)
            self.window.show_all()

        self.window.present()

    def on_quit(self, *args, **kwargs):
        self.quit()

    def find_service(self):
        self.remote_mxdc = None
        self.service_type = '_mxdc_{}._tcp.local.'.format(identifier_slug(self.beamline.name))
        self.remote_mxdc = clients.MxDCClientFactory(self.service_type)()

    def on_shutdown(self, *args):
        logger.info('Stopping ...')
        self.beamline.cleanup()
        clear_loggers()


def clear_loggers():
    # disconnect all log handlers first
    logger = logging.getLogger('')
    for h in logger.handlers:
        logger.removeHandler(h)


class HutchApp(object):
    def __init__(self, dark=False):
        self.application = Application(dark=dark)

    def run(self):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.application.quit)
        if USE_TWISTED:
            reactor.registerGApplication(self.application)
            reactor.run()
        else:
            self.application.run(sys.argv)
