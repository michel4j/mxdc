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

#from twisted.python.components import globalRegistry
from mxdc.widgets.resultlist import *
#from bcm.beamline.mx import IBeamline
#from mxdc.widgets.textviewer import TextViewer, GUIHandler

try:
    import webkit
    browser_engine = 'webkit'
except:
    import gtkmozembed
    browser_engine = 'gecko'

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


class ResultManager(gtk.Frame):
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'result_manager.glade'), 
                                  'result_manager')

        self._create_widgets()

        
    def __getattr__(self, key):
        try:
            return super(ResultManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def _create_widgets(self):      
        self.result_list = ResultList()
        self.result_list.listview.connect('row-activated', self.on_result_row_activated)
    
        self.list_window.add(self.result_list)
        if browser_engine == 'gecko':
            self.browser = gtkmozembed.MozEmbed()
            self.html_window.add_with_viewport(self.browser)      
        else:
            self.browser = webkit.WebView()
            self.browser_settings = webkit.WebSettings()
            self.browser_settings.set_property("enable-file-access-from-file-uris", True)
            self.browser.set_settings(self.browser_settings)
            
            #self.browser.load_url = self.browser.load_uri
            self.html_window.add(self.browser)
              
        self.browser.load_uri('file:///users/cmcfadmin/SIM-20101029/B6/scrn/report/index.html')
        self.add(self.result_manager)
        self.show_all()

    def add_item(self, data):
        return self.result_list.add_item(data)
    
    def update_item(self, iter, data):
        self.result_list.update_item(iter, data)

    def add_items(self, item_list):
        for item in item_list:
            self.add_item(item)
    
    def clear_results(self):
        self.result_list.clear()

    def on_result_row_activated(self, treeview, path, column):
        model = treeview.get_model()
        iter = model.get_iter(path)
        data = model.get_value(iter, RESULT_COLUMN_DETAIL)
        uri = 'file://%s/report/index.html' % data.get('url','')
        print uri
        #self.browser.open(uri)
        self.browser.load_uri('file:///users/cmcfadmin/SIM-20101029/B14/scrn/report/index.html')
        
        print uri
        
if __name__ == "__main__":
    from twisted.internet import gtk2reactor
    gtk2reactor.install()
    from twisted.internet import reactor

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
        
