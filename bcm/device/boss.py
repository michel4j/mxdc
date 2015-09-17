from bcm.device.base import BaseDevice
from bcm.device.interfaces import IOptimizer
from bcm.utils.log import get_module_logger
from zope.interface import implements
import time


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

class Optimizer(BaseDevice):
    implements(IOptimizer)
    
    def __init__(self, name):
        BaseDevice.__init__(self)
        self.set_state(active=True)
        self.name = name
    
    def pause(self):
        pass
    
    def resume(self):
        pass
    
    def start(self):
        pass
    
    def stop(self):
        pass
        
    def wait(self):
        return

SimOptimizer = Optimizer
  
class BossPIDController(BaseDevice):
    implements(IOptimizer)
    
    def __init__(self, name, energy):
        BaseDevice.__init__(self)
        self.name = name
        self._enable = self.add_pv('%s:EnableDacOUT' % name)
        self._status = self.add_pv('%s:EnableDacIN' % name)
        self._beam_off = self.add_pv('%s:OffIntOUT' % name)
        self._status.connect('changed', self._state_change)
        self._off_value = 5000
        self._pause_value = 100000000
        self._energy = self.add_pv(energy)
        
        
    def _state_change(self, obj, val):
        self.set_state(busy=(val==1))
        
    def pause(self):
        _logger.debug('Pausing Beam Stabilization')
        if self.active_state and self._status.get() == 1 and self._beam_off.get() != self._pause_value:
            self._off_value = self._beam_off.get()
            self._beam_off.set(self._pause_value)

    def resume(self):
        _logger.debug('Resuming Beam Stabilization')
        if self.active_state:
            self._beam_off.set(self._off_value)
                
    def start(self):
        _logger.debug('Enabling Beam Stabilization')
        if self.active_state:
            self._enable.put(1)
        
    def stop(self):
        _logger.debug('Disabling Beam Stabilization')
        if self.active_state:
            self._enable.put(0)
    
    def wait(self):
        return
        
class MostabPIDController(BaseDevice):
    
    implements(IOptimizer)
    
    def __init__(self, name):
        BaseDevice.__init__(self)
        self.name = name
        self._start = self.add_pv('%s:Mostab:opt:cmd' % name)
        self._stop = self.add_pv('%s:abortFlag' % name)
        self._state = self.add_pv('%s:Mostab:opt:sts'% name)
        self._enabled = self.add_pv('%s:Mostab:opt:enabled'% name)
        self._command_active = False
        self._state.connect('changed', self._state_change)
        self._enabled.connect('changed', self._on_enable)
        
        
    def _state_change(self, obj, val):
        if val == 1:
            self.set_state(busy=True)
        else:
            self._command_active = False
            self.set_state(busy=False)
    
    def _on_enable(self, obj, val):
        if val == 0:
            self.set_state(health=(16, 'srcheck', "No Beam"))
        else:
            self.set_state(health=(0, 'srcheck'))
        
    def start(self):
        if self.health_state[0] == 0:
            self._command_active = True
            self._start.put(1)
        else:
            _logger.warning('Not enough beam to optimize.')
        
    
    def stop(self):
        self._stop.put(1)
    
    def wait(self):
        poll=0.05
        while self.busy_state or self._command_active:
            time.sleep(poll)

__all__ = ['BossPIDController', 'MostabPIDController', 'SimOptimizer']
        