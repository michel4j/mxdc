import time
import math
import logging

from zope.interface import implements
from bcm.device.interfaces import IGoniometer, IMotor
from bcm.protocol.ca import PV
from bcm.utils.log import NullHandler

# setup module logger and add default do-nothing handler
_logger = logging.getLogger(__name__).addHandler( NullHandler() )


class GoniometerError(Exception):

    """Base class for errors in the goniometer module."""

class Goniometer(object):

    implements(misc.IGoniometer)

    def __init__(self, name, omega):
        # initialize process variables
        self._scan_cmd = PV("%s:scanFrame.PROC" % name, monitor=False)
        self._state = PV("%s:scanFrame:status" % name)
        self._shutter_state = PV("%s:outp1:fbk" % name)
        
        self.omega = IMotor(omega)
                
        #parameters
        self._settings = {
            'time' : PV("%s:expTime" % name, monitor=False),
            'delta' : PV("%s:deltaOmega" % name, monitor=False),
            'angle': PV("%s:openSHPos" % name, monitor=False),
        }
        
                
    def configure(self, **kwargs):
        for key in kwargs.keys():
            self._settings[key].put(params[key])
    
    def scan(self):
        self._scan_cmd.put('\x01')

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
        pass    # FIXME: We need a proper way to stop goniometer


