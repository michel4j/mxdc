'''
Created on Oct 27, 2010

@author: michel
'''

import os
import time
import gtk
import gtk.glade
#import gobject
#import pango
#import logging

from twisted.python.components import globalRegistry
from mxdc.widgets.resultlist import *
from mxdc.widgets.datalist import DataList
from bcm.utils.log import get_module_logger
from bcm.utils import lims_tools, runlists, json
from bcm.beamline.mx import IBeamline
from bcm.utils.misc import get_project_name
from bcm.utils.science import SPACE_GROUP_NAMES


#from mxdc.widgets.textviewer import TextViewer, GUIHandler
_logger = get_module_logger(__name__)

try:
    import gtkmozembed
    browser_engine = 'gecko'
except:
    import webkit
    browser_engine = 'webkit'

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


class ResultManager(gtk.Frame):
    __gsignals__ = {
        'active-sample': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
        'active-strategy': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
    }
    
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'result_manager.glade'), 
                                  'result_manager')

        self._create_widgets()
        self.active_sample = None
        self.active_strategy = None
        self._dataset_path = os.environ['HOME']

    def __getattr__(self, key):
        try:
            return super(ResultManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def do_active_sample(self, obj=None):
        pass
    
    def do_active_strategy(self, obj=None, data=None):
        pass
        

    def _create_widgets(self):
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.result_list = ResultList()
        self.dataset_list = DataList()
        self.result_list.listview.connect('row-activated', self.on_result_row_activated)
        self.screen_btn.connect('clicked', self.on_screen_action)
        self.process_btn.connect('clicked', self.on_process_action)
        
        # make buttons only active when something is selected
        data_selector = self.dataset_list.listview.get_selection()
        data_selector.connect('changed', self.on_datasets_selected)
        
    
        self.results_frame.add(self.result_list)
        self.datasets_frame.add(self.dataset_list)
        if browser_engine == 'gecko':
            self.browser = gtkmozembed.MozEmbed()
            self.html_window.add(self.browser)
        else:
            self.browser = webkit.WebView()
            self.browser_settings = webkit.WebSettings()
            self.browser_settings.set_property("enable-file-access-from-file-uris", True)
            self.browser_settings.set_property("default-font-size", 11)
            self.browser.set_settings(self.browser_settings)

            self.html_window.add(self.browser)
        self.update_sample_btn.connect('clicked', self.send_active_sample)
        self.update_strategy_btn.connect('clicked', self.send_active_strategy)
        self.add_dataset_btn.connect('clicked', self.on_load_dataset)
        self.add(self.result_manager)
        self.show_all()

    def add_result(self, data):
        return self.result_list.add_item(data)

    def add_dataset(self, data):
        return self.dataset_list.add_item(data)
    
    def update_result(self, iter, data):
        self.result_list.update_item(iter, data)

    def upload_results(self, results):
        lims_tools.upload_report(self.beamline, results)

    def add_results(self, item_list):
        for item in item_list:
            self.add_result(item)

    def add_datasets(self, item_list):
        for item in item_list:
            self.add_dataset(item)
    
    def clear_results(self):
        self.result_list.clear()

    def clear_datasets(self):
        self.dataset_list.clear()

    def send_active_sample(self, obj):
        if self.active_sample is not None:
            self.emit('active-sample', self.active_sample)

    def send_active_strategy(self, obj):
        if self.active_strategy is not None:
            self.emit('active-strategy', self.active_strategy)

    def on_load_dataset(self, obj):
        
        file_open = gtk.FileChooserDialog(title="Select Datasets to add",
                action=gtk.FILE_CHOOSER_ACTION_OPEN,
                buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        file_open.set_select_multiple(True)
        dataset_filter = gtk.FileFilter()
        dataset_filter.set_name("Dataset Summary")
        dataset_filter.add_pattern("*.SUMMARY")
        file_open.add_filter(dataset_filter)
        file_open.set_current_folder(self._dataset_path)

        if file_open.run() == gtk.RESPONSE_OK:
            filenames = file_open.get_filenames()
        else:
            filenames = []
        file_open.destroy()  
        if len(filenames) > 0:
            self._dataset_path = os.path.dirname(filenames[0])
                
        for filename in filenames:
            if filename is not None:
                try:
                    data = json.load(file(filename))
                    self.add_dataset(data)
                    _logger.info('Dataset "%s" loaded.' % data['name'])
                except:
                    _logger.error('Invalid file format. Unable to load dataset')
            
    def on_datasets_selected(self, selection):
        if selection.count_selected_rows() > 0:
            self.process_btn.set_sensitive(True)
            self.screen_btn.set_sensitive(True)
        else:
            self.process_btn.set_sensitive(True)
            self.screen_btn.set_sensitive(False)
                        
    def on_screen_action(self, obj):
        datasets = self.dataset_list.get_selected()
        for data in datasets:
            frame_list = runlists.frameset_to_list(data['frame_sets'])
            _first_frame = os.path.join(data['directory'],
                                        "%s_%03d.img" % (data['name'], frame_list[0]))
            _a_params = {'directory': os.path.join(data['directory'], '%s-scrn'% data['name']),
                         'info': {'anomalous': self.anom_check_btn.get_active(),
                                  'file_names': [_first_frame,]                                             
                                  },
                         'type': 'SCRN',
                         'crystal': data.get('crystal', {}),
                         'name': data['name'] }
        self.process_dataset(_a_params)
    
    def on_process_action(self, obj):
        datasets = self.dataset_list.get_selected()
        if not self.merge_check_btn.get_active() and not self.mad_check_btn.get_active():
            for data in datasets:
                frame_list = runlists.frameset_to_list(data['frame_sets'])
                _first_frame = os.path.join(data['directory'],
                                        "%s_%03d.img" % (data['name'], frame_list[0]))
                _a_params = {'directory': os.path.join(data['directory'], '%s-proc' % data['name']),
                             'info': {'anomalous': self.anom_check_btn.get_active(),
                                      'file_names': [_first_frame,]                                             
                                      },
                             'type': 'PROC',
                             'crystal': data.get('crystal', {}),
                             'name': data['name'] }
                self.process_dataset(_a_params)
        else:              
            file_names = []
            name_list = []
            for data in datasets:
                frame_list = runlists.frameset_to_list(data['frame_sets'])
                file_names.append(os.path.join(data['directory'],
                                            "%s_%03d.img" % (data['name'], frame_list[0])))
                name_list.append(data['name'])
            _prefix = os.path.commonprefix(name_list)
            if _prefix == '':
                _prefix = '_'.join(name_list)
            elif _prefix[-1] == '_':
                _prefix = _prefix[:-1]

            _a_params = {'directory': os.path.join(data['directory'], '%s-proc' % _prefix),
                         'info': {'mad': self.mad_check_btn.get_active(),
                                  'file_names': file_names,                                             
                                  },
                         'type': 'PROC',
                         'crystal': datasets[0].get('crystal', {}), # use crystal from first one
                         'name': datasets[0]['name']} # use name from first one only
            self.process_dataset(_a_params)
        
    def process_dataset(self, params):
        params.update(state=RESULT_STATE_WAITING)
        iter = self.add_result(params)
        if params.get('type', 'SCRN') == 'SCRN':
            cmd = 'screenDataset'
        else:
            cmd = 'processDataset'
        try:
            self.beamline.dpm.service.callRemote(cmd,
                                params['info'], 
                                params['directory'],
                                get_project_name(),
                                ).addCallbacks(self._result_ready, callbackArgs=[iter, params],
                                               errback=self._result_fail, errbackArgs=[iter])
        except:
            raise
            self._result_fail(None, iter)
        
    def _result_ready(self, results, iter, params):
        for index, data in enumerate(results):
            if index != 0:
                _a_params = params
                _a_params.update(name=data['result']['name'], state=RESULT_STATE_WAITING)
                res_iter = self.add_result(params)
            else:
                res_iter = iter
            cell_info = '%0.1f %0.1f %0.1f %0.1f %0.1f %0.1f' % (
                        data['result']['cell_a'],
                        data['result']['cell_b'],
                        data['result']['cell_c'],
                        data['result']['cell_alpha'],
                        data['result']['cell_beta'],
                        data['result']['cell_gamma']
                        )
            item = {'state': RESULT_STATE_READY,
                    'score': data['result']['score'],
                    'space_group': SPACE_GROUP_NAMES[data['result']['space_group_id']],
                    'unit_cell': cell_info,
                    'detail': data}
            self.update_result(res_iter, item)
        self.upload_results(results)

        
    def _result_fail(self, failure, iter):
        _logger.error("Unable to process data")
        if failure is not None:
            _logger.error(failure.getErrorMessage())
            failure.printBriefTraceback()
        item = {'state': RESULT_STATE_ERROR}
        self.update_result(iter, item)


    def on_result_row_activated(self, treeview, path, column):
        model = treeview.get_model()
        iter = model.get_iter(path)
        result_data = model.get_value(iter, RESULT_COLUMN_RESULT)
        sample_data = model.get_value(iter, RESULT_COLUMN_DATA)

        result = result_data.get('result', None)
        self.active_strategy = result_data.get('strategy', None)
        self.active_sample = sample_data
        
        if result in [None, '']:
            _logger.info('Results are not yet available')
            return
                
        if self.active_sample is not None and self.active_sample != {}:
            _crystal_string = "<b>Selected crystal: </b> %s [%s]" % (self.active_sample.get('name'),
                                           self.active_sample.get('port'))
            self.crystal_lbl.set_markup(_crystal_string)
            
        if result.get('url', None) in [None, '']:
            _logger.info('Results are not yet available')
            return
        
        # Active update buttons if data is available
        if self.active_sample is not None and self.active_sample != {}:
            self.update_sample_btn.set_sensitive(True)
        else:
            self.update_sample_btn.set_sensitive(False)
            
        if self.active_strategy is not None:
            self.update_strategy_btn.set_sensitive(True)
        else:
            self.update_strategy_btn.set_sensitive(False)

        
        filename =  os.path.join(result['url'], 'report', 'index.html')
        if os.path.exists(filename):
            uri = 'file://%s' % filename
            
            _logger.info('Loading results in %s' % uri)
            if browser_engine == 'webkit':
                gobject.idle_add(self.browser.load_uri, uri)
            else:
                gobject.idle_add(self.browser.load_url, uri)            
        else:
            _logger.warning('Formatted results are not available.')
                
if __name__ == "__main__":
    from twisted.internet import gtk2reactor
    gtk2reactor.install()
    from twisted.internet import reactor
    
    for k,v in os.environ.items():
        print '%s=%s' % (k, v)
    
    win = gtk.Window()
    win.connect("destroy", lambda x: reactor.stop())
    win.set_default_size(800,600)
    win.set_border_width(2)
    win.set_title("Sample Widget Demo")

    example = ResultManager()
    example.result_list.load_data(TEST_DATA)

    win.add(example)
    win.show_all()

    try:
        reactor.run()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()
        
