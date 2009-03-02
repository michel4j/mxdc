import time
import logging
import warnings
warnings.simplefilter("ignore")

from zope.interface import implements
from bcm.device.interfaces import IGoniometer
from bcm.protocol.ca import PV
from bcm.device.motor import VMEMotor
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

# Goniometer state constants
(
    GONIO_IDLE,
    GONIO_ACTIVE,
) = range(2)

class GoniometerError(Exception):

    """Base class for errors in the goniometer module."""

class Goniometer(object):

    implements(IGoniometer)

    def __init__(self, name):
        self.name = name
        pv_root = name.split(':')[0]
        # initialize process variables
        self._scan_cmd = PV("%s:scanFrame.PROC" % pv_root, monitor=False)
        self._state = PV("%s:scanFrame:status" % pv_root)
        self._shutter_state = PV("%s:outp1:fbk" % pv_root)
        
        self.omega = VMEMotor('%s:deg' % name)
                
        #parameters
        self._settings = {
            'time' : PV("%s:expTime" % pv_root, monitor=False),
            'delta' : PV("%s:deltaOmega" % pv_root, monitor=False),
            'angle': PV("%s:openSHPos" % pv_root, monitor=False),
        }
        
                
    def configure(self, **kwargs):
        for key in kwargs.keys():
            self._settings[key].put(kwargs[key])
    
    def scan(self, wait=True):
        self._scan_cmd.set('\x01')
        if wait:
            self.wait(start=True, stop=True)

    def get_state(self):
        return self._state.get() != 0   
                        
    def wait(self, start=True, stop=True, poll=0.01, timeout=20):
        if (start):
            time_left = 2
            while not self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
        if (stop):
            time_left = timeout
            while self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll

    def stop(self):
        pass    # FIXME: We need a proper way to stop goniometer scan


class MD2Goniometer(object):

    implements(IGoniometer)

    def __init__(self, name):
        self.name = name
        pv_root = name
        # initialize process variables
        self._scan_cmd = PV("%s:S:StartScan" % pv_root, monitor=False)
        self._abort_cmd = PV("%s:S:AbortScan" % pv_root, monitor=False)
        self._state = PV("%s:G:MachAppState" % pv_root)
        self._shutter_state = PV("%s:G:ShutterIsOpen" % pv_root)
        self._log = PV('%s:G:StatusMsg' % pv_root)
        
        self.omega = VMEMotor('%s:G:OmegaPosn' % pv_root)
                
        #parameters
        self._settings = {
            'time' : PV("%s:S:ScanExposureTime" % pv_root, monitor=False),
            'delta' : PV("%s:S:ScanRange" % pv_root, monitor=False),
            'angle': PV("%s:S:ScanStartAngle" % pv_root, monitor=False),
            'passes': PV("%s:S:ScanNumOfPasses" % pv_root, monitor=False),
        }
                       
    def configure(self, **kwargs):
        for key in kwargs.keys():
            self._settings[key].put(kwargs[key])
    
    def scan(self):
        self._scan_cmd.set(1)

    def get_state(self):
        return self._state.get() != 3  
                        
    def wait(self, start=True, stop=True, poll=0.01, timeout=20):
        if (start):
            time_left = 2
            while not self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
        if (stop):
            time_left = timeout
            while self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll

    def stop(self):
        self._abort_cmd.set(1)

