import gtk, gobject
import gtk.glade
import sys, os
import logging
import pwd

from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from mxdc.widgets.collectmanager import CollectManager
from mxdc.widgets.scanmanager import ScanManager
from mxdc.widgets.hutchmanager import HutchManager
from mxdc.widgets.screeningmanager import ScreenManager
from mxdc.widgets.samplemanager import SampleManager
from mxdc.widgets.resultmanager import ResultManager
from mxdc.widgets.resultlist import RESULT_STATE_WAITING, RESULT_STATE_READY, RESULT_STATE_ERROR
from bcm.utils.log import get_module_logger, log_to_console
from mxdc.widgets.splash import Splash
from mxdc.widgets.statuspanel import StatusPanel
from mxdc.widgets import dialogs
from bcm.engine.scripting import get_scripts
from bcm.utils.misc import get_project_name
from mxdc.utils import clients

_logger = get_module_logger('mxdc')
SHARE_DIR = os.path.join(os.path.dirname(__file__), 'share')
VERSION = (file(os.path.join(os.path.dirname(__file__), 'VERSION')).readline()).strip()
COPYRIGHT = """
Copyright (c) 2006-2010, Canadian Light Source, Inc
All rights reserved.

This software is provided by the copyright holders and contributors "as is" and
any express or implied warranties, including, but not limited to, the implied
warranties of merchantability and fitness for a particular purpose are
disclaimed. In no event shall the Canadian Light Source be liable for any
direct, indirect, incidental, special, exemplary, or consequential damages
(including, but not limited to, procurement of substitute goods or services;
loss of use, data, or profits; or business interruption) however caused and
on any theory of liability, whether in contract, strict liability, or tort
(including negligence or otherwise) arising in any way out of the use of this
software, even if advised of the possibility of such damage.
"""

class AppWindow(gtk.Window):
    def __init__(self, version=VERSION):
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self._xml = gtk.glade.XML(os.path.join(SHARE_DIR, 'mxdc_main.glade'), 'mxdc_main')
        self.set_position(gtk.WIN_POS_CENTER)
        self.icon_file = os.path.join(SHARE_DIR, 'icon.png')
        self.set_title('MxDC - Mx Data Collector')
        self.version = version
        self.splash = Splash(version)
        self.splash.set_transient_for(self)
        self.splash.show_all()
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

        gobject.timeout_add(2000, lambda: self.splash.hide())         
        self.scan_manager = ScanManager()
        self.collect_manager = CollectManager()
        self.scan_manager.connect('create-run', self.on_create_run)       
        self.hutch_manager = HutchManager()
        self.sample_manager = SampleManager()
        self.result_manager = ResultManager()
        self.screen_manager = ScreenManager()
        self.status_panel = StatusPanel()
        self.dpm_client = clients.DPMClient()
        
        self.screen_manager.screen_runner.connect('analyse-request', self.on_analyse_request)
        self.sample_manager.connect('samples-changed', self.on_samples_changed)
        self.sample_manager.connect('active-sample', self.on_active_sample)
        self.result_manager.connect('active-sample', self.on_active_sample)
        self.result_manager.connect('active-strategy', self.on_active_strategy)
        self.scan_manager.connect('active-strategy', self.on_active_strategy)
        self.collect_manager.connect('new-datasets', self.on_new_datasets)
        self.screen_manager.connect('new-datasets', self.on_new_datasets)

        
        self.quit_cmd.connect('activate', lambda x: self._do_quit() )
        self.about_cmd.connect('activate', lambda x:  self._do_about() )
        
        notebook = gtk.Notebook()
        def _mk_lbl(txt):
            lbl = gtk.Label(txt)
            lbl.set_padding(6,0)
            return lbl
            
        notebook.append_page(self.hutch_manager, tab_label=_mk_lbl('Beamline Setup'))
        notebook.append_page(self.sample_manager, tab_label=_mk_lbl('Samples'))
        notebook.append_page(self.collect_manager, tab_label=_mk_lbl('Data Collection'))
        notebook.append_page(self.screen_manager, tab_label=_mk_lbl('Screening'))
        notebook.append_page(self.scan_manager, tab_label=_mk_lbl('Fluorescence Scans'))
        notebook.append_page(self.result_manager, tab_label=_mk_lbl('Results'))
        notebook.set_border_width(6)

        self.main_frame.add(notebook)
        self.mxdc_main.pack_start(self.status_panel, expand = False, fill = False)
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
        
    def _do_quit(self):
        self.hide()
        self.emit('destroy')
             
    def _do_about(self):
        authors = [
            "Michel Fodje (maintainer)",
            "Kathryn Janzen",
            "Kevin Anderson",
            ]
        about = gtk.AboutDialog()
        about.set_name("MX Data Collector")
        about.set_version(self.version)
        about.set_copyright(COPYRIGHT)
        about.set_comments("Program for macromolecular crystallography data acquisition.")
        about.set_website("http://cmcf.lightsource.ca")
        about.set_authors(authors)
        about.set_program_name('MxDC')
        logo = gtk.gdk.pixbuf_new_from_file(self.icon_file)
        about.set_logo(logo)
        
        about.connect('response', lambda x,y: about.destroy())
        about.connect('destroy', lambda x: about.destroy())
        about.set_transient_for(self)
        about.show()

    def on_create_run(self, obj=None, arg=None):
        run_data = self.scan_manager.get_run_data()
        self.collect_manager.add_run( run_data )
        header = 'New MAD Run Added'
        subhead = 'A new run for MAD data collection has been added to the "Data Collection" tab. '
        subhead += 'Remember to delete the runs you no longer need before proceeding.'
        dialogs.info(header, subhead)
        
    def on_samples_changed(self, obj, ctx):
        samples = ctx.get_loaded_samples()
        self.screen_manager.add_samples(samples)
        
    def on_active_sample(self, obj, data):
        self.collect_manager.update_active_data(sample=data)
        header = 'Active Sample Updated'
        subhead = 'The active sample has been updated to "%s (%s)", in the "Data Collection" tab. ' % (data['name'], data['port'])
        subhead += 'Please create a new run or update the run parameters to collect on it.'
        dialogs.info(header, subhead)

    def on_active_strategy(self, obj, data):
        self.collect_manager.update_active_data(strategy=data)
        header = 'Active Strategy Updated'
        subhead = 'The active strategy has been updated in the "Data Collection" tab. '
        subhead += 'Please create a new run or update the run parameters to use it.'
        dialogs.info(header, subhead)

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