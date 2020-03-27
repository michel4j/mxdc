import logging
import os
import signal
import sys
import time
import warnings
from datetime import datetime

import gi

warnings.simplefilter("ignore")
gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, Gio, GLib
from twisted.internet import gtk3reactor

gtk3reactor.install()

from mxdc import conf
from mxdc.conf import settings
from mxdc.services import server
from mxdc.utils import mdns
from mxdc.utils.log import get_module_logger

from mxdc.widgets.AppWindow import AppWindow
from mxdc.widgets import dialogs
from mxdc.controllers.settings import SettingsDialog
from mxdc.controllers.browser import Browser
from mxdc.utils import excepthook, misc
from mxdc.beamlines import build_beamline
from mxdc.services import clients
from twisted.internet import reactor
from twisted.spread import pb

USE_TWISTED = True
MXDC_PORT = misc.get_free_tcp_port()  # 9898
VERSION = "2020.02"
COPYRIGHT = "Copyright (c) 2006-{}, Canadian Light Source, Inc. All rights reserved.".format(datetime.now().year)

logger = get_module_logger(__name__)


class Application(Gtk.Application):
    def __init__(self, **kwargs):
        super(Application, self).__init__(application_id="org.mxdc", **kwargs)
        self.window = None
        self.settings_active = False
        self.resource_data = GLib.Bytes.new(misc.load_binary_data(os.path.join(conf.SHARE_DIR, 'mxdc.gresource')))
        self.resources = Gio.Resource.new_from_data(self.resource_data)
        Gio.resources_register(self.resources)
        self.connect('shutdown', self.on_shutdown)

    def do_startup(self, *args):
        Gtk.Application.do_startup(self, *args)
        action = Gio.SimpleAction.new("about", None)
        action.connect("activate", self.on_about)
        self.add_action(action)

        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self.on_quit)
        self.add_action(action)

        action = Gio.SimpleAction.new("preferences", None)
        action.connect("activate", self.on_preferences)
        self.add_action(action)

        action = Gio.SimpleAction.new("help", None)
        action.connect("activate", self.on_help)
        self.add_action(action)

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
            # Windows are associated with the application
            self.window = AppWindow(application=self, title='MxDC')
            self.window.connect('destroy', self.on_quit)
            self.window.setup()

        self.window.present()
        if settings.show_release_notes():
            Browser(self.window)


    def on_about(self, action, param):
        authors = [
            "Michel Fodje",
            "Kathryn Janzen",
            "Kevin Anderson",
            "Cuylar Conly"
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
    def __init__(self):
        self.application = Application()

    def run(self):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.application.quit)
        if USE_TWISTED:
            reactor.registerGApplication(self.application)
            reactor.run()
        else:
            self.application.run(sys.argv)
