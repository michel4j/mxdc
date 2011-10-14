import traceback
import gtk, gobject
import sys, os

from twisted.python.components import globalRegistry
from bcm.beamline.mx import IBeamline
from bcm.engine.scripting import get_scripts
from bcm.utils.log import get_module_logger
from bcm.utils.misc import get_project_name
from bcm.utils import lims_tools

from mxdc.widgets.predictor import Predictor
from mxdc.widgets.sampleviewer import SampleViewer, HCViewer
from mxdc.widgets.ptzviewer import AxisViewer
from mxdc.widgets.samplepicker import SamplePicker
from mxdc.widgets.simplevideo import SimpleVideo
from mxdc.widgets.sampleloader import DewarLoader, STATUS_NOT_LOADED, STATUS_LOADED
from mxdc.widgets import dialogs
from mxdc.widgets.misc import *

_logger = get_module_logger('mxdc.samplemanager')

class SampleManager(gtk.Frame):
    __gsignals__ = {
        'samples-changed': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        'active-sample': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
        'sample-selected': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
    }    
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)       
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'sample_widget.glade'), 
                                  'sample_widget')
        self._create_widgets()
        self.changed_hc = False
    
    def __getattr__(self, key):
        try:
            return super(SampleManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def do_samples_changed(self, data):
        pass

    def do_sample_selected(self, data):
        pass
    
    def do_active_sample(self, data):
        pass
    
    def _create_widgets(self):
        self.beamline = globalRegistry.lookup([], IBeamline)
               
        # video, automounter, cryojet, dewar loader 
        self.sample_viewer = SampleViewer()
        self.hc_viewer = HCViewer()
        self.humidity_controller = HCWidget(self.beamline.humidity_control)
        self.hutch_viewer = AxisViewer(self.beamline.hutch_video)
        self.dewar_loader = DewarLoader()
        self.cryo_controller = CryojetWidget(self.beamline.cryojet)
        self.sample_picker = SamplePicker()
        
        def _mk_lbl(txt):
            lbl = gtk.Label(txt)
            lbl.set_padding(6,0)
            return lbl
        
        self.video_ntbk.append_page(self.sample_viewer, tab_label=_mk_lbl('Sample'))
        self.video_ntbk.append_page(self.hutch_viewer, tab_label=_mk_lbl('Hutch'))
        self.video_ntbk.connect('realize', lambda x: self.video_ntbk.set_current_page(0))
        
        self.cryo_ntbk.append_page(self.cryo_controller, tab_label=_mk_lbl('Cryojet Stream'))

        if self.beamline.humidity_control.status.connected():
            self.video_ntbk.append_page(self.hc_viewer, tab_label=_mk_lbl('Humidity Control'))
            self.video_ntbk.connect('switch-page', self.on_tab_change)
            self.cryo_ntbk.append_page(self.humidity_controller, tab_label=_mk_lbl('Humidity Control'))
            self.cryo_ntbk.connect('switch-page', self.on_tab_change)
            
        
        self.robot_ntbk.append_page(self.sample_picker, tab_label=_mk_lbl('Automounter '))
        self.dewar_loader.set_border_width(3)     
        self.loader_frame.add(self.dewar_loader)
        self.add(self.sample_widget)
        self.dewar_loader.lims_btn.connect('clicked', self.on_import_lims)
        self.dewar_loader.connect('samples-changed', self.on_samples_changed)
        self.dewar_loader.connect('sample-selected', self.on_sample_selected)
        self.beamline.automounter.connect('mounted', self.on_sample_mounted)
        self.beamline.manualmounter.connect('mounted', self.on_sample_mounted, False)
        
    def on_tab_change(self, obj, pointer, page_num):
        if not self.changed_hc:
            if ( obj.get_property("name") == "video_ntbk" and page_num is 2 ) or ( obj.get_property("name") == "cryo_ntbk" and page_num is 1 ):
                self.changed_hc = True
                self.cryo_ntbk.set_current_page(1)
                self.video_ntbk.set_current_page(2)
        else:
            self.changed_hc = False

    def on_samples_changed(self, obj):
        gobject.idle_add(self.emit, 'samples-changed', self.dewar_loader)

    def update_data(self, sample=None):
        self.dewar_loader.mount_widget.update_data(sample)

    def on_sample_mounted(self, obj, mount_info, auto=True):
        if auto:
            if mount_info is not None: # sample mounted
                port, barcode = mount_info
                if barcode.strip() != '': # find crystal in database by barcode one was detected
                    xtl = self.dewar_loader.find_crystal(barcode=barcode)
                    if xtl is not None:
                        if xtl['port'] != port:
                            header = 'Barcode Mismatch'
                            subhead = 'The observed barcode read by the automounter is different from'
                            subhead += 'the expected one. The barcode will be trusted rather than the port.'
                            dialogs.warning(header, subhead)
                    else:
                        xtl =  self.dewar_loader.find_crystal(port=port)
                else: # if barcode is not read correctly or none exists, use port
                    xtl =  self.dewar_loader.find_crystal(port=port)
                gobject.idle_add(self.emit, 'active-sample', xtl)
    
            else:   # sample dismounted
                gobject.idle_add(self.emit, 'active-sample', None)
        else:
            gobject.idle_add(self.emit, 'active-sample', mount_info)
            
    def on_sample_selected(self, obj, crystal):
        
        if crystal.get('load_status', STATUS_NOT_LOADED) == STATUS_LOADED:
            if self.beamline.automounter.is_mountable(crystal['port']):
                self.sample_picker.pick_port(crystal['port'])
                gobject.idle_add(self.emit, 'sample-selected', crystal)
            else:
                self.sample_picker.pick_port(None)
                gobject.idle_add(self.emit, 'sample-selected', {})
        else:
            self.sample_picker.pick_port(None)
            gobject.idle_add(self.emit, 'sample-selected', crystal)

    def update_active_sample(self, sample=None):
        # send updated parameters to runs
        if sample is None:
            self.active_sample = {}
        else:
            self.active_sample = sample
        self.dewar_loader.mount_widget.update_active_sample(self.active_sample)
    
    def update_selected(self, sample=None):
        self.dewar_loader.mount_widget.update_selected(sample)
    
    def get_database(self):
        return self.dewar_loader.samples_database

    def on_import_lims(self, obj):
        reply = lims_tools.get_onsite_samples(self.beamline)
        if reply.get('error') is not None:
            header = 'Error Connecting to the LIMS'
            subhead = 'Containers and Samples could not be imported.'
            details = reply['error'].get('message')
            dialogs.error(header, subhead, details=details)
        else:
            self.dewar_loader.import_lims(reply)
        
        
        
                        