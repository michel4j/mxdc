import os
import gobject
import thread
import xmlrpclib
from ConfigParser import ConfigParser
from zope.interface import implements
from zope.component import globalSiteManager as gsm
from bcm.device import motor, detector, counter, video, misc, goniometer, mca
from bcm.protocol import ca
from bcm.beamline.interfaces import IBeamline

_DEVICE_MAP = {
    'clsmotors': motor.clsMotor,
    'vmemotors': motor.vmeMotor,
    'pseudomotors': motor.pseudoMotor,
    'counters': counter.Counter,
    'mcas': mca.MultiChannelAnalyzer,
    'detectors': detector.MXCCDImager,
    'goniometers': goniometer.Goniometer,
    'shutters': misc.Shutter,
    'cameras': video.CACamera,
    'axiscameras': video.AxisCamera,
    'fakecameras': video.SimCamera,
    'energymotors': motor.energyMotor,
    'attenuators': misc.Attenuator,
    'energymotor': motor.energyMotor,
    'braggenergymotor': motor.braggEnergyMotor,
    'variables': ca.PV,
    'webservices': xmlrpclib.ServerProxy,
    'cryojets': misc.Cryojet,
    }    
    

class MXBeamline(object):
    implements(IBeamline)
    def __init__(self, filename):
        self.config_file = '/media/seagate/beamline-control-module/etc/' + filename
        self.devices = {}
        self.config = {}
        self.lock = thread.allocate_lock()
        gsm.registerUtility(self, IBeamline, 'bcm.beamline') 
        
    def setup(self):
        ca.threads_init()
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
                    args = config.get(section, item).split('|')
                    self.devices[item] = dev_type(*args)
                    setattr(self, item, self.devices[item])
                    frac_complete += item_step
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
 
        #for attr in ['ccd', 'sample_cam','energy', 'bragg_energy', 'mca', 
        #             'config', 'gonio', 'i0','attenuator', 'shutter','det_d','det_2th','beam_w','beam_h','image_server']:
        #    assert hasattr(self, attr)

    def configure(self, *args, **kwargs):
        ca.threads_init()
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
    bl = MXBeamline('vlinac.conf')
    bl.setup()
    
