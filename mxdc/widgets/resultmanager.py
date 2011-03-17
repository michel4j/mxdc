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
from bcm.utils.log import get_module_logger
from bcm.utils import lims_tools
from bcm.beamline.mx import IBeamline

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

    def do_active_sample(self, obj=None):
        pass
    
    def do_active_strategy(self, obj=None, data=None):
        pass
        
    def __getattr__(self, key):
        try:
            return super(ResultManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def _create_widgets(self):
        self.beamline = globalRegistry.lookup([], IBeamline)  
        self.result_list = ResultList()
        self.result_list.listview.connect('row-activated', self.on_result_row_activated)
    
        self.list_window.add(self.result_list)
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
        self.add(self.result_manager)
        self.show_all()

    def add_item(self, data):
        return self.result_list.add_item(data)
    
    def update_item(self, iter, data):
        self.result_list.update_item(iter, data)

    def upload_results(self, results):
        lims_tools.upload_report(self.beamline, results)

    def add_items(self, item_list):
        for item in item_list:
            self.add_item(item)
    
    def clear_results(self):
        self.result_list.clear()

    def send_active_sample(self, obj):
        if self.active_sample is not None:
            self.emit('active-sample', self.active_sample)

    def send_active_strategy(self, obj):
        if self.active_strategy is not None:
            self.emit('active-strategy', self.active_strategy)

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
        
        if self.active_sample is not None:
            _crystal_string = "<b>Selected crystal: </b> %s [%s]" % (self.active_sample.get('name'),
                                           self.active_sample.get('port'))
            self.crystal_lbl.set_markup(_crystal_string)
            
        if result.get('url', None) in [None, '']:
            _logger.info('Results are not yet available')
            return
        
        # Active update buttons if data is available
        if self.active_sample is not None:
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
        
