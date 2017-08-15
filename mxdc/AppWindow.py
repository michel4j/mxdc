from mxdc.utils import config
config.get_session() # update the session configuration

from bcm.engine.scripting import get_scripts
from bcm.utils.log import get_module_logger
from mxdc.utils.gui import GUIFile
from mxdc.widgets import dialogs
from mxdc.widgets.collectmanager import CollectManager
from mxdc.widgets.hutchmanager import HutchManager
from mxdc.widgets.resultmanager import ResultManager
from mxdc.widgets.samplemanager import SampleManager
from mxdc.widgets.scanmanager import ScanManager
from mxdc.widgets.screeningmanager import ScreenManager
from mxdc.widgets.splash import Splash
from mxdc.widgets.statuspanel import StatusPanel
import gobject
import gtk
import os

_logger = get_module_logger('mxdc')
SHARE_DIR = os.path.join(os.path.dirname(__file__), 'share')

_version_file = os.path.join(os.path.dirname(__file__), 'VERSION')
if os.path.exists(_version_file):
    VERSION = (file(_version_file).readline()).strip()
else:
    VERSION = '- Development -'

COPYRIGHT = """
Copyright (c) 2006-2010, Canadian Light Source, Inc
All rights reserved.
"""
    
class AppWindow(gtk.Window):
    def __init__(self, version=VERSION):
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self._xml = GUIFile(os.path.join(SHARE_DIR, 'mxdc_main'), 'mxdc_main')
        self.set_position(gtk.WIN_POS_CENTER)
        self.icon_file = os.path.join(SHARE_DIR, 'icon.png')
        self.set_title('MxDC - Mx Data Collector')
        self.version = version
        self.splash = Splash(version)
        dialogs.MAIN_WINDOW = self
        self.splash.show_all()
        #self.splash.set_transient_for(self)
        self.splash.set_keep_above(True)
        self.splash.set_modal(True)
        
        #prepare pixbufs for tab status icons
        self._info_img = gtk.gdk.pixbuf_new_from_file(
                            os.path.join(os.path.dirname(__file__), 'widgets','data','tiny-info.png'))
        self._warn_img = gtk.gdk.pixbuf_new_from_file(
                            os.path.join(os.path.dirname(__file__), 'widgets','data','tiny-warn.png'))

        self._first_load = True
        self._show_select_dialog = True
        self._show_run_dialog = True

        while gtk.events_pending():
            gtk.main_iteration()

    def __getattr__(self, key):
        try:
            return super(AppWindow).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
        
    def run(self):
        icon = gtk.gdk.pixbuf_new_from_file(self.icon_file)
        self.set_icon(icon)
        #self.set_resizable(False)

        self.scan_manager = ScanManager()
        self.collect_manager = CollectManager()
        self.scan_manager.connect('create-run', self.on_create_run)       
        self.hutch_manager = HutchManager()
        self.sample_manager = SampleManager()
        self.result_manager = ResultManager()
        self.screen_manager = ScreenManager()
        self.status_panel = StatusPanel()
        
        self.screen_manager.screen_runner.connect('analyse-request', self.on_analyse_request)
        self.sample_manager.connect('samples-changed', self.on_samples_changed)
        self.sample_manager.connect('sample-selected', self.on_sample_selected)
        self.sample_manager.connect('active-sample', self.on_active_sample)
        self.result_manager.connect('sample-selected', self.on_sample_selected)
        self.result_manager.connect('update-strategy', self.on_update_strategy)
        self.scan_manager.connect('update-strategy', self.on_update_strategy)
        self.collect_manager.connect('new-datasets', self.on_new_datasets)
        self.screen_manager.connect('new-datasets', self.on_new_datasets)

        self.hutch_manager.connect('beam-change', self.on_beam_change)
        
        self.quit_cmd.connect('activate', lambda x: self._do_quit() )
        self.about_cmd.connect('activate', lambda x:  self._do_about() )
        
        notebook = gtk.Notebook()
        
        def _mk_lbl(txt):
            aln = gtk.Alignment(0.5,0.5,0,0)
            aln.set_padding(0,0,6,6)
            box = gtk.HBox(False,2)
            aln.raw_text = txt
            aln.label = gtk.Label(txt)
            aln.label.set_use_markup(True)
            box.pack_end(aln.label, expand=False, fill=False)
            aln.image = gtk.Image()
            box.pack_start(aln.image, expand=False, fill=False)
            aln.add(box)
            aln.show_all()
            return aln
            
        notebook.append_page(self.hutch_manager, tab_label=_mk_lbl('Beamline Setup'))
        notebook.append_page(self.sample_manager, tab_label=_mk_lbl('Samples'))
        notebook.append_page(self.collect_manager, tab_label=_mk_lbl('Data Collection'))
        notebook.append_page(self.screen_manager, tab_label=_mk_lbl('Screening'))
        notebook.append_page(self.scan_manager, tab_label=_mk_lbl('Fluorescence Scans'))
        notebook.append_page(self.result_manager, tab_label=_mk_lbl('Processing Results'))
        notebook.set_border_width(3)
        self.notebook = notebook
        self.notebook.connect('switch-page', self.on_page_switch)

        self.main_frame.add(notebook)
        self.mxdc_main.pack_end(self.status_panel, expand = False, fill = False)
        self.add(self.mxdc_main)
        self.scripts = get_scripts()
        # register menu events
        self.mounting_mnu.connect('activate', self.hutch_manager.on_mounting)
        self.centering_mnu.connect('activate', self.hutch_manager.on_centering)
        self.collect_mnu.connect('activate', self.hutch_manager.on_collection)
        self.beam_mnu.connect('activate', self.hutch_manager.on_beam_mode)
        self.open_shutter_mnu.connect('activate', self.hutch_manager.on_open_shutter)
        self.close_shutter_mnu.connect('activate', self.hutch_manager.on_close_shutter)
        
        self.show_all()
        self.ready()

    def ready(self):
        self.splash.hide()
        self.present()
        
    def _do_quit(self):
        self.hide()
        self.emit('destroy')
             
    def _do_about(self):
        authors = [
            "Michel Fodje (maintainer)",
            "Kathryn Janzen",
            "Kevin Anderson",
            "Cuylar Conly"
            ]
        about = gtk.AboutDialog()
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
        logo = gtk.gdk.pixbuf_new_from_file(self.icon_file)
        about.set_logo(logo)
        
        about.connect('response', lambda x,y: x.destroy())
        about.connect('destroy', lambda x: x.destroy())
        #about.set_transient_for(self)
        about.show()

    def on_create_run(self, obj=None, arg=None):
        run_data = self.scan_manager.get_run_data()
        self.collect_manager.add_run( run_data )
        if self._show_run_dialog:
            header = 'New MAD Run Added'
            subhead = 'A new run for MAD data collection has been added to the "Data Collection" tab. '
            subhead += 'Remember to delete the runs you no longer need before proceeding.'
            chkbtn = gtk.CheckButton('Do not show this dialog again.')
            def _chk_cb(obj):
                self._show_run_dialog = (not obj.get_active())
            chkbtn.connect('toggled', _chk_cb)
            chkbtn.set_property('can-focus', False)
            dialogs.info(header, subhead) #dialogs.info(header, subhead, extra_widgets=[chkbtn])
        
    def on_samples_changed(self, obj, ctx):
        samples = ctx.get_loaded_samples()
        self.screen_manager.add_samples(samples)
        # only change tabs if samples are changed manually
        if not self._first_load:
            tab_lbl = self.notebook.get_tab_label(self.screen_manager)
            tab_lbl.image.set_from_pixbuf(self._info_img)
            tab_lbl.label.set_markup("<b>%s</b>" % tab_lbl.raw_text)
        else:
            self._first_load = False
        
    def on_active_sample(self, obj, data):
        self.sample_manager.update_active_sample(data)
        self.collect_manager.update_active_sample(data)
        self.scan_manager.update_active_sample(data)

    def on_sample_selected(self, obj, data):
        self.collect_manager.update_selected(sample=data)
        self.sample_manager.update_selected(sample=data)
        try:
            _logger.info('The selected sample has been updated to "%s (%s)"' % (data['name'], data['port']))
        except KeyError:
            _logger.info('The crystal cannot be selected')
        tab_lbl = self.notebook.get_tab_label(self.collect_manager)
        tab_lbl.image.set_from_pixbuf(self._info_img)
        tab_lbl.label.set_markup("<b>%s</b>" % tab_lbl.raw_text)
        
