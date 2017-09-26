import imp
import os
import threading

from interfaces import IBeamline
from mxdc.com import ca
from mxdc.devices import stages, misc, automounter, diagnostics, motor, video
from mxdc.utils.log import get_module_logger
from twisted.python.components import globalRegistry
from zope.interface import implements


class MXBeamline(object):
    """MX Beamline(Macromolecular Crystallography Beamline) objects

    Initializes a MXBeamline object from a python configuration file. The 
    configuration file is loaded as a python module and follows the 
    following conventions:
    
        -
        - Optionally will also load a local module defined in the file 
          $(MXDC_CONFIG)_local.py e.g 'CMCFBM_local.py for the above example.
        - Global Variables:
              CONFIG       = A dictionary containing any other key value pairs
                             will be available as beamline.config
              DEVICES      = A dictionary mapping devices names to devices objects.
                                    See CLSSIM.py for a standard set of names.
              CONSOLE      = Same as above but only available in the console
                                in addition to the above
              SERVICES = A dictionary mapping services names to services client objects
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
        if key in self.registry:
            return self.registry[key]
        else:
            raise AttributeError('{} does not have attribute: {}'.format(self, key))

    def setup(self):
        """Setup and register the beamline devices from configuration files."""
        ca.threads_init()
        mod_name = os.environ.get('MXDC_CONFIG')
        mod_dir = os.path.join(os.environ.get('MXDC_PATH'), 'etc')
        self.logger = get_module_logger(__name__)
        try:
            g_params = imp.find_module(mod_name, [mod_dir])

            global_settings = imp.load_module('global_settings', *g_params)
            g_params[0].close()
        except ImportError:
            self.logger.error('settings file %s.py not found' % mod_name)
            raise

        try:
            l_params = imp.find_module(mod_name + '_local', [mod_dir])
            local_settings = imp.load_module('local_settings', *l_params)
            l_params[0].close()
        except ImportError:
            local_settings = None

        # Prepare Beamline Configuration
        config = {
            'name': 'SIM-1',
            'admin_groups': [2000],
            'energy_range': (6.0, 18.0),
            'default_attenuation': 90.0,
            'default_exposure': 0.5,
            'default_delta': 0.5,
            'default_beamstop': 25.0,
            'safe_beamstop': 25.0,
            'safe_distance': 700.0,
            'xrf_beamstop': 50.0,
            'xrf_fwhm': 0.1,
            'xrf_energy_offset': 2.0,
            'shutter_sequence': [],
            'orientation': 1,
            'centering_backlight': 65,
        }
        config.update(getattr(global_settings, 'CONFIG', {}))
        config.update(getattr(local_settings, 'CONFIG', {}))
        self.name = config['name']
        self.config = config
        # Register simple devices
        for settings in [global_settings, local_settings]:
            devs = getattr(settings, 'DEVICES', {})
            # Setup devices
            for dev_name, dev in devs.items():
                self.registry[dev_name] = dev
                self.logger.debug('Setting up devices: %s' % (dev_name))

            # Setup Console-only Devices
            if self.console:
                devs = getattr(settings, 'CONSOLE', {})
                for dev_name, dev in devs.items():
                    self.registry[dev_name] = dev
                    self.logger.debug('Setting up devices: %s' % (dev_name))

            # Setup services
            services = getattr(settings, 'SERVICES', {})
            for srv_name, srv in services.items():
                self.registry[srv_name] = srv
                self.logger.debug('Setting up services: %s' % (srv_name))

        # Create and register other/compound devices
        if 'sample_y' in self.registry:
            self.registry['sample_stage'] = stages.Sample2Stage(self.sample_x, self.sample_y, self.omega)
        else:
            self.registry['sample_stage'] = stages.Sample3Stage(self.sample_x, self.sample_y1, self.sample_y2,
                                                                self.omega)
        self.registry['sample_video'] = video.ZoomableCamera(self.sample_camera, self.sample_zoom)
        self.mca.nozzle = self.registry.get('mca_nozzle', None)
        self.registry['manualmounter'] = automounter.ManualMounter()

        # Setup Bealine shutters
        _shutter_list = []
        for nm in self.config['shutter_sequence']:
            _shutter_list.append(self.registry[nm])
        self.registry['all_shutters'] = misc.ShutterGroup(*tuple(_shutter_list))

        # Setup coordination between Beam tuner and energy changes
        if 'beam_tuner' in self.registry:
            self.energy.connect('starting', lambda x: self.beam_tuner.pause())
            self.energy.connect('done', lambda x: self.beam_tuner.resume())

        # default detector cover
        if not 'detector_cover' in self.registry:
            self.registry['detector_cover'] = misc.SimShutter('Dummy Detector Cover')

        # detector max resolution
        self.registry['maxres'] = motor.ResolutionMotor(self.energy, self.distance, self.detector.mm_size)

        # Setup diagnostics on some devices
        device_list = [
            'automounter', 'goniometer', 'detector', 'cryojet', 'mca',
            'enclosures', 'all_shutters', 'storage_ring'
        ]
        self.diagnostics = []
        for name in device_list:
            self.diagnostics.append(diagnostics.DeviceDiag(self.registry[name]))

        for name in ['image_server', 'dpm', 'lims', ]:
            self.diagnostics.append(diagnostics.ServiceDiag(self.registry[name]))

        self.diagnostics.append(diagnostics.DeviceDiag(self.registry['disk_space']))


__all__ = ['MXBeamline']
