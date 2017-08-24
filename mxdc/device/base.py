"""
.. module:: mxdc.device.base
    :synopsis: Basic beamline device housekeeping.
"""

from gi.repository import GObject  # @UnresolvedImport
from mxdc.com import ca
from mxdc.utils.log import get_module_logger
import re

logger = get_module_logger('devices')

class BaseDevice(GObject.GObject):
    """A generic device object class.  All devices should be derived from this 
    class. Objects of this class are instances of `GObject.GObject`. 
    
    **Attributes:**
    
        - `pending_devs`: a list of inactive child devices.
        - `health_manager`: A :class:`HealthManager` object.
        - `state_info`: A dict containing state information.
        - `name`:  the name of the device
    
    **Signals:**    
        - `active`: emitted when the state of the device changes from inactive 
          to active and vice-versa. Passes a single boolean value.
        - `busy`: emitted to notify listeners of a change in the busy state. A 
          single boolean parameter is passed along with the signal. `True` means
          busy, `False` means not busy.
        - `health`: signals an device sanity/error condition. Passes two 
          parameters, an integer error code and a string description. The 
          integer error codes are:
          
              - 0 : No error
              - 1 : MINOR, no impact to device functionality.
              - 2 : MARGINAL, no immediate impact. Attention may soon be needed.
              - 4 : SERIOUS, functionality impacted but recovery is possible.
              - 8 : CRITICAL, functionality broken, recovery is not possible.
              - 16 : DISABLED, device has been manually disabled.
              
        - `message`: signal for sending messages from the device to any 
          listeners. Messages are passed as a single string parameter.

    **Dynamic Attributes:**
        - `<signal>_state`: for each signal defined in derived classes, the last
          transmitted data corresponding to the current state can be obtained 
          through the dynamic variable with the suffix "_state" added to the 
          signal name. For example::
         
          >>> obj.active_state
          >>> True
    
    **Dynamic Methods:**
        - `is_<signal>()`: for each boolean signal defined in derived clases, the
          current state can be obtained by adding the prefix "is_" to the signal
          name. For example::
          
          >>> obj.is_active()
          >>> True
    """
    # signals
    __gsignals__ =  { 
        "active": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_BOOLEAN,)),
        "busy": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_BOOLEAN,)),
        "health": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        "message": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_STRING,)),
        }
    
    def __init__(self):
        GObject.GObject.__init__(self)
        self.pending_devs = [] # inactive child devices or process variables
        self.health_manager = HealthManager() # manages the health states
        self.state_info = {'active': False, 'busy': False, 
                             'health': (99,''), 'message': ''}
        self.name = self.__class__.__name__
        self._dev_state_patt = re.compile('^(\w+)_state$')
        self._dev_bool_patt = re.compile('^is_(\w+)$')
        
    def __repr__(self):
        state_txts = []
        for k,v in self.state_info.items():
            state_txts.append(' %12s: %s' % (k, str(v)))
        state_txts.sort()
        txt = "<%s: %s\n%s\n>" % (self.__class__.__name__, self.name, '\n'.join(state_txts))
        return txt
        
    def _check_active(self):
        if len(self.pending_devs) > 0:
            inactive_devs = [dev.name for dev in self.pending_devs]
            msg = '\n\t'.join(inactive_devs)
            #msg = '[%d] inactive children:\n\t%s' % (len(inactive_devs), msg)
            msg = '[%d] inactive children.' % (len(inactive_devs))
            logger.warning( "(%s) %s" % (self.name, msg))
        return True
    
    def do_busy(self, st):
        pass
    
    def do_health(self, st):
        pass
    
    def do_message(self, st):
        pass
    
    def do_active(self, st):
        _k = {True: 'active', False: 'inactive'}
        logger.info( "(%s) is now %s." % (self.name, _k[st]))
        if not st:
            if len(self.pending_devs) > 0:
                inactive_devs = [dev.name for dev in self.pending_devs]
                msg = '[%d] inactive children.' % (len(inactive_devs))
                logger.warning( "(%s) %s" % (self.name, msg))
            
    def is_active(self):
        return self.active_state
    
    def is_busy(self):
        return self.busy_state
    
    def get_state(self):
        """Obtain a copy of the device state.
         
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
        """Set the state of the device and emit the corresponding signal. 
        
        Kwargs:
            Keyworded arguments follow the same conventions as the state 
            dictionary and correspond to any signals defined for the device.
            Signals must be previously defined as supported signals of the device.
            
        For example::
        
            mydevice.set_state(active=True, busy=False, 
                               health=(1, 'error','too hot'),
                               message="the device is overheating")
        """

        for st, val in kwargs.items():
            if st != 'health':
                # only signal a state change if it actually changes for non
                # health signals
                sid = GObject.signal_lookup(st, self)
                if sid == 0: break
                if self.state_info.get(st, None) != val:
                    self.state_info.update({st: val})
                    GObject.idle_add(self.emit, st, val)
                elif val == None:
                    self.state_info.update({st: None})
                    GObject.idle_add(self.emit, st)
            elif st == 'health':
                sev, cntx = val[:2]
                if sev != 0:          
                    self.health_manager.add(*val)
                else:
                    self.health_manager.remove(cntx)
                _health = self.health_manager.get_health()
                if _health[0] == 0 and len(val)==3:  # allows messages to go through for good health
                    _health = (0,  val[2])
                if _health != self.health_state:
                    self.state_info.update({st: _health})
                    GObject.idle_add(self.emit, st, _health)
                
            
    def add_pv(self, *args, **kwargs):
        """Add a process variable (PV) to the device.
        
        Create a new process variable, add it to the device. 
        Keyworded arguments should be the same as those expected for instantiating a
        :class:`mxdc.com.ca.PV` object.

        Returns:
            A reference to the created :class:`mxdc.com.ca.PV` object.
        """

        dev = ca.PV(*args, **kwargs)
        self.pending_devs.append(dev)
        dev.connect('active', self._on_device_active)
        return dev
    
    def add_devices(self, *devices):
        """ Add one or more devices as children of this device. """
        
        for dev in devices:
            self.pending_devs.append(dev)
            dev.connect('active', self._on_device_active)

    def _on_device_active(self, dev, state):
        """I am called every time a device becomes active or inactive.
        I expect to receive a reference to the device and a boolean 
        state flag which is True on connect and False on disconnect. If it is
        a connection, I add the device to the pending device list
        otherwise I remove the device from the list. When ever the list goes to
        zero, I set the group state to active and inactive otherwise.
        """
        
        if state and dev in self.pending_devs:
            self.pending_devs.remove(dev)
        elif not state and dev not in self.pending_devs:
            self.pending_devs.append(dev)
        if len(self.pending_devs) == 0:
            self.set_state(active=True, health=(0, 'active'))
        else:
            self.set_state(active=False, health=(4, 'active', '%d inactive components.' % len(self.pending_devs)))

    def __getattr__(self, key):
        m = self._dev_state_patt.match(key)
        n = self._dev_bool_patt.match(key)
        if m:
            key = m.group(1)
            return self.state_info.get(key, None)
        elif n:
            key = n.group(1)
            val = self.state_info.get(key, None)
            if (val is True) or (val is False):
                def dyn_func(): return val
                return dyn_func
            else:
                raise AttributeError("%s is not a boolean '%s'" % (self.__class__.__name__, key))
        else:
            raise AttributeError("%s has no attribute '%s'" % (self.__class__.__name__, key))
        


class HealthManager(object):
    """Manages the health states. The object enables registration and removal of
    error states and consistent reporting of health based on all currently 
    active health issues.
    """
    
    def __init__(self, **kwargs):
        """Takes key worded arguments. The keyword name is the context, and
        the value is an error string to be returned instead of the context name
        with all health information for the given context. 
        """
        self.msg_dict = kwargs
        self.health_states = set()
    
    def register_messages(self, **kwargs):
        """Update or add entries to the context message register"""
        self.msg_dict.update(kwargs)

        
    def add(self, severity, context, msg=None):
        """Adds an error state of the given context as a string
        and a severity value as a integer. If a message is given, it will be 
        stored and used instead of the context name. Only one message per context
        type is allowed. Use a different context if you want different messages.
        """
        if msg is not None:
            self.msg_dict.update({context: msg})
        self.health_states.add((severity, context))
    
    def remove(self, context):
        """Remove all errors of the given context as a string."""
        err_list = [e for e in self.health_states if e[1] == context]
        for e in err_list:
            self.health_states.remove(e)
    
    def get_health(self):
        """Generate an error code and string based on all the currently registered
        errors within the health registry.
        """
        severity = 0
        msg_list = set()
        for sev, cntx in self.health_states:
            severity = severity | sev
            msg_list.add(self.msg_dict.get(cntx, cntx))
        msg = ' '.join(msg_list)
        return severity, msg
            
            
        
        
