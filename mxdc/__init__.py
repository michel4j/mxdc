import atexit
import threading
import reprlib

from gi.repository import GObject, GLib
from gi.types import GObjectMeta
from zope.interface import providedBy, Interface, Attribute
from zope.interface.adapter import AdapterRegistry
from zope.interface.interface import adapter_hooks

from mxdc.com import ca
from mxdc.utils.log import get_module_logger, log_call
from mxdc.utils.misc import check_call

logger = get_module_logger(__name__)


obj_repr = reprlib.Repr()
obj_repr.maxlevel = 4
obj_repr.maxdict = 1


class IBeamline(Interface):
    """
    Inteface for Beamline Objects
    """
    name = Attribute("""Name or description of devices.""")
    config = Attribute("""A dictionary of beamline configuratioin parameters.""")
    lock = Attribute("""A reentrant lock""")


class Registry(object):
    """
    Proxy class for managing Utility and Adapter registries
    """
    utilities = AdapterRegistry()
    adapters = AdapterRegistry()

    @classmethod
    def add_adapter(cls, *args, **kwargs):
        """
        Wrapper for zope.interface.AdapterRegistry.register
        """
        cls.adapters.register(*args, **kwargs)

    @classmethod
    def subscribe(cls, interface, obj):
        """
        Register a subscription of an object for a given interface

        :param interface: Target interface
        :param obj: object
        """
        cls.utilities.subscribe([], interface, obj)

    @classmethod
    def add_utility(cls, interface, obj, name=''):
        """
        Register an object as a utility for a given interface

        :param interface:
        :param obj: utility
        :param name: optional name for utility
        """
        cls.utilities.register([], interface, name, obj)

    @classmethod
    def get_utility(cls, interface, name=''):
        """
        Fetch the utility which provides a given interface

        :param interface:
        :param name: optional name for utility
        :return: utility
        """
        return cls.utilities.lookup([], interface, name)

    @classmethod
    def get_subscribers(cls, interface):
        """
        Fetch all subscribers for a given interface

        :param interface:
        :return: list of subscribers
        """
        return cls.utilities.subscriptions([], interface)


def _hook(provided, obj):
    """
    Support syntactic sugar for easy creation of adaptors

    :param provided: interface
    :param obj: object to adapt
    :return: adapted object
    """

    adapter = Registry.adapters.lookup1(providedBy(obj), provided, '')
    if adapter is not None:
        return adapter(obj)


def _del_hook():
    adapter_hooks.remove(_hook)


# manage hooks
adapter_hooks.append(_hook)
atexit.register(_del_hook)


def _get_signal_ids(itype):
    """
    Get a list of all signal names supported by the object

    :param itype: type (GObject.GType) - Instance or interface type.
    :returns: list of strings
    """
    try:
        parent_type = GObject.type_parent(itype)
        parent_signals = _get_signal_ids(parent_type)
    except RuntimeError:
        parent_signals = []
    return GObject.signal_list_ids(itype) + parent_signals


def _get_signal_properties(itype):
    queries = (GObject.signal_query(sig_id) for sig_id in _get_signal_ids(itype))
    return {
        query.signal_name: query.param_types
        for query in queries
    }


Signal = GObject.Signal
Property = GObject.Property


class ObjectType(GObjectMeta):
    """
    MetaClass for adding extra syntactic sugar when you want to define signals without polluting the namespace with
    signal names
    """

    def __new__(cls, name, superclasses, attributes):
        signals = attributes.get('Signals', None)
        if signals:
            attributes.update({
                '__sig_{}'.format(name): signal
                for name, signal in signals.__dict__.items() if isinstance(signal, Signal)
            })
        return GObjectMeta.__new__(cls, name, superclasses, attributes)


