'''Basic Beamline device

This module defines functions and classes for basic beamline devices which
implement generic housekeeping required by all devices.

'''

import gobject
from bcm.protocol import ca
from bcm.utils.log import get_module_logger

logger = get_module_logger(__name__)

class BaseDevice(gobject.GObject):
    """A generic device object class.
        
    All devices should be derived from this class. Objects of this class are instances of
    ``gobject.GObject``. Objects have the following additional ``signals`` defined.
    
    Signals:
    --------
    
        - ``active``: emitted when the state of the device changes from inactive to active
           and vice-versa. Passes a single boolean value as a parameter. ``True`` represents
           a change from inactive to active, and ``False`` represents the opposite.
        - ``busy``: emitted to notify listeners of a change in the busy state of the device.
          A single boolean parameter is passed along with the signal. ``True`` means busy,
          ``False`` means not busy.
        - ``error``: signals an error condition. Passes two parameters, an integer error code
          and a string description. The integer error codes are the following:
              - 0 : No error
              - 1 : MINOR, no impact to device functionality. No attention needed.
              - 2 : MARGINAL, no immediate impact to device functionality but may impact future
                functionality. Attention may soon be needed.
              - 3 : SERIOUS, functionality impacted but recovery is possible. Attention needed.
              - 4 : CRITICAL, functionality broken, recovery is not possible. Attention needed.
        - ``message``: signal for sending messages from the device to any listeners. Messages are
          passed as a single string parameter.
        
    """
    # signals
    __gsignals__ =  { 
        "active": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "busy": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "error": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_INT, gobject.TYPE_STRING)),
        "message": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
        }
    
    def __init__(self):
        gobject.GObject.__init__(self)
        self.pending_devs = [] # used for EPICS devices and device groups
        self.device_state = {'active': False, 'busy': False, 
                             'error': (0,''), 'message': ''}
        self.name = 'No Name Device'

    def do_active(self, st):
        _k = {True: 'active', False: 'inactive'}
        logger.info( "(%s) is now %s." % (self.name, _k[st]))


    def get_state(self):
        """ Returns the state of the device as a dictionary. The entries of the
        state dictionary are:
        
            - ``active`` : Boolean
            - ``busy``: Boolean
            - ``error``: tuple(int, string)
            - ``message``: string
        
        """
        return self.device_state.copy()
    
    def set_state(self, **kwargs):
        """ Set the state of the device based on the specified keyworded arguments.
        Also emits the state signals in the process . Keyworded arguments follow 
        the same conventions as the state dictionary and the following are recognized:
                
            - ``active`` : Boolean
            - ``busy``: Boolean
            - ``error``: tuple(int, string)
            - ``message``: string
        
        Signals will be emitted only for the specified keyworded arguments.
        """
        for st, val in kwargs.items():
            if st in ['active','busy','message']:
                # only signal a state change if it actually changes
                if self.device_state[st] != val:
                    self.device_state[st] = val
                    gobject.idle_add(self.emit, st, val)
            elif st == 'error':
                self.device_state[st] = val
                gobject.idle_add(self.emit, st, val[0], val[1])
            
    def add_pv(self, *args, **kwargs):
        """ Add a process variable (PV) to the device and return its reference. 
        Keeps track of added PVs. Keyworded 
        arguments should be the same as those expected for instantiating a
        ``bcm.protocol.ca.PV`` object.
        
        This method also connects the PVs 'active' signal to the ``on_pv_active`` method.
        """

        pv = ca.PV(*args, **kwargs)
        self.pending_devs.append(pv.name)
        pv.connect('active', self.on_pv_active)
        return pv
    

    def on_pv_active(self, pv, state):
        """I am called every time a process variable connects or disconnects.
        I expect to receive a reference to the process variable and a boolean 
        state flag which is True on connect and False on disconnect. If it is
        a connection, I add the process variable name to the pending pvs list
        otherwise I remove the name from the list. When ever the list goes to
        zero, I set the device state to active and inactive otherwise.
        """
        
        if state and pv.name in self.pending_devs:
            self.pending_devs.remove(pv.name)
        elif not state and pv.name not in self.pending_devs:
            self.pending_devs.append(pv.name)
        
        if len(self.pending_devs) == 0:
            self.set_state(active=True)
        else:
            #print self.pending_devs
            self.set_state(active=False)


class BaseDeviceGroup(BaseDevice):
    """A generic device container for convenient grouping of multiple devices, with 
    a single state reflecting combined states of individual devices."""

    def add_devices(self, *args):
        """ Add one or more devices to the device and return its reference. 
                
        This method also connects the devices' 'active' signal to the ``on_device_active`` method.
        """
        
        for dev in args:
            self.pending_devs.append(dev)
            dev.connect('active', self.on_device_active)

    def on_device_active(self, dev, state):
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
            self.set_state(active=True)
        else:
            #print self.pending_devs
            self.set_state(active=False)

