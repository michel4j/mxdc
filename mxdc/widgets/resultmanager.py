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
from mxdc.widgets.resultlist import ResultList, TEST_DATA
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
        if browser_engine == 'gecko':
            self.browser = gtkmozembed.MozEmbed()
        else:
            self.browser = webkit.WebView()
            self.browser.load_url = self.browser.load_uri
            
        self.list_window.add(self.result_list)
        self.html_window.add(self.browser)      
        #self.browser.load_url('http://www.google.com')
        self.add(self.result_manager)
        self.result_list.load_data(TEST_DATA)
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
        