class Object(GObject.GObject, metaclass=ObjectType):
    """
    Base Class for event-aware objects in MxDC which can emit signals and register
    callbacks.

    Signals are defined through the `Signals` attribute class as follows:

    .. code-block:: python

        class Signals:
            name = Signal('name', arg_types=(str,))
            ready = Signal('ready', arg_types=(bool, str))

    """

    def __init__(self):
        super().__init__()
        self.name = self.__class__.__name__
        self.__signal_types__ = _get_signal_properties(self)
        self.__state__ = {name: None for name in self.__signal_types__.keys()}
        self.__identifier__ = ''

    def __str__(self):
        obj_id = hex(id(self))
        return (
            f"<{self.__class__.__name__} | {self.name} | {obj_id}/>"
        )

    def __repr__(self):
        state_info = '\n'.join(
            f'    {name}: {obj_repr.repr(value)}'
            for name, value in sorted(self.get_states().items())
            if value is not None
        )
        obj_id = hex(id(self))
        return (
            f"<{self.__class__.__name__} | {self.name} | {obj_id}\n"
            f"{state_info}"
            f"\n/>"
        )

    def _emission(self, signal, *args):
        try:
            super().emit(signal, *args)
        except TypeError as e:
            logger.error("'{}': Invalid parameters for signal '{}': {}".format(self, signal, args))

    # # # FOR diagnosis
    # def connect(self, signal:str, func, *args, **kwargs):
    #     return super().connect(signal, check_call(func), *args, **kwargs)

    def emit(self, signal: str, *args, force=False):
        """
        Emit the signal. Signal emissions are thread safe and will be handled in the main thread.

        :param signal: Signal name
        :param args: list of signal parameters
        :param force: if True emit the signal even if the value is the same as before

        """

        signal = signal.replace('_', '-')

        num_args = len(args)
        current = self.__state__.get(signal)
        if num_args == 0:
            value = None
        elif num_args == 1:
            value = args[0]
        else:
            value = args

        if isinstance(value, (dict, list)):
            force = True

        # Only emit signal if non-blank existing value is not the same as new value
        if force or ((current != value) or (current is None) or signal not in self.__state__):
            self.__state__[signal] = value
            if GLib.main_context_get_thread_default():
                self._emission(signal, *args)
            else:
                GLib.idle_add(self._emission, signal, *args)

    def get_state(self, item: str):
        """
        Get a specific state by key. The key is transformed so that underscores are replaced with hyphens
        (i.e, 'event_name' is translated to 'event-name')

        :param item: state key
        """
        return self.__state__.get(item.replace('_', '-'))

    def get_states(self):
        """
        Obtain a copy of the internal state dictionary. The returned dictionary is not
        neccessarily usable as kwargs for set_state due to the '_' to '-' transformation of the keys.
        """
        return self.__state__.copy()

    def set_state(self, *args, **kwargs):
        """
        Set the state of the object and emit the corresponding signal.

        :param args: list of strings corresponding to non-value signal names
        :param kwargs: name, value pairs corresponding to signal name and signal arguments.
        """

        for signal in args:
            self.emit(signal)

        for signal, value in kwargs.items():
            if isinstance(value, (tuple, list)):
                self.emit(signal, *value, force=True)
            else:
                self.emit(signal, value, force=True)


