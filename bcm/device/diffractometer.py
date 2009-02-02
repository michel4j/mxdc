import logging
from zope.interface import implements
from bcm.device.interfaces import IDiffractometer, IMotor
from bcm.protocol.ca import PV
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class DiffractometerError(Exception):

    """Base class for errors in the diffractometer module."""

class Diffractometer(object):

    implements(IDiffractometer)
    
    def __init__(self, name, distance, two_theta):
        self.name = name
        self.distance  = distance
        self.two_theta = two_theta
                    
    def get_state(self):
        return self.distance.get_state() | self.two_theta.get_state()        
                        
    def wait(self):
        self.distance.wait()
        self.two_theta.wait()

    def stop(self):
        self.distance.stop()
        self.two_theta.stop()

