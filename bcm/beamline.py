import os
import gobject
from bcm.devices import positioners, detectors, cameras, misc
from bcm.protocols import ca
from bcm.utils import gtk_idle
from ConfigParser import ConfigParser
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
    'webservices': xmlrpclib.ServerProxy
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
        
    def __call__(self):
        self.setup()
        
    def setup(self, idle_func=gtk_idle):
        config = ConfigParser()
        config.read(self.config_file)
        sec_step = 1.0 / len(config.sections())
        frac_complete = 0.0
        for section in config.sections():
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
                    if hasattr(self.devices[item], 'connect') and section not in ['variables', 'webservices']:
                        self.devices[item].connect('log', self.on_log)
            elif section == 'config':
                for item in config.options(section):
                    if item == 'diagram':
                        arg = config.get(section, item)
                        self.config[item] = os.environ['BCM_CONFIG_PATH'] + '/' + arg
                    if item == 'energy_range':
                        args = config.get(section, item).split('-')
                        self.config['energy_range'] = map(float, args)
                    frac_complete += item_step
                    gobject.idle_add(self.emit, 'progress', frac_complete)           
                
    
if __name__ == '__main__':
    bl = PX('vlinac.conf')
    bl()
    
