"""This module defines classes for Optimizers."""

import time
from zope.interface import implements
from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from bcm.device.base import BaseDevice
from bcm.utils.log import get_module_logger
from bcm.device.interfaces import IOptimizer
from bcm.engine.scanning import RelScan
from bcm.engine import fitting

import numpy
import gobject

_logger = get_module_logger(__name__)


class PitchOptimizer(BaseDevice):
    """Pitch Optimizer for 08B1-1"""
    implements(IOptimizer)
    
    def __init__(self, name, pitch_func, min_count=0.0):
        BaseDevice.__init__(self)
        self.name = name
        self.min_count = min_count
        self._scan = None
        self.set_state(active=True)
        self.pitch_func = pitch_func
    

    def start(self):
        bl = globalRegistry.lookup([], IBeamline)
        if bl is None:
            _logger.warning('Beamline is not available.')
            return 
        elif self.busy_state == True:
            _logger.warning('Pitch Optimizer is already busy.')
            return 
        self.pitch = bl.dcm_pitch
        self.counter = bl.i_0
        self._current_pitch = self.pitch.get_position()
        #energy = bl.energy.get_position()
        #self.pitch.move_to(self.pitch_func(energy))

        if self.counter.value.get() < self.min_count:
            _logger.warning('Counter is below threshold.')
            return 
        else:
            #self.set_state(busy=True)
            #_p = self.pitch_func(energy)
            #self._current_pitch = _p
            #st_p = _p - 0.002
            #en_p = _p + 0.002
            self._scan = RelScan(self.pitch, -0.002, 0.002, 20, self.counter, 0.5)
            self._scan.connect('done', self._fit_scan, bl)
            if 'boss' in bl.registry:
                bl.boss.pause()
            
            self._scan.start()
            
    def _fit_scan(self, scan, bl):
        data = numpy.array(scan.data)
        xo = data[:, 0]
        yo = data[:,-1]
        if 'boss' in bl.registry:
            bl.boss.resume()

        params, success = fitting.peak_fit(xo, yo, 'gaussian')
        ymax = params[0]
        fwhm = params[1]
        midp = params[2]
        
        if success:
            self._current_pitch = midp
            self.pitch.move_to(midp)       
            _logger.info('Pitch Optimized. MIDP=%0.4e FWHM=%0.4e YMAX=%0.4e.' % (midp, fwhm, ymax))
        else:
            self.pitch.move_to(self._current_pitch)
            _logger.info('Pitch Optimization failed. Moving to theoretical position %0.4e.' % (self._current_pitch))
        self.set_state(busy=False)
              
    def stop(self):
        if self.active_state and self._scan is not None:
            self._scan.stop()
            self.pitch.move_to(self._current_pitch)
            _logger.info('Pitch Optimization aborted. Moving to theoretical position %0.4e.' % (self._current_pitch))

    def pause(self):
        if self.active_state and self._scan is not None:
            self._scan.pause(True)

    def resume(self):
        if self.active_state and self._scan is not None:
            self._scan.pause(False)

    def wait(self):
        poll=0.05
        while self.busy_state:
            time.sleep(poll)

class SimOptimizer(BaseDevice):
    """Pitch Optimizer for 08B1-1"""
    implements(IOptimizer)
    
    def __init__(self, name):
        BaseDevice.__init__(self)
        self.name = name
        self.set_state(active=True)
    

    def start(self):
        self.set_state(busy=True)
        gobject.timeout_add(2000, self._not_busy)            

    def _not_busy(self):
        self.set_state(busy=False)
              
    def stop(self):
        pass
    def pause(self):
        pass

    def resume(self):
        pass

    def wait(self):
        poll=0.05
        while self.busy_state:
            time.sleep(poll)
            
__all__ = ['PitchOptimizer', 'SimOptimizer']
