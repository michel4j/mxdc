import time
import sys
import logging
import numpy
import gobject

from zope.interface import implements
from bcm.device.interfaces import IMonochromator, IMotor, IOptimizer
from bcm.protocol import ca
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class MonochromatorError(Exception):

    """Base class for errors."""
            
     
class Monochromator(object):
    
    implements(IMonochromator)
    
    def __init__(self, simple_energy, energy, mostab):
        self.simple_energy = IMotor(simple_energy)
        self.energy = IMotor(energy)
        self.mostab = IOptimizer(mostab)

    def get_state(self):
        return (self.simple_energy.get_state() | 
                self.energy.get_state() |
                self.mostab.get_state()
                )
                        
    def wait(self):
        self.energy.wait()
        self.mostab.wait()

    def stop(self):
        self.energy.stop()
        self.mostab.stop()
        