
import random
import time

import numpy
from zope.interface import implementer

from mxdc import Signal, Device
from mxdc.utils import decorators
from mxdc.utils.log import get_module_logger
from .interfaces import ICounter

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


@implementer(ICounter)
class BaseCounter(Device):
    """
    Base class for all counter devices

    Signals:
        changed: arg_types=(object,), value has changed
        count: arg_types=(float,), result of asynchronous
    """

    class Signals:
        changed = Signal("changed", arg_types=(object,))
        count = Signal("count", arg_types=(float,))

    def count(self, t):
        """
        Averaging of the value for the specified amount of time. Blocks while counting

        :param t: total time to count
        :return: average accumulated value
        """
        raise NotImplementedError('Subclasses must implement this method')

    def start(self):
        """
        Start counting as fast as possible until stopped. Values should be emitted as the count signal
        """

    def stop(self):
        """
        Stop fast counting
        """

    @decorators.async_call
    def count_async(self, t):
        """
        Non-blocking averaging of the value for the specified amount of time. The result of the count
        will be available in the "average_count" attribute

        :param t: total time to count
        """
        self.set_state(count=self.count(t))


class Counter(BaseCounter):
    """
    EPICS based Counter Device objects. Enables counting and averaging of
    process variables over given time periods.

    :param pv_name: process variable name
    :param zero:   zero offset value.
    """

    def __init__(self, pv_name, zero=0.0):
        super().__init__()
        self.name = pv_name
        self.zero = float(zero)
        self.stopped = True

        self.value = self.add_pv(pv_name)
        self.descr = self.add_pv('%s.DESC' % pv_name)

        self.value.connect('changed', self.on_value)
        self.descr.connect('changed', self.on_description)
    
    def on_description(self, pv, val):
        if val != '':
            self.name = val

    def on_value(self, pv, val):
        self.set_state(changed=val)
    
    def count(self, t):
        if t <= 0.0:
            return self.value.get() - self.zero
            
        logger.debug('Averaging detector (%s) for %0.2f sec.' % (self.name, t) )
        interval=0.01
        values = []
        time_left = t
        while time_left > 0.0:
            values.append( self.value.get() )
            time.sleep(interval)
            time_left -= interval
        total = (sum(values, 0.0)/len(values)) - self.zero
        logger.debug('(%s) Returning average of %d values for %0.2f sec.' % (self.name, len(values), t) )
        self.set_state(count=total)
        return total

    @decorators.async_call
    def start(self):
        self.stopped = False
        while not self.stopped:
            val = self.value.get()
            self.set_state(count=val)
            time.sleep(.01)  # 10 ms

    def stop(self):
        self.stopped = True


def gen_sim_data():
    x = y = numpy.linspace(-3.0, 3.0, 100)
    X, Y = numpy.meshgrid(x, y)
    Z1 = numpy.exp(-X ** 2 - Y ** 2)
    Z2 = numpy.exp(-(X - 1) ** 2 - (Y - 1) ** 2)
    Z = (Z1 - Z2) * 2
    return Z


class SimCounter(BaseCounter):
    """
    Simulated Counter Device objects. Optionally reads from external file.
    """

    SIM_COUNTER_DATA = gen_sim_data()

    def __init__(self, name, zero=12345):
        super().__init__()
        from mxdc.devices.misc import SimPositioner
        self.zero = float(zero)
        self.name = name
        self.stopped = True
        self.value = SimPositioner('PV', self.zero, '', noise=2)
        self.set_state(active=True, health=(0, '', ''))
        self.value.connect('changed', self.on_value)
        self.counter_position = random.randrange(0, self.SIM_COUNTER_DATA.shape[0] ** 2)
        self.prev_value = self.zero

    def fetch_value(self):
        i, j = divmod(self.counter_position, self.SIM_COUNTER_DATA.shape[0])
        i %= self.SIM_COUNTER_DATA.shape[0]
        self.counter_position += 1
        value = self.SIM_COUNTER_DATA[i,j] * (1-random.random()*0.02)  # 2% noise
        self.prev_value = value
        return value

    def count(self, t):
        time.sleep(t)
        value = self.fetch_value()
        self.set_state(count=value)
        return value

    @decorators.async_call
    def start(self):
        self.stopped = False
        while not self.stopped:
            val = self.value.get()
            self.set_state(count=val)
            time.sleep(.01)  # 10 ms

    def stop(self):
        self.stopped = True

    def on_value(self, obj, val):
        self.set_state(changed=val)


__all__ = ['BaseCounter', 'Counter', 'SimCounter']
