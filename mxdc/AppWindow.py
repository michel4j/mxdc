import gi
import atexit

gi.require_version('Gtk', '3.0')
from mxdc.beamline.mx import IBeamline
from mxdc.utils import config

config.get_session()  # update the session configuration
from mxdc.engines.scripting import get_scripts
from mxdc.utils.log import get_module_logger
from mxdc.utils import gui
from mxdc.control import common, status
from mxdc.control import setup, scans, datasets
from mxdc.control import samples, analysis
from mxdc.widgets import dialogs
from mxdc.widgets.splash import Splash
from twisted.python.components import globalRegistry
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject
import os
from datetime import datetime

logger = get_module_logger(__name__)

SHARE_DIR = os.path.join(os.path.dirname(__file__), 'share')

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

    def __init__(self, version=VERSION):
        super(AppWindow, self).__init__(name='MxDC')
        self.set_wmclass("MxDC", "MxDC")
        self.set_position(Gtk.WindowPosition.CENTER)
        settings = self.get_settings()
        settings.props.gtk_enable_animations = True
        css = Gtk.CssProvider()
        with open(os.path.join(SHARE_DIR, 'styles.less'), 'r') as handle:
            css_data = handle.read()
            css.load_from_data(css_data)
        style = self.get_style_context()
        style.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.set_size_request(1290, 884)
        self.set_resizable(False)
        self.icon_file = os.path.join(SHARE_DIR, 'icon.png')

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

        while Gtk.events_pending():
            Gtk.main_iteration()

    def add_menu_actions(self):
        self.quit_mnu.connect('activate', lambda x: self.do_quit())
        self.about_mnu.connect('activate', lambda x: self.do_about())
        self.mount_mnu.connect('activate', lambda x: self.scripts['SetMountMode'].start())
        self.centering_mnu.connect('activate', lambda x: self.scripts['SetCenteringMode'].start())
        self.collect_mnu.connect('activate', lambda x: self.scripts['SetCollectMode'].start())
        self.beam_mnu.connect('activate', lambda x: self.scripts['SetBeamMode'].start())

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

    def do_quit(self):
        self.hide()
        self.emit('destroy')

    def do_about(self):
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

    # def on_create_run(self, obj=None, arg=None):
    #     run_data = self.scan_manager.get_run_data()
    #     #self.collect_manager.add_run(run_data)
    #     if self.show_run_dialog:
    #         header = 'New MAD Run Added'
    #         subhead = 'A new run for MAD data collection has been added to the "Data Collection" tab. '
    #         subhead += 'Remember to delete the runs you no longer need before proceeding.'
    #         chkbtn = Gtk.CheckButton('Do not show this dialog again.')
    #
    #         def _chk_cb(obj):
    #             self.show_run_dialog = (not obj.get_active())
    #
    #         chkbtn.connect('toggled', _chk_cb)
    #         chkbtn.set_property('can-focus', False)
    #         dialogs.info(header, subhead, extra_widgets=[chkbtn])

    # def on_samples_changed(self, obj, ctx):
    #     samples = ctx.get_loaded_samples()
    #     #self.screen_manager.add_samples(samples)
    #     # only change tabs if samples are changed manually
    #     if not self.first_load:
    #         # self.screen_box.props.needs_attention = True
    #         pass
    #     else:
    #         self.first_load = False

    # def on_active_sample(self, obj, data):
    #     self.sample_microscope.update_active_sample(data)
    #     #self.collect_manager.update_active_sample(data)
    #     self.scan_manager.update_active_sample(data)
    #
    # def on_sample_selected(self, obj, data):
    #     #self.collect_manager.update_selected(sample=data)
    #     self.sample_microscope.update_selected(sample=data)
    #     try:
    #         logger.info('The selected sample has been updated to "%s (%s)"' % (data['name'], data['port']))
    #         # self.datasets_box.props.needs_attention = True
    #     except KeyError:
    #         logger.info('The crystal cannot be selected')

    # def on_beam_change(self, obj, beam_available):
    #     if not beam_available:
    #         # self.setup_box.props.needs_attention = True
    #         pass
    #
    # def on_update_strategy(self, obj, data):
    #     #self.collect_manager.update_data(strategy=data)
    #     # self.datasets_box.props.needs_attention = True
    #     pass
    #
    # def on_new_datasets(self, obj, datasets):
    #     # Fech full crystal information from sample database and update the dataset information
    #     database = self.sample_microscope.get_database()
    #     if database is not None:
    #         for dataset in datasets:
    #             if dataset.get('crystal_id') is not None:
    #                 crystal = database['crystals'].get(str(dataset['crystal_id']))
    #                 if crystal is None:
    #                     continue
    #                 if dataset.get('experiment_id') is not None:
    #                     group = database['experiments'].get(str(dataset['experiment_id']))
    #                     if group is not None:
    #                         crystal.update(group_name=group.get('name', dataset['experiment_id']))
    #                 dataset.update(crystal=crystal)
    #     self.result_manager.add_datasets(datasets)


    def on_page_switched(self, stack, params):
        stack.child_set(stack.props.visible_child, needs_attention=False)

    def on_analyse_request(self, obj, data):
        self.analyses.process_dataset(data)
        # self.analysis_box.props.needs_attention = True