class Device(Object):
    """
    Base device object. All devices should be derived from this class.

    Signals:

        * "active": arg_types=(bool,), True when device is ready to be controlled
        * "busy": arg_types=(bool,), True when device is busy
        * "enabled": arg_types=(bool,), True when device is enabled for control
        * "health": arg_types=(severity: int, context: str, message: str), represents the health state of the device the severity levels are

            - 0: OK,
            - 1: MINOR,
            - 2: MARGINAL,
            - 4: SERIOUS,
            - 8: CRITICAL,
            - 16: DISABLED

    """

    class Signals:
        active = Signal("active", arg_types=(bool,))
        busy = Signal("busy", arg_types=(bool,))
        enabled = Signal("enabled", arg_types=(bool,))
        health = Signal("health", arg_types=(int, str, str))
        message = Signal("message", arg_types=(str,))

    def __init__(self):
        super().__init__()
        self.__pending = []
        self.__features = set()
        # inactive child devices or process variables
        self.health_manager = HealthManager()   # manages the health states
        GLib.timeout_add(10000, self.check_inactive)

    def do_active(self, state):
        desc = {True: 'active', False: 'inactive'}
        logger.info("'{}' is now {}.".format(self.name, desc[state]))
        if not state and len(self.__pending) > 0:
            inactive_devs = [dev.name for dev in self.__pending]
            msg = '[{:d}] inactive variables.'.format(len(inactive_devs))
            logger.debug("'{}' {}".format(self.name, msg))

    def configure(self, **kwargs):
        """
        Configure the device.  Keyword arguments and implementation details are device specific.
        """

    def supports(self, *features):
        """
        Check if device supports all of the features specified

        :param features: one or more features to check
        :return: bool
        """
        return all(feature in self.__features for feature in features)

    def add_features(self, *features):
        """
        Flag the provided features as supported

        :param features: features supported by device. Features can be any python object.
        """
        self.__features |= set(features)

    def is_healthy(self):
        """
        Check if all health flags are clear
        """
        try:
            severity, context, message = self.get_state('health')
        except (ValueError, TypeError):
            return False
        else:
            return severity <= 1

    def is_active(self):
        """
        Check if the device is active and ready for commands
        """
        return self.get_state("active")

    def is_busy(self):
        """
        Check if the device is busy/moving
        """
        return self.get_state("busy")

    def is_enabled(self):
        """
        Check if the device is enabled/disabled
        """
        return self.get_state("enabled")

    def check_inactive(self):
        if self.__pending:
            inactive = [dev.name for dev in self.__pending]
            self.set_state(health=(16, 'inactive', '{} Inactive'.format(len(inactive))))
            logger.error("'{}':  {} inactive components:".format(self.name, len(inactive)))

    def set_state(self, *args, **kwargs):
        # health needs special pre-processing
        if 'health' in kwargs:
            value = kwargs.pop('health')

            sev, ctx, msg = value
            if sev != 0:
                self.health_manager.add(*value)
            else:
                self.health_manager.remove(ctx)
            health = self.health_manager.get_health()
            if health != self.get_state('health'):
                self.emit('health', *health)

        super().set_state(*args, **kwargs)

    def add_pv(self, *args, **kwargs):
        """
        Create a new process variable (PV) and add it as a component to the device.

        Arguments and Keyworded arguments should be the same as those expected for instantiating the process variable
        class.
        """
        dev = ca.PV(*args, **kwargs)
        self.__pending.append(dev)
        dev.connect('active', self.on_component_active)
        return dev

    def add_components(self, *components):
        """
        Add one or more components as children of this device. Components can be other devices.

        :param components: components to add to this device
        """

        for dev in components:
            if not dev.is_active():
                self.__pending.append(dev)
            dev.connect('active', self.on_component_active)

    def get_pending(self):
        """
        Get a list of pending/inactive components
        """

        return self.__pending

    def on_component_active(self, component, state):
        """
        Callback which is processed every time a component becomes active or inactive, and manages the list
        of pending components.

        :param component: sub-component
        :param state: state of component, True if active, False if inactive
        """

        if state and component in self.__pending:
            self.__pending.remove(component)
        elif not state and component not in self.__pending:
            self.__pending.append(component)
        if len(self.__pending) == 0:
            self.set_state(active=True, health=(0, 'active', ''))
        elif self.get_state('active'):
            # only emit if current active
            self.set_state(active=False, health=(4, 'active', 'inactive components.'))

    def cleanup(self):
        """
        Clean up before shutdown
        """


