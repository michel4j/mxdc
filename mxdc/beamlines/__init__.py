import threading
import importlib.util
import importlib.machinery
import os

from zope.interface import implementer

from mxdc import Registry, Object, Signal, IBeamline
from mxdc.utils.misc import get_project_id, DotDict, import_string
from mxdc.utils.log import get_module_logger


@implementer(IBeamline)
class Beamline(Object):
    """
    Base class for all Beamline objects

    Initializes a Beamline object from a python configuration file. The devices
    defined in the configuration file can be accessed by name as attributes
    of the beamline.

    :param console: if True, initialize console devices as well

    The configuration file is loaded as a python module and follows the
    following conventions:

        * Optionally will also load a local module defined in the file
          <config-module>_local.py for the above example.
        * Global Variables:

    Signals:
        - ready: (bool,)

    Attributes:
        - DEFAULTS: dict, default config values for the beamline
        - REQUIRED: list of required device names. All devices on this list must be
          defined in the config file.
    """

    class Signals:
        ready = Signal("ready", arg_types=(bool,))

    DEFAULTS = {}  # Default values for fields in the CONFIG dictionary
    REQUIRED = {}  # Required device names in the DEVICES or SERVICES dictionary

    def __init__(self, console=False):
        from mxdc.conf import settings
        super().__init__()
        self.console = console
        self.config_files = settings.get_configs()
        self.registry = {}
        self.config = DotDict()
        self.lock = threading.RLock()
        self.logger = get_module_logger(self.__class__.__name__)
        self.load_config()
        Registry.add_utility(IBeamline, self)

    def __getattr__(self, key):
        if key in self.registry:
            return self.registry[key]
        else:
            raise AttributeError('{} does not have attribute: {}'.format(self, key))

    def load_config(self):
        """
        Read the configuration file and register all devices. You should not need to call
        this method directly.
        """
        global_file, local_file = self.config_files
        global_module = os.path.splitext(os.path.basename(global_file))[0]
        local_module = os.path.splitext(os.path.basename(local_file))[0]
        config_dir = os.path.dirname(global_file)
        local_settings = None

        try:
            spec = importlib.machinery.PathFinder().find_spec(global_module, [config_dir])
            global_settings = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(global_settings)
        except (ImportError, AttributeError):
            self.logger.error('Config file error')
            raise

        spec = importlib.machinery.PathFinder().find_spec(local_module, [config_dir])
        if spec:
            try:
                local_settings = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(global_settings)
            except ImportError:
                local_settings = None

        # Prepare Beamline Configuration
        config = self.DEFAULTS.copy()
        config.update(getattr(global_settings, 'CONFIG', {}))
        config.update(getattr(local_settings, 'CONFIG', {}))

        self.name = config.get('name', 'BL001')
        self.config.update(config)

        # Register simple devices
        for settings in [global_settings, local_settings]:
            devices = getattr(settings, 'DEVICES', {})
            # Setup devices
            for dev_name, dev in list(devices.items()):
                self.registry[dev_name] = dev
                self.logger.debug('Setting up devices: %s' % (dev_name))

            # Setup Console-only Devices
            if self.console:
                devices = getattr(settings, 'CONSOLE', {})
                for dev_name, dev in list(devices.items()):
                    self.registry[dev_name] = dev
                    self.logger.debug('Setting up devices: %s' % (dev_name))

            # Setup services
            services = getattr(settings, 'SERVICES', {})
            for srv_name, srv in list(services.items()):
                self.registry[srv_name] = srv
                self.logger.debug('Setting up services: {}'.format(srv_name))

        # Make sure all required devices are registered
        registered = set(self.registry.keys())
        if registered >= set(self.REQUIRED):
            self.logger.debug('All required devices/services registered.')
        else:
            missing = set(self.REQUIRED) - registered
            self.logger.error("Required devices/services not defined: {}".format(missing))
            raise AttributeError('Missing devices: {}'.format(missing))

        # finally run custom setup operations after all devices have been added to registry
        self.setup()

    def setup(self):
        """
        Additional setup tasks should be defined here. This is run after the configuration is loaded
        and all devices and services have been added to the registry
        """

    def cleanup(self):
        """
        Cleanup devices which can be cleaned up
        """
        for name, device in list(self.registry.items()):
            if hasattr(device, 'cleanup'):
                device.cleanup()

    def is_admin(self):
        """
        Check if the current user is an administrator
        """
        return get_project_id() in self.config.get('admin_groups', [])

    def is_ready(self):
        """
        Check if beamline is ready
        """
        return self.get_state('ready')


def build_beamline(console=False):
    """
    Create and return a beamline object of the appropriate type as determined by the config file
    :param console: Whether to instantiate console devices.
    :return: beamline object
    """
    from mxdc.conf import PROPERTIES
    beamline_class_name = PROPERTIES.get('type', 'mxdc.beamlines.mx.MXBeamline')
    BeamlineClass = import_string(beamline_class_name)
    return BeamlineClass(console=console)


__all__ = ['Beamline', 'IBeamline', 'build_beamline']