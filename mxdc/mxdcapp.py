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
from mxdc.widgets.AppWindow import AppWindow
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


class MXDCApp(object):
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


        self.broadcast_service()
        self.main_window.connect('destroy', self.do_quit)
        self.main_window.run()

    def broadcast_service(self):
        self.remote_mxdc = None
        self.service_type = '_mxdc_{}._tcp'.format(identifier_slug(self.beamline.name))
        self.service_data = {
            'user': get_project_name(),
            'started': time.asctime(time.localtime()),
            'beamline': self.beamline.name
        }

        try:
            self.provider = mdns.Provider('MXDC Client ({})'.format(
                self.beamline.name), self.service_type, MXDC_PORT, self.service_data, unique=True
            )
        except mdns.mDNSError:
            self.remote_mxdc = clients.MxDCClientFactory(self.service_type)()
            self.remote_mxdc.connect('active', self.service_found)
        else:
            self.start_server()

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
                    self.remote_mxdc.send_message('Hello earth! All your bases are belong to us.')
                    d = self.remote_mxdc.shutdown()
                    d.addCallback(self.start_server)
                else:
                    self.do_quit()
            else:
                dialogs.error(
                    'MXDC Already Running',
                    'An instance of MXDC is already running on the local network. Only one instance permitted.'
                )
                self.do_quit()

    def start_server(self, *args, **kwargs):
        self.service = server.MXDCService(clients.messenger)
        logger.info(
            'Local MXDC instance {}@{} started {}'.format(
                self.service_data['user'], self.beamline.name, self.service_data['started']
            )
        )
        self.session_active = True
        self.beamline.lims.open_session(self.beamline.name, settings.get_session())
        reactor.listenTCP(MXDC_PORT, pb.PBServerFactory(server.IPerspectiveMXDC(self.service)))

    def do_quit(self, obj=None):
        if self.session_active:
            logger.info('Closing MxLIVE Session...')
            self.beamline.lims.close_session(self.beamline.name, settings.get_session())
        logger.info('Stopping ...')
        if self.remote_mxdc:
            self.remote_mxdc.leave()
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


