import gi

gi.require_version('Gtk', '3.0')
from mxdc import conf
from mxdc.conf import settings
from mxdc.beamlines.mx import IBeamline
from mxdc.engines.scripting import get_scripts
from mxdc.utils.log import get_module_logger
from mxdc.utils import gui
from mxdc.controllers import common, status
from mxdc.controllers import setup, scans, datasets
from mxdc.controllers import samples, analysis
from mxdc.controllers.settings import SettingsDialog
from mxdc.widgets import dialogs
from mxdc.widgets.splash import Splash
from twisted.python.components import globalRegistry
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, Gio, GLib
import os
from datetime import datetime

logger = get_module_logger(__name__)

_version_file = os.path.join(os.path.dirname(__file__), 'VERSION')
if os.path.exists(_version_file):
    VERSION = (file(_version_file).readline()).strip()
else:
    VERSION = "- Development -"

COPYRIGHT = "Copyright (c) 2006-{}, Canadian Light Source, Inc. All rights reserved.".format(datetime.now().year)




class AppWindow(Gtk.ApplicationWindow, gui.BuilderMixin):
    gui_roots = {
        'data/mxdc_main': [
            'auto_groups_pop', 'scans_ptable_pop', 'app_menu', 'header_bar',
            'mxdc_main',
        ]
    }

    def __init__(self, application=None, version=VERSION):
        super(AppWindow, self).__init__(name='MxDC', application=application)
        self.set_wmclass("MxDC", "MxDC")
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
        self.splash = Splash(version)
        self.splash.show_all()
        self.splash.set_keep_above(True)
        self.splash.set_modal(True)
        while Gtk.events_pending():
            Gtk.main_iteration()

        self.setup_gui()
        dialogs.MAIN_WINDOW = self

        self.first_load = True
        self.show_select_dialog = True
        self.show_run_dialog = True
        self.settings_active = False

        while Gtk.events_pending():
            Gtk.main_iteration()

    def add_menu_actions(self):
        self.quit_mnu.connect('activate', self.do_quit)
        self.about_mnu.connect('activate', self.do_about)
        self.preferences_mnu.connect('activate', self.do_settings)

    def build_gui(self):
        self.notifier = common.AppNotifier(self.notification_lbl, self.notification_revealer, self.notification_btn)

        self.analysis = analysis.AnalysisController(self)
        self.samples = samples.SamplesController(self)

        self.hutch_manager = setup.SetupController(self)
        self.status_panel = status.StatusPanel(self)
        self.datasets = datasets.DatasetsController(self)
        self.automation = datasets.AutomationController(self)
        self.scans = scans.ScanManager(self)

        self.app_mnu_btn.set_popup(self.app_menu)

        self.add_menu_actions()
        self.page_switcher.set_stack(self.main_stack)
        self.main_stack.connect('notify::visible-child', self.on_page_switched)
        self.dir_template_btn.connect('clicked', self.do_settings)
        self.set_titlebar(self.header_bar)
        icon = GdkPixbuf.Pixbuf.new_from_file(self.icon_file)
        self.set_icon(icon)

        GObject.timeout_add(1010, lambda: self.present())
        GObject.timeout_add(1000, lambda: self.splash.hide())

        self.add(self.mxdc_main)

        self.show_all()

    def run(self):
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.scripts = get_scripts()
        self.build_gui()

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
        name = 'Mx Data Collector (MxDC)'
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

    def on_analyse_request(self, obj, data):
        self.analyses.process_dataset(data)
        # self.analysis_box.props.needs_attention = True


MENU_XML = """
<?xml version="1.0" encoding="UTF-8"?>
<interface>
  <menu id="app-menu">
    <section>
      <item>
        <attribute name="action">app.preferences</attribute>
        <attribute name="label" translatable="yes">Preferences</attribute>
      </item>
    </section>
    <section>
      <item>
        <attribute name="action">app.about</attribute>
        <attribute name="label" translatable="yes">_About</attribute>
      </item>
      <item>
        <attribute name="action">app.quit</attribute>
        <attribute name="label" translatable="yes">_Quit</attribute>
        <attribute name="accel">&lt;Primary&gt;q</attribute>
    </item>
    </section>
  </menu>
</interface>
"""


class Application(Gtk.Application):
    def __init__(self, *args, **kwargs):
        super(Application, self).__init__(
            *args, application_id="ca.lightsource.mxdc",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
            **kwargs
        )
        self.window = None
        self.add_main_option("test", ord("t"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Command line test", None)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        action = Gio.SimpleAction.new("about", None)
        action.connect("activate", self.on_about)
        self.add_action(action)

        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self.on_quit)
        self.add_action(action)

        action = Gio.SimpleAction.new("preferences", None)
        action.connect("activate", self.on_preferences)
        self.add_action(action)

        builder = Gtk.Builder.new_from_string(MENU_XML, -1)
        self.set_app_menu(builder.get_object("app-menu"))

    def do_activate(self):
        # We only allow a single window and raise any existing ones
        if not self.window:
            # Windows are associated with the application
            # when the last one is closed the application shuts down
            self.window = AppWindow(application=self)

        self.window.present()

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()

        if options.contains("test"):
            # This is printed on the main instance
            print("Test argument recieved")

        self.activate()
        return 0

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
        about.set_version(self.version)
        about.set_copyright(COPYRIGHT)
        about.set_comments("Program for macromolecular crystallography data acquisition.")
        about.set_website("http://cmcf.lightsource.ca")
        about.set_authors(authors)
        logo = GdkPixbuf.Pixbuf.new_from_file(self.icon_file)
        about.set_logo(logo)
        about.present()

    def on_quit(self, action, param):
        self.quit()