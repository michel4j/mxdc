import gi

gi.require_version('Gtk', '3.0')
from mxdc import conf
from mxdc.conf import settings
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
from mxdc.widgets.splash import Splash
from twisted.python.components import globalRegistry
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, Gio, GLib
import os
from datetime import datetime

logger = get_module_logger(__name__)

_version_file = os.path.join(os.path.dirname(__file__), 'VERSION')
VERSION = "2017-10"

COPYRIGHT = "Copyright (c) 2006-{}, Canadian Light Source, Inc. All rights reserved.".format(datetime.now().year)



class AppWindow(Gtk.ApplicationWindow, gui.BuilderMixin):
    gui_roots = {
        'data/mxdc_hutch': [
             'auto_groups_pop', 'scans_ptable_pop', 'header_bar', 'mxdc_main',
        ]
    }

    def __init__(self, application=None, version=VERSION):
        super(AppWindow, self).__init__(name='MxDC', application=application)
        self.set_wmclass("MxDC HutchViewer", "MxDC HutchViewer")
        self.set_position(Gtk.WindowPosition.CENTER)
        app_settings = self.get_settings()
        app_settings.props.gtk_enable_animations = True
        css = Gtk.CssProvider()
        with open(os.path.join(conf.SHARE_DIR, 'styles.less'), 'r') as handle:
            css_data = handle.read()
            css.load_from_data(css_data)
        style = self.get_style_context()
        style.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.set_size_request(1290, 884)
        self.set_resizable(False)
        self.icon_file = os.path.join(conf.SHARE_DIR, 'icon.png')

        self.version = version
        self.setup_gui()
        dialogs.MAIN_WINDOW = self

        self.first_load = True
        self.show_select_dialog = True
        self.show_run_dialog = True
        self.settings_active = False

        while Gtk.events_pending():
            Gtk.main_iteration()

    def build_gui(self):
        self.notifier = common.AppNotifier(self.notification_lbl, self.notification_revealer, self.notification_btn)
        self.samples = samples.HutchSamplesController(self)

        self.hutch_manager = setup.SetupController(self)
        self.status_panel = status.StatusPanel(self)

        # Chat
        self.chat = chat.ChatController(self)

        self.page_switcher.set_stack(self.main_stack)
        for stack in [self.main_stack, self.setup_status_stack, self.samples_stack]:
            stack.connect('notify::visible-child', self.on_page_switched)
        self.set_titlebar(self.header_bar)
        icon = GdkPixbuf.Pixbuf.new_from_file(self.icon_file)
        self.set_icon(icon)

        self.image_viewer = ImageViewer()
        self.datasets_viewer_box.add(self.image_viewer)
        self.image_viewer.open_btn.set_sensitive(False)
        self.beamline.detector.connect('new-image', self.load_detector_image)
        GObject.timeout_add(1010, lambda: self.present())

        self.add(self.mxdc_main)

        self.show_all()

    def run(self):
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.scripts = get_scripts()
        self.build_gui()

    def load_detector_image(self, obj, file_path):
        self.image_viewer.open_image(file_path)


    def do_quit(self, *args):
        self.hide()
        self.emit('destroy')

    def do_about(self, *args):
        authors = [
            "Michel Fodje",
            "Kathryn Janzen",
            "Kevin Anderson",
            "Cuylar Conly"
        ]
        about = Gtk.AboutDialog()
        about.set_transient_for(self)
        name = 'MxDC Hutch Viewer'
        try:
            about.set_program_name(name)
        except:
            about.set_name(name)
        about.set_version(self.version)
        about.set_copyright(COPYRIGHT)
        about.set_comments("Program for macromolecular crystallography data acquisition.")
        about.set_website("http://cmcf.lightsource.ca")
        about.set_authors(authors)
        logo = GdkPixbuf.Pixbuf.new_from_file(self.icon_file)
        about.set_logo(logo)

        about.connect('response', lambda x, y: x.destroy())
        about.connect('destroy', lambda x: x.destroy())
        about.show()

    def do_settings(self, *args):
        if not self.settings_active:
            self.settings_active = True
            dialog = SettingsDialog(self)
            dialog.run()
            self.settings_active = False

    def on_page_switched(self, stack, params):
        stack.child_set(stack.props.visible_child, needs_attention=False)



