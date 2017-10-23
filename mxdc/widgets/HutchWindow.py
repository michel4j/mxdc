import gi

gi.require_version('Gtk', '3.0')
from mxdc import conf
from mxdc.beamlines.mx import IBeamline
from mxdc.engines.scripting import get_scripts
from mxdc.utils.log import get_module_logger
from mxdc.utils import gui
from mxdc.controllers import common, status, chat
from mxdc.controllers import setup, scans, datasets
from mxdc.controllers import samples, analysis
from mxdc.controllers.settings import SettingsDialog
from mxdc.widgets import dialogs
from mxdc.widgets.imageviewer import ImageViewer
from twisted.python.components import globalRegistry
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject
import os
from datetime import datetime

logger = get_module_logger(__name__)

_version_file = os.path.join(os.path.dirname(__file__), 'VERSION')

VERSION = "2017.10"
COPYRIGHT = "Copyright (c) 2006-{}, Canadian Light Source, Inc. All rights reserved.".format(datetime.now().year)


class AppBuilder(gui.Builder):
    gui_roots = {
        'data/mxdc_hutch': [
           'header_bar', 'mxdc_main',
        ]
    }

    def __init__(self):
        super(AppBuilder, self).__init__()
        self.notifier = common.AppNotifier(
            self.notification_lbl,
            self.notification_revealer,
            self.notification_btn
        )

        self.page_switcher.set_stack(self.main_stack)
        for stack in [self.main_stack, self.setup_status_stack]:
            stack.connect('notify::visible-child', self.on_page_switched)

    def on_page_switched(self, stack, params):
        stack.child_set(stack.props.visible_child, needs_attention=False)


class AppWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super(AppWindow, self).__init__(*args, **kwargs)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_wmclass('MxDC Hutch Viewer', 'MxDC Hutch Viewer')
        app_settings = self.get_settings()
        app_settings.props.gtk_enable_animations = True
        css = Gtk.CssProvider()
        with open(os.path.join(conf.SHARE_DIR, 'styles.less'), 'r') as handle:
            css_data = handle.read()
            css.load_from_data(css_data)
        style = self.get_style_context()
        style.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.builder = AppBuilder()
        self.set_size_request(1290, 884)
        self.set_resizable(False)
        self.icon_file = os.path.join(conf.SHARE_DIR, 'icon.png')

        dialogs.MAIN_WINDOW = self
        self.settings_active = False

    def setup(self):
        self.samples = samples.HutchSamplesController(self.builder)
        self.hutch_manager = setup.SetupController(self.builder)
        self.status_panel = status.StatusPanel(self.builder)


        # Chat
        self.chat = chat.ChatController(self.builder)

        self.set_titlebar(self.builder.header_bar)
        icon = GdkPixbuf.Pixbuf.new_from_file(self.icon_file)
        self.set_icon(icon)
        self.add(self.builder.mxdc_main)
        self.show_all()



