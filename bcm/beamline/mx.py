import os
import gobject
import thread
import xmlrpclib
from ConfigParser import ConfigParser
from zope.interface import implements
from zope.component import globalSiteManager as gsm

from bcm.protocol import ca
from bcm.device.motor import VMEMotor, EnergyMotor, BraggEnergyMotor
from bcm.device.motor import PseudoMotor, CLSMotor
from bcm.device.misc import Positioner, Attenuator, Shutter, Cryojet, Stage
from bcm.device.misc import Collimator, MostabOptimizer
from bcm.device.detector import MXCCDImager
from bcm.device.goniometer import Goniometer
from bcm.device.monochromator import Monochromator
from bcm.device.mca import MultiChannelAnalyzer
from bcm.device.diffractometer import Diffractometer
from bcm.device.video import CACamera, AxisCamera
from bcm.service.imagesync_client import ImageSyncClient
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger

import pprint

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

class MXBeamline(object):
    implements(IBeamline)
    
    def __init__(self, filename):
        self.config_file = os.path.join(filename)
        self.devices = {}
        self.config = {}
        self.lock = thread.allocate_lock()
        self.setup()
        gsm.registerUtility(self, IBeamline, 'bcm.beamline')
        _logger.info('Beamline Registered.')
        
    def setup(self):
        ca.threads_init()
        config = ConfigParser()
        config.read(self.config_file)
        sections = config.sections()
        _temp_items = {}
        for section in ['devices', 'services', 'utilities']:
            _temp_items[section] = []
            print section
            for item in config.items(section):
                if '@' in item[1]:
                    _temp_items[section].append(item)
                else:
                    print '\t', item[0], item[1].split(',')[0]
        pprint.pprint(_temp_items)
        
if __name__ == '__main__':
    config_file = '/home/michel/Code/eclipse-ws/beamline-control-module/etc/08id1.conf'
    bl = MXBeamline(config_file)
    
