"""This module defines classes for Optimizers."""

import time
from zope.interface import implements
from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from bcm.device.base import BaseDevice
from bcm.utils.log import get_module_logger
from bcm.engine.interfaces import IOptimizer
from bcm.engine.scanning import AbsScan
from bcm.engine import fitting

import numpy

_logger = get_module_logger(__name__)

class Optimizer(BaseDevice):
    implements(IOptimizer)
    
    def __init__(self, name):
        BaseDevice.__init__(self)
        self.set_state(active=True)
        self.name = name
    
    def start(self):
        pass
    
    def stop(self):
        pass
        
    def wait(self):
        return

SimOptimizer = Optimizer
  
class MostabOptimizer(BaseDevice):
    
    implements(IOptimizer)
    
    def __init__(self, name):
        BaseDevice.__init__(self)
        self._start = self.add_pv('%s:Mostab:opt:cmd' % name)
        self._stop = self.add_pv('%s:abortFlag' % name)
        self._state1 = self.add_pv('%s:optRun'% name)
        self._state2 = self.add_pv('%s:optDone'% name)
        self._status = 0
        self._command_active = False
        self._state1.connect('changed', self._state_change)
        self._state2.connect('changed', self._state_change)
        
        
    def _state_change(self, obj, val):
        if self._state1.get() > 0:
            self._status =  1
            self._command_active = False
        elif self._state2.get() >0:
            self._status = 0
        
    def start(self):
        self._command_active = True
        self._start.put(1)
        
    
    def stop(self):
        self._stop.put(1)
    
    def wait(self):
        poll=0.05
        while self._status == 1 or self._command_active:
            time.sleep(poll)


class PitchOptimizer(BaseDevice):
    """Pitch Optimizer for 08B1-1"""
    implements(IOptimizer)
    
    def __init__(self, pitch_mtr, cntr, min_count=0.0):
        BaseDevice.__init__(self)
        self.name = 'Pitch Optimizer'
        self.pitch = pitch_mtr
        self.counter = cntr
        self.min_count = min_count
        self.add_devices(self.pitch, self.counter)
        self._scan = None
    
    def calc_pitch(self, energy, p=[0.3985341, -0.10101318, 0.01685788, -0.15792546]):
        x = energy
        a = numpy.arcsin(1.97704/x)
        return p[0] + p[1] * numpy.sin(a) + p[2] * numpy.log(a) + p[3] * numpy.cos(a)
    
    def start(self):
        bl = globalRegistry.lookup([], IBeamline)
        if bl is None:
            _logger.warning('Beamline is not available.')
            return 
        elif self.active_state == False:
            _logger.warning('Pitch Optimizer is inactive.')
            return 
        elif self.busy_state == True:
            _logger.warning('Pitch Optimizer is already busy.')
            return 
        elif self.counter.value.get() < self.min_count:
            _logger.warning('Counter is below threshold.')
            return 
        else:
            self.set_state(busy=True)
            energy = bl.energy.get_position()
            _p = self.calc_pitch(energy)
            self._current_pitch = _p
            st_p = _p - 0.002
            en_p = _p + 0.002
            self._scan = AbsScan(self.pitch, st_p, en_p, 20, self.counter, 0.5)
            self._scan.connect('done', self._fit_scan)
            self._scan.start()
            
    def _fit_scan(self, scan):
        data = numpy.array(scan.data)
        xo = data[:, 0]
        yo = data[:,-1]

        params, success = fitting.peak_fit(xo, yo, 'gaussian')
        ymax = params[0]
        fwhm = params[1]
        midp = params[2]
        
        if success:
            self._current_pitch = midp
            self.pitch.move_to(midp)       
            _logger.info('Pitch Optimized. MIDP=%0.4e FWHM=%0.4e YMAX=%0.4e.' % (midp, fwhm, ymax))
        else:
            self.pitch_move_to(self._current_pitch)
            _logger.info('Pitch Optimization failed. Moving to theoretical position %0.4e.' % (self._current_pitch))
        self.set_state(busy=False)
              
    def stop(self):
        if self.active_state and self._scan is not None:
            self._scan.stop()
            self.pitch.move_to(self._current_pitch)
            _logger.info('Pitch Optimization aborded. Moving to theoretical position %0.4e.' % (self._current_pitch))

    def wait(self):
        poll=0.05
        while self.busy_state:
            time.sleep(poll)
            
__all__ = ['MostabOptimizer', 'SimOptimizer', 'PitchOptimizer'] 