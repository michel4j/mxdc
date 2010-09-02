import traceback
import gtk, gobject
import sys, os
import logging
from twisted.python.components import globalRegistry
from bcm.beamline.mx import IBeamline
from bcm.engine.scripting import get_scripts
from bcm.utils.log import get_module_logger

from mxdc.widgets.predictor import Predictor
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.ptzviewer import AxisViewer
from mxdc.widgets.samplepicker import SamplePicker
from mxdc.widgets.simplevideo import SimpleVideo
from mxdc.widgets.dewarloader import DewarLoader
from mxdc.widgets.misc import *

_logger = get_module_logger('mxdc.samplemanager')

class SampleManager(gtk.Frame):
    __gsignals__ = {
        'samples-changed': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,))
    }    
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'sample_widget.glade'), 
                                  'sample_widget')
        self._create_widgets()
    
    def __getattr__(self, key):
        try:
            return super(SampleManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def _create_widgets(self):
        self.beamline = globalRegistry.lookup([], IBeamline)
                
        # video, automounter, cryojet, dewar loader 
        self.sample_viewer = SampleViewer()
        self.hutch_viewer = AxisViewer(self.beamline.hutch_video)
        self.dewar_loader = DewarLoader()
        self.cryo_controller = CryojetWidget(self.beamline.cryojet)
        self.sample_picker = SamplePicker(self.beamline.automounter)
        
        self.video_ntbk.append_page(self.sample_viewer, tab_label=gtk.Label('  Sample '))
        self.video_ntbk.append_page(self.hutch_viewer, tab_label=gtk.Label('  Hutch '))
        self.video_ntbk.connect('realize', lambda x: self.video_ntbk.set_current_page(0))
        self.cryo_ntbk.append_page(self.cryo_controller, tab_label=gtk.Label('  Cryojet Stream  '))
        
        self.robot_ntbk.append_page(self.sample_picker, tab_label=gtk.Label('  Automounter  '))
        self.dewar_loader.set_border_width(3)     
        self.loader_frame.add(self.dewar_loader)
        self.add(self.sample_widget)
        self.dewar_loader.connect('samples-changed', self.on_samples_changed)
        
    def on_samples_changed(self, obj):
        self.emit('samples-changed', self.dewar_loader)
        
        
        
                        