import os
import gobject
import threading
import time
import re
import xmlrpclib
from ConfigParser import ConfigParser
from zope.interface import implements
from zope.component import globalSiteManager as gsm

from bcm.protocol import ca
from bcm.protocol.ca import PV
from bcm.device.motor import VMEMotor, EnergyMotor, BraggEnergyMotor
from bcm.device.motor import PseudoMotor, CLSMotor
from bcm.device.counter import Counter
from bcm.device.misc import Positioner, Attenuator, Shutter, Cryojet, Stage
from bcm.device.misc import Collimator, MostabOptimizer
from bcm.device.detector import MXCCDImager
from bcm.device.goniometer import Goniometer
from bcm.device.monochromator import Monochromator
from bcm.device.mca import MultiChannelAnalyzer
from bcm.device.diffractometer import Diffractometer
from bcm.device.video import CACamera, AxisCamera, AxisPTZCamera
from bcm.service.imagesync_client import ImageSyncClient
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger, log_to_console

log_to_console()

# compare function for sorting according to dependency
def _cmp_arg(a, b):
    if b[2].find('@%s' % a[1]) > 0:
        return 1
    elif a[2].find('@%s' % b[1]) > 0:
        return -1
    else:
        return 0
     
class MXBeamline(object):
    implements(IBeamline)
    
    def __init__(self, filename):
        self.config_file = os.path.join(filename)
        self.registry = {}
        self.config = {}
        self.lock = threading.RLock()
        self.setup()
        gsm.registerUtility(self, IBeamline, 'bcm.beamline')
        ca.flush()
        time.sleep(0.1)
        self.logger.info('Beamline Registered.')
        
    def setup(self):
        ca.threads_init()
        config = ConfigParser()
        config.read(self.config_file)
        sections = config.sections()
        _item_list = []
        
        # read config section
        for section in ['beamline']:
            for item in config.items(section):
                if item[0] == 'name':
                    self.name = item[1]
                elif item[0] == 'energy_range':
                    self.config[item[0]] = map(float, item[1].split(','))
                else:
                    self.config[item[0]] = item[1]
                    
        self.logger = get_module_logger('%s:%s' % (self.__class__.__name__,
                                                   self.name))
        # parse first time to make item list                   
        for section in ['devices', 'services', 'utilities']:
            for item in config.items(section):
                name = item[0]
                vals = item[1].split(',')
                type_ = vals[0].strip()
                args = [ "'%s'" % v.strip() for v in vals[1:] ]
                cmd = '%s(%s)' % (type_, ', '.join(args))
                _item_list.append( (section, name,  cmd) )
        
        # sort according to dependency
        _item_list.sort(_cmp_arg)
        
        # now process item list and create device registry automatically
        for section, name, cmd in _item_list:
            n_cmd = re.sub("'@([^- ,]+)'", "self.registry['\\1']", cmd)
            reg_cmd = "self.registry['%s'] = %s" % (name, n_cmd)
            self.logger.info('Setting up %s: %s' % (section, name))
            exec(reg_cmd)
            if section in ['utilities', 'services']:
                util_cmd = "self.%s = self.registry['%s']" % (name, name)
                self.logger.info('Registering %s: %s' % (section, name))
                exec(util_cmd)
                    
if __name__ == '__main__':
    config_file = '/home/michel/Code/eclipse-ws/beamline-control-module/etc/08id1.conf'
    bl = MXBeamline(config_file)
    
