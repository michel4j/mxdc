import time
import math
import logging

from zope.interface import implements
from bcm.device.interfaces import ICounter
from bcm.protocol.ca import PV
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

class CounterError(Exception):

    """Base class for errors in the counter module."""


class Counter(object):

    implements(ICounter)
    
    def __init__(self, pv_name):
        self.name = pv_name     
        self.value = PV(pv_name)
    
    def count(self, t):
        if t <= 0.0:
            return self.value.get()
            
        _logger.debug('Averaging detector (%s) for %0.2f sec.' % (self.name, t) )
        interval=0.01
        values = []
        time_left = t
        while time_left > 0.0:
            values.append( self.value.get() )
            time.sleep(interval)
            time_left -= interval
        total = sum(values, 0.0)/len(values)
        _logger.debug('(%s) Returning average of %d values for %0.2f sec.' % (self.name, len(values), t) )
        return total
                        

