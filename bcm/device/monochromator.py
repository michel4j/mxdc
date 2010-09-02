import time
import sys
import logging
import numpy
import gobject

from zope.interface import implements
from bcm.device.base import BaseDevice
from bcm.device.interfaces import IMonochromator, IMotor
from bcm.engine.interfaces import IOptimizer
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class Monochromator(BaseDevice):
    
    implements(IMonochromator)
    
    def __init__(self, simple_energy, energy, mostab=None):
        BaseDevice.__init__(self)
        self.name = 'Monochromator'
        self.simple_energy = simple_energy
        self.energy = energy
        self.mostab = mostab
        if self.mostab is not None:
            self.add_devices(self.energy, self.simple_energy, self.mostab)
        else:           
            self.add_devices(self.energy, self.simple_energy)
                        
    def wait(self):
        self.energy.wait()
        if self.mostab is not None:
            self.mostab.wait()

    def stop(self):
        self.energy.stop()
        if self.mostab is not None:
            self.mostab.stop()
        