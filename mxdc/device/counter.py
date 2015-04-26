
from mxdc.device.base import BaseDevice
from mxdc.interface.devices import ICounter
from mxdc.utils.log import get_module_logger
from zope.interface import implements
from mxdc.utils import decorators
import numpy
import os
import random
import time


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class Counter(BaseDevice):
    """EPICS based Counter Device objects. Enables counting and averaging of 
    process variables over given time periods.
    """

    implements(ICounter)
    
    def __init__(self, pv_name, zero=0.0):
        """        
        Args:
            pv_name (str): Process Variable name.
        
        Kwargs:
            zero (float):  Zero offset value. Defaults to 0.0;
        
        Returns
            float. The average process variable value during the count time.            
        """
        BaseDevice.__init__(self)
        self.name = pv_name
        self.zero = float(zero)
        self.value = self.add_pv(pv_name)
        self.DESC = self.add_pv('%s.DESC' % pv_name)
        self.DESC.connect('changed', self._on_name_change)
    
    def _on_name_change(self, pv, val):
        if val != '':
            self.name = val
    
    def count(self, t):
        """Count for the specified amount of time and return the numeric value
        corresponding to the average count. This method blocks for the specified 
        time.
        
        Args:
            t (float): averaging time in seconds.
        
        Returns
            float. The average process variable value during the count time.            
        """
        
        if t <= 0.0:
            return self.value.get() - self.zero
            
        _logger.debug('Averaging detector (%s) for %0.2f sec.' % (self.name, t) )
        interval=0.01
        values = []
        time_left = t
        while time_left > 0.0:
            values.append( self.value.get() )
            time.sleep(interval)
            time_left -= interval
        total = (sum(values, 0.0)/len(values)) - self.zero
        _logger.debug('(%s) Returning average of %d values for %0.2f sec.' % (self.name, len(values), t) )
        return total #* (t/interval)
    
    @decorators.async
    def async_count(self, t):
        self.avg_value = self.count(t)
                        


class SimCounter(BaseDevice):
    """Simulated Counter Device objects. Optionally reads from external file.
    """
    
    SIM_COUNTER_DATA = numpy.loadtxt(os.path.join(os.path.dirname(__file__),'data','simcounter.dat'))
    implements(ICounter)
    
    def __init__(self, name, zero=1.0, real=True):
        """        
        Args:
            name (str): Device Name.
        
        Kwargs:
            zero (float):  Zero offset value. Defaults to 1.0;
            real (bool): Whether to read from a file for more realistic values.
        
        Returns
            float. If reading from a file (default), the value loops through and
            cycles back at the end. Otherwise it alwas returns the zero value.            
        """
        
        BaseDevice.__init__(self)
        from mxdc.device.misc import SimPositioner
        self.zero = float(zero)
        self.name = name
        self.real = int(real)
        self.value = SimPositioner('PV', self.zero, '')
        self.set_state(active=True, health=(0,''))
        self._counter_position = random.randrange(0, self.SIM_COUNTER_DATA.shape[0]**2)
        
    def __repr__(self):
        s = "<%s:'%s'>" % (self.__class__.__name__, self.name)
        return s
    
    def count(self, t):
        """Count for the specified amount of time and return the numeric value
        corresponding to the average count. This method blocks for the specified 
        time.
        
        Args:
            t (float): averaging time in seconds.
        
        Returns
            float. The average process variable value during the count time.            
        """
        
        time.sleep(t)
        i,j = divmod(self._counter_position, self.SIM_COUNTER_DATA.shape[0])
        self._counter_position += 1
        if self.real == 1:
            return self.zero
        else:
            return self.SIM_COUNTER_DATA[i,j]

    @decorators.async
    def async_count(self, t):
        self.avg_value = self.count(t)

__all__ = ['Counter', 'SimCounter']
