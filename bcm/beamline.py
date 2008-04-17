import os
import gobject
from bcm.devices import positioners, detectors, cameras, misc
from bcm.protocols import ca
from bcm.utils import gtk_idle
from ConfigParser import ConfigParser
import string

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
    'energymotors': positioners.energyMotor,
    'attenuators': positioners.Attenuator,
    'variables': ca.PV
    }


class BeamlineBase(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['log'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,))

    def __init__(self):
        gobject.GObject.__init__(self)
        
    def log(self, text):
        gobject.idle_add(self.emit, 'log', text)
    
    
gobject.type_register(BeamlineBase)
    
    

class PX(BeamlineBase):
    def __init__(self, filename):
        BeamlineBase.__init__(self)
        
        self.config_file = os.environ['BCM_CONFIG_PATH'] + '/' + filename
        self.devices = {}
        
    def setup(self, idle_func=gtk_idle):
        self.log("Beamline config: '%s' " % self.config_file)
        self.log("Setting up beamline devices ...")
        self.config = ConfigParser()
        self.config.read(self.config_file)
        for section in self.config.sections():
            self.log("%s:" % section.upper())
            if _DEVICE_MAP.has_key(section):
                dev_type = _DEVICE_MAP[section]
                for item in self.config.options(section):
                    args = self.config.get(section, item).split('|')
                    self.devices[item] = dev_type(*args)
                    setattr(self, item, self.devices[item])
                    self.log(item)
                    if idle_func is not None:
                        idle_func()
    
if __name__ == '__main__':
    bl = PX('vlinac.conf')
    bl.setup()
    
