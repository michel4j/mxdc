import logging
from zope.interface import implements
from bcm.device.interfaces import ICollimator, IMotor
from bcm.protocol.ca import PV
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class CollimatorError(Exception):

    """Base class for errors in the collimator module."""

class Collimator(object):

    implements(misc.IGoniometer)
    
    def __init__(self, name, width, height):
        self.name = name
        self.width  = width
        self.height = height
                    
    def get_state(self):
        return self.width.get_state() | self.height.get_state()        
                        
    def wait(self):
        self.width.wait()
        self.height.wait()

    def stop(self):
        self.width.stop()
        self.height.stop()