class HealthManager(object):
    """
    Manages the health states. The object enables registration and removal of
    error states and consistent reporting of health based on all currently
    active health issues.

    :param kwargs: The keyword name is the context, and
        the value is an error string to be returned instead of the context name
        with all health information for the given context.
    """

    def __init__(self, **kwargs):
        self.messages = kwargs
        self.health_states = set()

    def register_messages(self, **kwargs):
        """
        Update or add entries to the context message register.

        :param kwargs: The keyword name is the context, and
            the value is an error string
        :returns:
        """
        self.messages.update(kwargs)

    def add(self, severity, context, msg=None):
        """
        Adds an error state to the health registry.

        :param severity: Integer representing the severity
        :param context: the context name (str)
        :param msg: If a message is given, it will be
            stored and used instead of the context name. Only one message per context
            type is allowed. Use a different context if you want different messages.
        """
        if msg is not None:
            self.messages.update({context: msg})
        self.health_states.add((severity, context))

    def remove(self, context):
        """
        Remove all errors from the given context

        :param context: The context name (str)
        """

        err_list = [error for error in self.health_states if error[1] == context]
        for error in err_list:
            self.health_states.remove(error)

    def get_health(self):
        """
        Generate an error code and string based on all the currently registered
        errors within the health registry.

        :return: The health state tuple, (severity: int,  context: str, message: str)
        """
        severity = 0
        msg_list = set()
        for sev, context in self.health_states:
            severity = severity | sev
            msg_list.add(self.messages.get(context, context))
        msg = ' '.join(msg_list)
        return severity, '', msg


class Engine(Object):
    """
    Base class for all Engines.

    An Engine provides utilities for running stoppable/pausable activities
    in a thread, reporting progress and notifying watchers of the start, end and progress
    of the activity

    Signals:
        - **started**: arg_types=(data: object,)
        - **stopped**: arg_types=(data: object,)
        - **busy**: arg_types=(bool,)
        - **done**: arg_types=(data: object,)
        - **error**: arg_types=(str,)
        - **paused**: arg_types=(paused: bool, reason: str)
        - **progress**: arg_types=(fraction: float, message: str)

    Attributes:
        - **beamline**: Beamline Object
    """

    class Signals:
        started = Signal('started', arg_types=(object,))
        stopped = Signal('stopped', arg_types=(object,))
        busy = Signal('busy', arg_types=(bool,))
        done = Signal('done', arg_types=(object,))
        error = Signal('error', arg_types=(str,))
        paused = Signal('paused', arg_types=(bool, str))
        progress = Signal('progress', arg_types=(float, object))

    def __init__(self):
        super().__init__()
        self.stopped = True
        self.paused = False
        self.beamline = Registry.get_utility(IBeamline)

    def __engine__(self):
        """
        Proxy for calling run method inside a thread
        """
        ca.threads_init()
        self.run()

    def is_stopped(self):
        """
        Check if the engine is stopped
        """
        return self.stopped

    def is_paused(self):
        """
        Check if the engine is paused
        """
        return self.paused

    def is_busy(self):
        """
        Check if the engine is busy
        """
        return self.get_state("busy")

    def start(self):
        """
        Start the engine as a daemon thread
        """
        worker_thread = threading.Thread(target=self.__engine__)
        worker_thread.setDaemon(True)
        worker_thread.setName(self.__class__.__name__)
        self.paused = False
        self.stopped = False
        worker_thread.start()

    def execute(self):
        """
        Run engine in the current thread
        :return: the result of the run method
        """
        self.paused = False
        self.stopped = False
        return self.run()

    def stop(self):
        """
        Stop the engine
        """
        self.stopped = True
        self.paused = False

    def pause(self, reason=''):
        """
        Pause the engine

        :param reason: Optional string describing the reason for the pause
        """
        self.paused = True
        self.emit('paused', self.paused, reason)

    def resume(self):
        """
        Resume from the paused state
        """
        self.paused = False
        self.emit('paused', self.paused, '')

    def run(self):
        """
        This method should contain the implementation details of the engine operation.
        It should appropriately monitor the stopped and paused variables and act accordingly.
        """
        raise NotImplementedError('Must be implemented by subclasses')
