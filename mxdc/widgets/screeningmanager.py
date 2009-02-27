import sys
import os
import gtk
import gtk.glade
import gobject
from zope.component import globalSiteManager as gsm
from mxdc.widgets.samplelist import SampleList, TEST_DATA
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.ptzviewer import AxisViewer
from bcm.beamline.mx import IBeamline
from bcm.engine.scripting import get_scripts

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class ScreenManager(gtk.Frame):
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._create_widgets()
        
    def _create_widgets(self):
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'screening_widget.glade'), 
                                  'screening_widget')            
        self.screen_manager = self._xml.get_widget('screening_widget')
        self.sample_box = self._xml.get_widget('sample_box')
        self.video_book = self._xml.get_widget('video_book')
        self.sample_list = SampleList()
        self.sample_box.pack_start(self.sample_list, expand=True, fill=True)
        self.sample_list.load_data(TEST_DATA)

        self.beamline = gsm.getUtility(IBeamline, 'bcm.beamline')      

        # video        
        self.sample_viewer = SampleViewer()
        self.hutch_viewer = AxisViewer(self.beamline.registry['hutch_video'])
        self.video_book.append_page(self.sample_viewer, tab_label=gtk.Label('Sample Camera'))
        self.video_book.append_page(self.hutch_viewer, tab_label=gtk.Label('Hutch Camera'))
        self.video_book.connect('map', lambda x: self.video_book.set_current_page(0))       
        
        self.add(self.screen_manager)

        
        self.show_all()