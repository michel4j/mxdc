import os
import gobject
from bcm.devices import positioners, detectors, cameras, misc
from bcm.protocols import ca
from bcm.utils import gtk_idle
from ConfigParser import ConfigParser
import thread
from bcm.tools import *

import string
import xmlrpclib

_DEVICE_MAP = {
    'clsmotors': positioners.clsMotor,
    'vmemotors': positioners.vmeMotor,
    'pseudomotors': positioners.pseudoMotor,
    'counters': detectors.Counter,
    'positioners': positioners.Positioner,
    'mcas': detectors.MCA,
    'detectors': detectors.MarCCDImager,
    'goniometers': misc.Gonio,
    'shutters': misc.Shutter,
    'qbpms': detectors.QBPM,
    'cameras': cameras.Camera,
    'axiscameras': cameras.AxisCamera,
    'fakecameras': cameras.CameraSim,
    'energymotors': positioners.energyMotor,
    'attenuators': positioners.Attenuator,
    'energymotor': positioners.energyMotor,
    'braggenergymotor': positioners.braggEnergyMotor,
    'variables': ca.PV,
    'webservices': xmlrpclib.ServerProxy,
    'cryojets': misc.Cryojet,
    }


class BeamlineBase(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['log'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,))

    def __init__(self):
        gobject.GObject.__init__(self)
        
    def log(self, text):
        gobject.idle_add(self.emit, 'log', text)

    def on_log(self, obj, text):
        self.log(text)
    
    def __call__(self):
        self.setup()
    
    def setup(self):
        pass
    
gobject.type_register(BeamlineBase)
    
    

class PX(BeamlineBase):
    def __init__(self, filename):
        BeamlineBase.__init__(self)
        
        self.config_file = os.environ['BCM_CONFIG_PATH'] + '/' + filename
        self.devices = {}
        self.config = {}
        self.lock = thread.allocate_lock()  
        
    def __call__(self):
        self.setup()
        
    def setup(self, idle_func=gtk_idle):
        ca.thread_init()
        config = ConfigParser()
        config.read(self.config_file)
        sections =config.sections()
        sec_step = 1.0/len(sections)
        frac_complete = 0.0
        for section in sections:
            item_step = sec_step / (len(config.options(section)))
            if _DEVICE_MAP.has_key(section):
                dev_type = _DEVICE_MAP[section]
                for item in config.options(section):
                    self.log("Setting up %s: %s" % (section, item))
                    args = config.get(section, item).split('|')
                    self.devices[item] = dev_type(*args)
                    setattr(self, item, self.devices[item])
                    frac_complete += item_step
                    gobject.idle_add(self.emit, 'progress', frac_complete)
                    if idle_func is not None:
                        idle_func()
            elif section == 'config':
                for item in config.options(section):
                    if item == 'diagram':
                        arg = config.get(section, item)
                        self.config[item] = os.environ['BCM_CONFIG_PATH'] + '/' + arg
                    if item == 'energy_range':
                        args = config.get(section, item).split('-')
                        self.config['energy_range'] = map(float, args)
                    if item in ['detector_size','pixel_size']:
                        arg = config.get(section, item)
                        self.config[item] = float(arg)
                    frac_complete += item_step
                    gobject.idle_add(self.emit, 'progress', frac_complete)
 
        #for attr in ['ccd', 'sample_cam','energy', 'bragg_energy', 'mca', 
        #             'config', 'gonio', 'i0','attenuator', 'shutter','det_d','det_2th','beam_w','beam_h','image_server']:
        #    assert hasattr(self, attr)

    def configure(self, *args, **kwargs):
        ca.thread_init()
        _moved = []
        for k,v in kwargs.items():
            if k == 'energy':
                self.energy.move_to(v)
                _moved.append(self.energy)
            if k == 'beam_size':
                self.beam_w.move_to(v[0])
                self.beam_h.move_to(v[1])
                _moved.append(self.beam_w)
                _moved.append(self.beam_h)
            if k == 'attenuation':
                self.attenuator.move_to(v)
            if k == 'beamstop_distance':
                self.bst_z.move_to(v)
                _moved.append(self.bst_z)
            if k == 'detector_distance':
                self.det_d.move_to(v)
                _moved.append(self.det_d)
            if k == 'detector_twotheta':
                self.det_2th.move_to(v)
                _moved.append(self.det_2th)
                
        for m in _moved:
            #FIXME: What if the motor has moved and stopped already? It will timeout here.
            m.wait(start=True,stop=False)
        for m in _moved:
            m.wait(start=False,stop=True)
        
        final_pos = {}
        for k,v in kwargs.items():
            if k == 'energy':
                final_pos[k] = self.energy.get_position()
            if k == 'beam_size':
                final_pos[k] = ( self.beam_w.get_position(), self.beam_h.get_position() )
            if k == 'attenuation':
                final_pos[k] = self.attenuator.get_position()
            if k == 'beamstop_distance':
                final_pos[k] = self.bst_z.get_position()
            if k == 'detector_distance':
                final_pos[k] = self.det_d.get_position()
            if k == 'detector_twotheta':
                final_pos[k] = self.det_2th.get_position()            
            
        
        return final_pos
                


        
        
        
if __name__ == '__main__':
    bl = PX('vlinac.conf')
    bl()
    
