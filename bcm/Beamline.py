import os
from bcm.devices import positioners, detectors, cameras, misc
from bcm.protocols import ca
from ConfigParser import ConfigParser
import string

_DEVICE_MAP = {
    'clsmotors': positioners.clsMotor,
    'vmemotors': positioners.vmeMotor,
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
class PXBeamline:
    def __init__(self, filename):
        self.config_file = os.environ['BCM_CONFIG_PATH'] + '/' + filename
        self.devices = {}
        
    def setup(self):
        self.config = ConfigParser()
        self.config.read(self.config_file)
        for section in self.config.sections():
            if _DEVICE_MAP.has_key(section):
                dev_type = _DEVICE_MAP[section]
                for item in self.config.options(section):
                    args = self.config.get(section, item).split('|')
                    print item
                    self.devices[item] = dev_type(*args)
                    setattr(self, item, self.devices[item])
    
if __name__ == '__main__':
    bl = PXBeamline('vlinac.conf')
    bl.setup()
    