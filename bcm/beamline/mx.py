r"""MX Beamline(Macromolecular Crystallography Beamline) objects

This module creates MXBeamline objects (class MXBeamline) from a configuration
file. The configuration file format follows the conventions defined within the 
``ConfigParser`` module of the Python standard library.

The following additional assumptions are applied when interpreting the files: 
values can be a comma separated list such as: ``values = element1, element2, element3,...``
The list of elements are interpreted as follows:
    - 1st element:  device type
    - 2nd, 3rd etc: device instantiation parameters which may be strings
      or other devices. Prefixing @ as the first character
      indicates the element is the name of another device.
      Elements prefixed with '@' must exist independently.
    
The following sections and corresponding required parameters must be present within the 
configuration file:

``beamline``
    Defines beamline configuration parameters 
    
        - ``name`` : The name of the beamline given as a string.
        - ``energy_range``: The energy range available, given as a comma separated pair of floats.
        - ``beamline_diagram``: The file name of a graphic depicting the beamline arrangement.
        - ``beamline_type``: The type of beamline. For example "MX" 
        - ``orientation``: an integer identifying the orientation of the beamline, as derined by XREC.
       
``devices``
    Specifies devices and utilities to be registered for the specific type of beamline being configured.
    Each type of beamline expects somf device types and utilities to be available. The following list shows 
    what is expected for an "MX" Beamline.
    
    - ``monochromator``: A monochromator device
    - ``goniometer``: A goniometer device
    - ``diffractometer``: A diffractometer device
    - ``detector``: An imaging detector device
    - ``i_0``: A counter device
    - ``cryojet``: A cryojet device
    - ``sample_video``: A sample video source
    - ``beam_stop``: A beam-stop device
    - ``exposure_shutter``: A shutter for exposures
    - ``attenuator``: An attenuator device
    - ``mca``: A multichannel analyzer
    - etc.
        
``services``
    Web services

"""



import os
import gobject
import threading
import time
import re
import xmlrpclib
from ConfigParser import ConfigParser
from zope.interface import implements
from twisted.python.components import globalRegistry

from bcm.protocol import ca
from bcm.protocol.ca import PV
from bcm.device.motor import *
from bcm.device.counter import *
from bcm.device.misc import *
from bcm.device.detector import *
from bcm.device.diagnostics import *
from bcm.device.goniometer import *
from bcm.device.automounter import *
from bcm.device.monochromator import Monochromator
from bcm.device.mca import *
from bcm.device.diffractometer import Diffractometer
from bcm.device.video import *
from bcm.service.imagesync_client import *
from bcm.engine.optimizer import *
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger, log_to_console

#log_to_console()

# compare function for sorting according to dependency
def _cmp_arg(a, b):
    if b[2].find('@%s' % a[1]) > 0:
        return 1
    elif a[2].find('@%s' % b[1]) > 0:
        return -1
    else:
        return 0
     
class MXBeamline(object):
    """An MX Beamline"""
    implements(IBeamline)
    
    def __init__(self, filename):
        self.config_file = os.path.join(filename)
        self.registry = {}
        self.config = {}
        self.lock = threading.RLock()
        self.setup()
        globalRegistry.register([], IBeamline, '', self)
        ca.flush()
        time.sleep(0.1)
        self.logger.info('Beamline Registered.')

    def __getitem__(self, key):
        try:
            return self.registry[key]
        except:
            keys = key.split('.')
            v = getattr(self, keys[0])
            for key in keys[1:]:
                v = getattr(v, key)
            return v        
    
    def __getattr__(self, key):
        try:
            return super(MXBeamline).__getattr__(self, key)
        except AttributeError:
            return self.registry[key]
        
    def setup(self):
        """Set up and register the beamline devices."""
        ca.threads_init()
        config = ConfigParser()
        config.read(self.config_file)
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
        for section in ['devices', 'services','utilities']:
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
            #self.logger.debug('Setting up %s: %s' % (section, name))
            exec(reg_cmd)
        self.device_config = _item_list

__all__ = ['MXBeamline']
    