#        if self._show_select_dialog:
#            header = 'Selected Crystal Updated'
#            try:
#                subhead = 'The selected crystal has been updated to "%s (%s)" in ' % (data['name'], data['port'])
#                subhead += 'the Data Collection tab.'
#            except KeyError:
#                subhead = 'The crystal cannot be selected.'
#            chkbtn = gtk.CheckButton('Do not show this dialog again.')
#            def _chk_cb(obj):
#                self._show_select_dialog = (not obj.get_active())
#            chkbtn.connect('toggled', _chk_cb)
#            chkbtn.set_property('can-focus', False)
#            dialogs.info(header, subhead, extra_widgets=[chkbtn])

    def on_beam_change(self, obj, beam_available):
        # Do not show icon if current page is already hutch tab
        if self.notebook.get_current_page() != self.notebook.page_num(self.hutch_manager):
            tab_lbl = self.notebook.get_tab_label(self.hutch_manager)
            if beam_available:
                tab_lbl.image.set_from_pixbuf(None)
                tab_lbl.label.set_markup(tab_lbl.raw_text)
            else:
                tab_lbl.image.set_from_pixbuf(self._warn_img)
                tab_lbl.label.set_markup("<b>%s</b>" % tab_lbl.raw_text)
    
    def on_page_switch(self, obj, pg, pgn):
        wdg = self.notebook.get_nth_page(pgn)
        tab_lbl = self.notebook.get_tab_label(wdg)
        tab_lbl.image.set_from_pixbuf(None)
        tab_lbl.label.set_markup(tab_lbl.raw_text)
        
    def on_update_strategy(self, obj, data):
        self.collect_manager.update_data(strategy=data)
        _logger.info('The active strategy has been updated in the "Data Collection" tab.')

    def on_new_datasets(self, obj, datasets):
        # Fech full crystal information from sample database and update the dataset information
        database =  self.sample_manager.get_database()
        if database is not None:
            for dataset in datasets:
                if dataset.get('crystal_id') is not None:
                    crystal = database['crystals'].get(str(dataset['crystal_id']))
                    if crystal is None:
                        continue
                    if dataset.get('experiment_id') is not None:
                        group = database['experiments'].get(str(dataset['experiment_id']))
                        if group is not None:
                            crystal.update(group_name=group.get('name', dataset['experiment_id']))
                    dataset.update(crystal=crystal)
        self.result_manager.add_datasets(datasets)
        
    def on_analyse_request(self, obj, data):
        self.result_manager.process_dataset(data)
        tab_lbl = self.notebook.get_tab_label(self.result_manager)
        tab_lbl.image.set_from_pixbuf(self._info_img)
        tab_lbl.label.set_markup("<b>%s</b>" % tab_lbl.raw_text)
        
