"""
.. module:: mxdc.device.base
    :synopsis: Basic beamline device housekeeping.
"""

import re

from gi.repository import GObject  # @UnresolvedImport
from mxdc.com import ca
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class BaseDevice(GObject.GObject):
    """A generic devices object class.  All devices should be derived from this
    class. Objects of this class are instances of `GObject.GObject`. 
    
    **Attributes:**
    
        - `pending_devs`: a list of inactive child devices.
        - `health_manager`: A :class:`HealthManager` object.
        - `state_info`: A dict containing state information.
        - `name`:  the name of the devices
    
    **Signals:**    
        - `active`: emitted when the state of the devices changes from inactive
          to active and vice-versa. Passes a single boolean value.
        - `busy`: emitted to notify listeners of a change in the busy state. A 
          single boolean parameter is passed along with the signal. `True` means
          busy, `False` means not busy.
        - `health`: signals an devices sanity/error condition. Passes two
          parameters, an integer error code and a string description. The 
          integer error codes are:
          
              - 0 : No error
              - 1 : MINOR, no impact to devices functionality.
              - 2 : MARGINAL, no immediate impact. Attention may soon be needed.
              - 4 : SERIOUS, functionality impacted but recovery is possible.
              - 8 : CRITICAL, functionality broken, recovery is not possible.
              - 16 : DISABLED, devices has been manually disabled.
              
        - `message`: signal for sending messages from the devices to any
          listeners. Messages are passed as a single string parameter.

    **Virtual Attributes:**
        - `<signal>_state`: for each signal defined in derived classes, the last
          transmitted data corresponding to the current state can be obtained 
          through the dynamic variable with the suffix "_state" added to the 
          signal name. For example::
         
          >>> obj.active_state
          >>> True
    
    **Virtual Methods:**
        - `is_<signal>()`: for each boolean signal defined in derived clases, the
          current state can be obtained by adding the prefix "is_" to the signal
          name. For example::
          
          >>> obj.is_active()
          >>> True
    """
    # signals
    __gsignals__ = {
        "active": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "busy": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "health": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "message": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        self.pending = []  # inactive child devices or process variables
        self.health_manager = HealthManager()  # manages the health states
        self.state_info = {'active': False, 'busy': False, 'health': (99, ''), 'message': ''}
        self.name = self.__class__.__name__
        self.state_pattern = re.compile('^(\w+)_state$')
        self.bool_pattern = re.compile('^is_(\w+)$')

    def __repr__(self):
        state_txts = []
        for key, value in self.state_info.items():
            state_txts.append(' %12s: %s' % (key, str(value)))
        state_txts.sort()
        txt = "<{}: {}\n{}\n>".format(self.__class__.__name__, self.name, '\n'.join(state_txts))
        return txt

    def do_busy(self, state):
        pass

    def do_health(self, state):
        pass

    def do_message(self, state):
        pass

    def do_active(self, state):
        desc = {True: 'active', False: 'inactive'}
        logger.info("({}) is now {}.".format(self.name, desc[state]))
        if not state and len(self.pending) > 0:
            inactive_devs = [dev.name for dev in self.pending]
            msg = '[{:d}] inactive children.'.format(len(inactive_devs))
            logger.warning("(%s) %s" % (self.name, msg))

    def is_active(self):
        return self.active_state

    def is_busy(self):
        return self.busy_state

    def get_state(self):
        """Obtain a copy of the devices state.
         
        Returns:
            A dict mapping state keys to their correponding values. Entries contain
            at least the following entries:
        
                - `active` : Boolean
                - `busy`: Boolean
                - `health`: tuple(int, string)
                - `message`: string        
        """
        return self.state_info.copy()

    def set_state(self, **kwargs):
        """Set the state of the devices and emit the corresponding signal.
        
        Kwargs:
            Keyworded arguments follow the same conventions as the state 
            dictionary and correspond to any signals defined for the devices.
            Signals must be previously defined as supported signals of the devices.
            
        For example::
        
            mydevice.set_state(active=True, busy=False, 
                               health=(1, 'error','too hot'),
                               message="the devices is overheating")
        """

        for signal, value in kwargs.items():
            if signal != 'health':
                # only signal a state change if it actually changes for non
                # health signals
                sid = GObject.signal_lookup(signal, self)
                if sid == 0: break
                if self.state_info.get(signal, None) != value:
                    self.state_info.update({signal: value})
                    GObject.idle_add(self.emit, signal, value)
                elif value == None:
                    self.state_info.update({signal: None})
                    GObject.idle_add(self.emit, signal)
            elif signal == 'health':
                sev, cntx = value[:2]
                if sev != 0:
                    self.health_manager.add(*value)
                else:
                    self.health_manager.remove(cntx)
                health = self.health_manager.get_health()
                if health[0] == 0 and len(value) == 3:  # allows messages to go through for good health
                    health = (0, value[2])
                if health != self.health_state:
                    self.state_info.update({signal: health})
                    GObject.idle_add(self.emit, signal, health)

    def add_pv(self, *args, **kwargs):
        """Add a process variable (PV) to the devices.
        
        Create a new process variable, add it to the devices.
        Keyworded arguments should be the same as those expected for instantiating the process variable
        class. The Process Variable protocol may be requested by passing in the module through the
        'protocol' key-word argument. The  default protocol will be mxdc.com.ca

        :class:`mxdc.com.ca.PV` object.

        Returns:
            A reference to the created object.
        """

        protocol = kwargs.pop('protocol', ca)

        dev = protocol.PV(*args, **kwargs)
        self.pending.append(dev)
        dev.connect('active', self.on_device_active)
        return dev

    def add_devices(self, *devices):
        """ Add one or more devices as children of this devices. """

        for dev in devices:
            self.pending.append(dev)
            dev.connect('active', self.on_device_active)

    def on_device_active(self, dev, state):
        """I am called every time a devices becomes active or inactive.
        I expect to receive a reference to the devices and a boolean
        state flag which is True on connect and False on disconnect. If it is
        a connection, I add the devices to the pending devices list
        otherwise I remove the devices from the list. When ever the list goes to
        zero, I set the group state to active and inactive otherwise.
        """

        if state and dev in self.pending:
            self.pending.remove(dev)
        elif not state and dev not in self.pending:
            self.pending.append(dev)
        if len(self.pending) == 0:
            self.set_state(active=True, health=(0, 'active'))
        else:
            self.set_state(active=False, health=(4, 'active', '[%d] inactive components.' % len(self.pending)))

    def __getattr__(self, key):
        m = self.state_pattern.match(key)
        n = self.bool_pattern.match(key)
        if m:
            key = m.group(1)
            return self.state_info.get(key, None)
        elif n:
            key = n.group(1)
            val = self.state_info.get(key, None)
            if (val is True) or (val is False):
                # def dyn_func(): return val
                return lambda: val
            else:
                raise AttributeError("%s is not a boolean '%s'" % (self.__class__.__name__, key))
        else:
            raise AttributeError("%s has no attribute '%s'" % (self.__class__.__name__, key))


class HealthManager(object):
    """
    Manages the health states. The object enables registration and removal of
    error states and consistent reporting of health based on all currently 
    active health issues.
    """

    def __init__(self, **kwargs):
        """
        @param kwargs: The keyword name is the context, and
        the value is an error string to be returned instead of the context name
        with all health information for the given context.
        """
        self.messages = kwargs
        self.health_states = set()

    def register_messages(self, **kwargs):
        """
        Update or add entries to the context message register
        @param kwargs: The keyword name is the context, and
        the value is an error string
        @return:
        """
        self.messages.update(kwargs)

    def add(self, severity, context, msg=None):
        """
        Adds an error state to the health registry
        @param severity: Integer representing the severity
        @param context: the context name (str)
        @param msg: If a message is given, it will be
        stored and used instead of the context name. Only one message per context
        type is allowed. Use a different context if you want different messages.
        @return:
        """
        if msg is not None:
            self.messages.update({context: msg})
        self.health_states.add((severity, context))

    def remove(self, context):
        """
        Remove all errors from the given context
        @param context: The context name (str)
        @return:
        """

        err_list = [error for error in self.health_states if error[1] == context]
        for error in err_list:
            self.health_states.remove(error)

    def get_health(self):
        """
        Generate an error code and string based on all the currently registered
        errors within the health registry.
        """
        severity = 0
        msg_list = set()
        for sev, context in self.health_states:
            severity = severity | sev
            msg_list.add(self.messages.get(context, context))
        msg = ' '.join(msg_list)
        return severity, msg
