"""MX Beamline(Macromolecular Crystallography Beamline) objects

This module creates MXBeamline objects (class MXBeamline) from a python
configuration file
file. The configuration file is loaded as a python module and follows the 
following conventions:

    - Must be named the same as BCM_BEAMLINE environment variable followed by .py
      and placed in the directory defined by BCM_CONFIG_PATH. For example if the 
      BCM_BEAMLINE is '08B1', the module should be '08B1.py'
    - Optionally will also load a local module defined in the file 
      $(BCM_BEAMLINE)_local.py e.g '08B1_local.py for the above example.
    - Global Variables:
          BEAMLINE_NAME = Any string preferably without spaces
          BEAMLINE_TYPE = Only the string 'MX' for now
          BEAMLINE_ENERGY_RANGE = A tuple of 2 floats for low and hi energy limits
          BEAMLINE_GONIO_POSITION = Goniometer orientation according to XREC (i.e 1,2,3 etc)          
          DEFAULT_EXPOSURE    = A float for the default exposure time
          DEFAULT_ATTENUATION = A float for attenuation in %
          DEFAULT_BEAMSTOP    = Default beam-stop position
          SAFE_BEAMSTOP       = Safe Beam-stop position during mounting
          XRF_BEAMSTOP        = Beam-stop position for XRF scans
          LIMS_API_KEY        = A string
          MISC_SETTINGS       = A dictionary containing any other key value pairs
                                will be available as beamline.config['misc']
          DEVICES             = A dictionary mapping device names to device objects.
                                See SIM.py for a standard set of names.
          CONSOLE_DEVICES = Same as above but only available in the console
                            in addition to the above
          SERVICES = A dictionary mapping service names to service client objects
          BEAMLINE_SHUTTERS = A sequence of shutter device names for all shutters
                             required to allow beam to the end-station in the order 
                             in which they have to be opened.

"""



import os
import threading
import time
import re
import imp
from ConfigParser import ConfigParser
from zope.interface import implements
from twisted.python.components import globalRegistry

from bcm.protocol import ca
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger, log_to_console
from bcm.settings import *

       
class MXBeamline(object):
    """An MX Beamline"""
    implements(IBeamline)
    
    def __init__(self, console=False):
        self.console = console
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
        mod_name = os.environ.get('BCM_BEAMLINE')
        mod_dir = os.environ.get('BCM_CONFIG_PATH')
        self.logger = get_module_logger(__name__)
        try:
            g_params = imp.find_module(mod_name, [mod_dir])
            g_settings = imp.load_module('global_settings', *g_params)
            g_params[0].close()
        except ImportError:
            self.logger.error('settings file %s.py not found' % mod_name)
            raise
            
        try:
            l_params = imp.find_module(mod_name+'_local', [mod_dir])       
            l_settings = imp.load_module('local_settings', *l_params)
            l_params[0].close()
        except ImportError:
            l_settings = None
    
        # Prepare Beamline Configuration
        self.name = getattr(l_settings, 'BEAMLINE_NAME', getattr(g_settings, 'BEAMLINE_NAME', 'SIM-1'))
        
        _misc = getattr(g_settings, 'MISC_SETTINGS', {})
        _misc.update(getattr(l_settings, 'MISC_SETTINGS', {}))
        self.config.update({
            'name': self.name,
            'energy_range': getattr(l_settings, 'ENERGY_RANGE', getattr(g_settings, 'ENERGY_RANGE', (6.0, 18.0))),
            'default_attenuation': getattr(l_settings, 'DEFAULT_ATTENUATION', getattr(g_settings, 'DEFAULT_ATTENUATION', 90.0)),
            'default_exposure': getattr(l_settings, 'DEFAULT_EXPOSURE', getattr(g_settings, 'DEFAULT_EXPOSURE', 1.0)),
            'default_beamstop': getattr(l_settings, 'DEFAULT_BEAMSTOP', getattr(g_settings, 'DEFAULT_BEAMSTOP', 25.0)),
            'safe_beamstop': getattr(l_settings, 'SAFE_BEAMSTOP', getattr(g_settings, 'SAFE_BEAMSTOP', 25.0)),
            'xrf_beamstop': getattr(l_settings, 'XRF_BEAMSTOP', getattr(g_settings, 'XRF_BEAMSTOP', 50.0)),           
            'lims_api_key': getattr(l_settings, 'LIMS_API_KEY', getattr(g_settings, 'LIMS_API_KEY', '')),
            'shutter_sequence': getattr(l_settings, 'BEAMLINE_SHUTTERS', getattr(g_settings, 'BEAMLINE_SHUTTERS')),
            'orientation': getattr(l_settings, 'BEAMLINE_GONIO_POSITION', getattr(g_settings, 'BEAMLINE_GONIO_POSITION')),
            'misc': _misc,        
            })
                    
        # Register simple devices
        for settings in [g_settings, l_settings]:
            devs = getattr(settings, 'DEVICES', {})
            # Setup devices
            for dev_name, dev in devs.items():
                self.registry[dev_name] = dev               
                self.logger.debug('Setting up device: %s' % (dev_name))

            # Setup Console-only Devices
            if self.console:
                devs = getattr(settings, 'CONSOLE_DEVICES', {})
                for dev_name, dev in devs.items():
                    self.registry[dev_name] = dev               
                    self.logger.debug('Setting up device: %s' % (dev_name))
            
            # Setup services
            srvs = getattr(settings, 'SERVICES', {})
            for srv_name, srv in srvs.items():
                self.registry[srv_name] = srv            
                self.logger.debug('Setting up service: %s' % (srv_name))
        
        # Create and register other/compound devices
        self.registry['monochromator'] = Monochromator(self.bragg_energy, self.energy, self.mostab)
        self.registry['collimator'] = Collimator(self.beam_x, self.beam_y, self.beam_w, self.beam_h)
        self.registry['diffractometer'] = Diffractometer(self.distance, self.two_theta)
        if 'sample_y' in self.registry:
            self.registry['sample_stage'] = XYStage(self.sample_x, self.sample_y)
        else:
            self.registry['sample_stage'] = SampleStage(self.sample_x, self.sample_y1, self.sample_y2, self.omega)
        self.registry['sample_video'] = ZoomableCamera(self.sample_camera, self.sample_zoom)
        self.registry['manualmounter'] = ManualMounter()
        self.mca.nozzle = self.registry.get('mca_nozzle', None)
        self.registry['manualmounter'] = ManualMounter()
        
        #Setup Bealine shutters
        _shutter_list = []
        for nm in self.config['shutter_sequence']:
            _shutter_list.append(self.registry[nm])
        self.registry['all_shutters'] = ShutterGroup(*tuple(_shutter_list))
        
        # Setup diagnostics on some devices
        self.diagnostics = []
        for k in ['automounter', 'goniometer', 'detector', 'cryojet', 'storage_ring', 'mca']:
            try:
                self.diagnostics.append( DeviceDiag(self.registry[k]) )
            except:
                self.logger.warning('Could not configure diagnostic device')
        try:
            self.diagnostics.append(ShutterStateDiag(self.all_shutters))
        except:
            self.logger.warning('Could not configure diagnostic device')
            

__all__ = ['MXBeamline']
    
