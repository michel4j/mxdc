
from bcm.beamline.interfaces import IBeamline
from bcm.settings import *  # @UnusedWildImport
from twisted.python.components import globalRegistry
import imp


class MXBeamline(object):
    """MX Beamline(Macromolecular Crystallography Beamline) objects

    Initializes a MXBeamline object from a python configuration file. The 
    configuration file is loaded as a python module and follows the 
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
              ADMIN_GROUP = Group id for admin users (staff)        
              DEFAULT_EXPOSURE    = A float for the default exposure time
              DEFAULT_ATTENUATION = A float for attenuation in %
              DEFAULT_BEAMSTOP    = Default beam-stop position
              SAFE_BEAMSTOP       = Safe Beam-stop position during mounting
              XRF_BEAMSTOP        = Beam-stop position for XRF scans
              XRF_FWHM            = FWHM of MCA peaks in XRF mode
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
    implements(IBeamline)
    
    def __init__(self, console=False):
        """Kwargs:
            console (bool): Whether the beamline is being used within a console or 
            not. Used internally to register CONSOLE_DEVICES if True. Default is
            False.
        """
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
        """Setup and register the beamline devices from configuration files."""
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
            'admin_groups': getattr(l_settings, 'ADMIN_GROUPS', getattr(g_settings, 'ADMIN_GROUPS', [])),
            'energy_range': getattr(l_settings, 'BEAMLINE_ENERGY_RANGE', getattr(g_settings, 'BEAMLINE_ENERGY_RANGE', (6.0, 18.0))),
            'default_attenuation': getattr(l_settings, 'DEFAULT_ATTENUATION', getattr(g_settings, 'DEFAULT_ATTENUATION', 90.0)),
            'default_exposure': getattr(l_settings, 'DEFAULT_EXPOSURE', getattr(g_settings, 'DEFAULT_EXPOSURE', 0.5)),
            'default_delta': getattr(l_settings, 'DEFAULT_DELTA', getattr(g_settings, 'DEFAULT_DELTA', 0.5)),
            'default_beamstop': getattr(l_settings, 'DEFAULT_BEAMSTOP', getattr(g_settings, 'DEFAULT_BEAMSTOP', 25.0)),
            'default_distance': getattr(l_settings, 'DEFAULT_DISTANCE', getattr(g_settings, 'DEFAULT_DISTANCE', None)),
            'safe_beamstop': getattr(l_settings, 'SAFE_BEAMSTOP', getattr(g_settings, 'SAFE_BEAMSTOP', 25.0)),
            'safe_distance': getattr(l_settings, 'SAFE_DISTANCE', getattr(g_settings, 'SAFE_DISTANCE', 700.0)),
            'xrf_beamstop': getattr(l_settings, 'XRF_BEAMSTOP', getattr(g_settings, 'XRF_BEAMSTOP', 50.0)),           
            'xrf_fwhm': getattr(l_settings, 'XRF_FWHM', getattr(g_settings, 'XRF_FWHM', 0.1)),           
            'xrf_energy_offset': getattr(l_settings, 'XRF_ENERGY_OFFSET', getattr(g_settings, 'XRF_ENERGY_OFFSET', 2.0)),   
            'lims_api_key': getattr(l_settings, 'LIMS_API_KEY', getattr(g_settings, 'LIMS_API_KEY', '')),
            'shutter_sequence': getattr(l_settings, 'BEAMLINE_SHUTTERS', getattr(g_settings, 'BEAMLINE_SHUTTERS')),
            'orientation': getattr(l_settings, 'BEAMLINE_GONIO_POSITION', getattr(g_settings, 'BEAMLINE_GONIO_POSITION')),
            'centering_backlight': getattr(l_settings, 'CENTERING_BACKLIGHT', getattr(g_settings, 'CENTERING_BACKLIGHT')),
            'zoom_levels': getattr(l_settings, 'ZOOM_LEVELS', getattr(g_settings, 'ZOOM_LEVELS', (2,5,8))),
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
        if not 'detector_cover' in self.registry:
            self.registry['detector_cover'] = SimShutter('Dummy Detector Cover')
        
        #Setup Bealine shutters
        _shutter_list = []
        for nm in self.config['shutter_sequence']:
            _shutter_list.append(self.registry[nm])
        self.registry['all_shutters'] = ShutterGroup(*tuple(_shutter_list))
        
        
        # Setup diagnostics on some devices
        self.diagnostics = []
        for k in ['automounter', 'goniometer', 'detector', 'cryojet', 'mca', 'enclosures', 'all_shutters', 'storage_ring']:
            try:
                self.diagnostics.append( DeviceDiag(self.registry[k]) )
            except:
                self.logger.warning('Could not configure diagnostic device')
            
        for k in ['image_server', 'dpm', 'lims', ]:
            try:
                self.diagnostics.append( ServiceDiag(self.registry[k]) )
            except:
                self.logger.warning('Could not configure diagnostic service')
        
        try:
            self.diagnostics.append( DeviceDiag(self.registry['disk_space']) )
        except:
            self.logger.warning('Could not configure diagnostic service')
            

__all__ = ['MXBeamline']
    
