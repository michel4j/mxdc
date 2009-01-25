import time
import math
import logging
from zope.interface import implements
from bcm.device.interfaces import ICollimator, IMotor
from bcm.protocol.ca import PV
from bcm.utils.log import NullHandler

# setup module logger and add default do-nothing handler
_logger = logging.getLogger(__name__).addHandler( NullHandler() )


class CollimatorError(Exception):

    """Base class for errors in the collimator module."""

class Collimator(object):

    implements(misc.IGoniometer)
    
    def __init__(self, width, height):
        # initialize 
        self.width  = IMotor(width)
        self.height = IMotor(height)
                    
    def get_state(self):
        return self.width.get_state() | self.height.get_state()        
                        
    def wait(self):
        self.width.wait()
        self.height.wait()

    def stop(self):
        self.width.stop()
        self.height.stop()

