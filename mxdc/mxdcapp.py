import logging
import os
import signal
import sys
import time
from datetime import datetime

import gi

gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, Gio, GLib, Gdk, GdkPixbuf
from twisted.internet import gtk3reactor

gtk3reactor.install()

from mxdc import conf
from mxdc.conf import settings
from mxdc.services import server
from mxdc.utils import mdns, gui
from mxdc.utils.log import get_module_logger
from mxdc.controllers import common, analysis, samples, setup, status, datasets, scans, chat

from mxdc.widgets import dialogs
from mxdc.controllers.settings import SettingsDialog
from mxdc.controllers.browser import Browser
from mxdc.utils import excepthook, misc
from mxdc.beamlines import build_beamline
from mxdc.services import clients
from twisted.internet import reactor
from twisted.spread import pb
from . import version

USE_TWISTED = True
MXDC_PORT = misc.get_free_tcp_port()  # 9898

VERSION = version.get_version()
COPYRIGHT = "Copyright (c) 2006-{}, Canadian Light Source, Inc. All rights reserved.".format(datetime.now().year)

logger = get_module_logger(__name__)


class AppBuilder(gui.Builder):
    gui_roots = {
        'data/mxdc_main': [
            'auto_groups_pop', 'scans_ptable_pop', 'app_window', 'chat_avatars_pop'
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

        for stack in [self.main_stack, self.samples_stack]:
            stack.connect('notify::visible-child', self.on_page_switched)

    def on_page_switched(self, stack, params):
        stack.child_set(stack.props.visible_child, needs_attention=False)


class Application(Gtk.Application):
    def __init__(self, dark=False, **kwargs):
        super(Application, self).__init__(application_id="org.mxdc", **kwargs)
        self.window = None
        self.settings_active = False
        self.dark_mode = dark
        self.resource_data = GLib.Bytes.new(misc.load_binary_data(os.path.join(conf.SHARE_DIR, 'mxdc.gresource')))
        self.resources = Gio.Resource.new_from_data(self.resource_data)
        Gio.resources_register(self.resources)
        gui.register_icons()
        self.connect('shutdown', self.on_shutdown)

    def do_startup(self, *args):
        Gtk.Application.do_startup(self, *args)

        # build GUI
        self.builder = AppBuilder()
        menu = Gtk.Builder.new_from_resource('/org/mxdc/data/menus.ui')

        self.builder.app_menu_btn.set_menu_model(menu.get_object('app-menu'))

        # initialize beamline
        self.beamline = build_beamline()
        logger.info('Starting MxDC ({})... '.format(self.beamline.name))
        self.hook = excepthook.ExceptHook(
            name='MxDC',
            emails=self.beamline.config['bug_report'], exit_function=self.quit
        )

        #self.hook.install()
        self.broadcast_service()

    def do_activate(self, *args):
        # We only allow a single window and raise any existing ones
        if not self.window:
            self.window = self.builder.app_window
            self.window.connect('destroy', self.on_quit)

            # create actions
            actions = {
                'about': (self.on_about, None),
                'dark': (self.on_dark, GLib.Variant.new_boolean(self.dark_mode)),
                'quit': (self.on_quit, None),
                'preferences': (self.on_preferences, None),
                'help': (self.on_help, None),
            }
            for name, (callback, state) in actions.items():
                if state is None:
                    action = Gio.SimpleAction.new(name, None)
                else:
                    action = Gio.SimpleAction.new_stateful(name, None, state)

                action.connect("activate", callback)
                self.window.add_action(action)

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
            self.analysis = analysis.AnalysisController(self.builder)
            self.samples = samples.SamplesController(self.builder)
            self.hutch_manager = setup.SetupController(self.builder)
            self.status_panel = status.StatusPanel(self.builder)
            self.datasets = datasets.DatasetsController(self.builder)
            self.automation = datasets.AutomationController(self.builder)
            self.scans = scans.ScanManager(self.builder)
            self.chat = chat.ChatController(self.builder)
            self.window.show_all()

        self.window.present()

    def on_about(self, action, param):
        authors = [
            "Michel Fodje",
            "Kathryn Janzen",
            "Avatar Icons by Pixel Perfect(www.flaticon.com)"
        ]
        name = 'Mx Data Collector (MxDC)'
        about = Gtk.AboutDialog(transient_for=self.window, modal=True)
        about.set_program_name(name)
        about.set_version(VERSION)
        about.set_copyright(COPYRIGHT)
        about.set_comments("Program for macromolecular crystallography data acquisition.")
        about.set_website("http://cmcf.lightsource.ca")
        about.set_authors(authors)
        about.set_logo(self.window.get_icon())
        about.present()
        about.connect('response', lambda x,y: about.destroy())

    def on_dark(self, action, param):
        """
        Toggle dark mode
        """
        action.set_state(GLib.Variant.new_boolean(not action.get_state()))
        app_settings = Gtk.Settings.get_default()
        app_settings.props.gtk_application_prefer_dark_theme = action.get_state().get_boolean()

    def on_preferences(self, action, param):
        if not self.settings_active:
            self.settings_active = True
            dialog = SettingsDialog(self.window)
            dialog.run()
            self.settings_active = False

    def on_help(self, action, param):
        Browser(self.window)

    def on_quit(self, *args, **kwargs):
        self.quit()

    def broadcast_service(self):
        self.remote_mxdc = None
        self.service_type = '_mxdc._tcp.local.'
        self.service_data = {
            'user': misc.get_project_name(),
            'started': time.asctime(time.localtime()),
            'beamline': self.beamline.name
        }

        try:
            unique = 'SIM' not in self.beamline.name
            self.provider = mdns.Provider(
                'MXDC Client - {}'.format(self.beamline.name),
                self.service_type, MXDC_PORT, self.service_data, unique=unique
            )
            self.provider.connect('collision', self.on_collision)
        except:
            self.on_collision(None)
        else:
            self.start_server()

    def on_collision(self, obj):
        self.remote_mxdc = clients.MxDCClientFactory(self.service_type)()
        self.remote_mxdc.connect('active', self.service_found)

    def service_found(self, obj, state):
        if state and not settings.DEBUG:
            data = self.remote_mxdc.service_data
            msg = 'On <i>{}</i>, by user <i>{}</i> since <i>{}</i>. Only one instance permitted!'.format(
                data['host'], data['data']['user'], data['data']['started']
            )
            if set(self.beamline.config['admin_groups']) & set(os.getgroups()):
                msg += '\n\nDo you want to shut it down?'
                response = dialogs.yesno('MXDC Already Running', msg)
                if response == Gtk.ResponseType.YES:
                    self.beamline.messenger.send('Remote shutdown by staff!')
                    d = self.remote_mxdc.shutdown()
                    d.addCallback(self.start_server)
                else:
                    self.quit()
            else:
                dialogs.error(
                    'MXDC Already Running',
                    'An instance of MXDC is already running on the local network. Only one instance permitted.'
                )
                self.quit()

    def start_server(self, *args, **kwargs):
        self.service = server.MXDCService()
        logger.info(
            'Local MXDC instance {}@{} started {}'.format(
                self.service_data['user'], self.beamline.name, self.service_data['started']
            )
        )
        self.beamline.lims.open_session(self.beamline.name, settings.get_session())
        reactor.listenTCP(MXDC_PORT, pb.PBServerFactory(server.IPerspectiveMXDC(self.service)))

    def on_shutdown(self, *args):
        logger.info('Stopping ...')
        self.beamline.cleanup()
        clear_loggers()


def clear_loggers():
    # disconnect all log handlers first
    logger = logging.getLogger('')
    for h in logger.handlers:
        logger.removeHandler(h)


class MxDCApp(object):
    def __init__(self, dark=False):
        self.application = Application(dark=dark)

    def run(self):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.application.quit)
        if USE_TWISTED:
            reactor.registerGApplication(self.application)
            reactor.run()
        else:
            self.application.run(sys.argv)


