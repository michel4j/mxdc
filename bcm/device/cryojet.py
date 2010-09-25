'''
Created on Sep 7, 2010

@author: michel
'''

from zope.interface import implements
from bcm.device.base import BaseDevice
from bcm.utils.log import get_module_logger
from bcm.device.interfaces import ICryojet, IShutter
from bcm.device import misc


_logger = get_module_logger('devices')

class CryojetNozzle(misc.BasicShutter):
    def __init__(self, name):
        open_name = "%s:opr:open" % name
        close_name = "%s:opr:close" % name
        state_name = "%s:in" % name
        misc.BasicShutter.__init__(self, open_name, close_name, state_name)
        self._messages = ['Retracting', 'Restoring']
        self._name = 'Cryojet Nozzle'

class Cryojet(BaseDevice):
    
    implements(ICryojet)
    
    def __init__(self, cname, lname, nozzle_motor=None):
        BaseDevice.__init__(self)
        self.name = 'Cryojet'
        self.temperature = misc.Positioner('%s:sensorTemp:get' % cname,
                                      '%s:sensorTemp:get' % cname,
                                      units='Kelvin')
        self.sample_flow = misc.Positioner('%s:sampleFlow:set' % cname,
                                      '%s:SampleFlow:get' % cname,
                                      units='L/min')
        self.shield_flow = misc.Positioner('%s:shieldFlow:set' % cname,
                                      '%s:ShieldFlow:get' % cname,
                                      units='L/min')
        self.level = self.add_pv('%s:ch1LVL:get' % lname)
        
        
        #FIXME: This is ugly, should not hardcode pv name in class definition
        if nozzle_motor is not None:
            self.nozzle = IShutter(nozzle_motor)
        else:
            self.nozzle = CryojetNozzle('CSC1608-5-B10-01')
        self.fill_status = self.add_pv('%s:status:ch1:N.SVAL' % lname)
        self.add_devices(self.temperature, self.sample_flow, self.shield_flow)
        self._previous_flow = 7.0
        
        # connect signals for monitoring state
        self.temperature.connect('changed', self._on_temperature_changed)
        self.level.connect('changed', self._on_level_changed)
    
    def _on_temperature_changed(self, obj, val):
        if val >= 105.0:
            self.set_state(health=(4, 'temp', 'temperature high'))
        else:
            self.set_state(health=(0, 'temp'))

    def _on_level_changed(self, obj, val):
        if val >= 250:
            self.set_state(health=(0, 'cryo'))
        else:
            self.set_state(health=(2, 'cryo', 'cryo low'))
                
    def resume_flow(self):
        self.sample_flow.set(self._previous_flow)
    
    def stop_flow(self):
        self._previous_flow = self.sample_flow.get()
        self.sample_flow.set(0.0)

class SimCryojet(BaseDevice):
    implements(ICryojet)
    def __init__(self, name):
        BaseDevice.__init__(self)
        self.name = name
        self.temperature = misc.SimPositioner('Cryojet Temperature',
                                        pos=101.2, units='Kelvin')
        self.sample_flow = misc.SimPositioner('Cryojet Sample Flow',
                                         pos=8.0,  units='L/min')
        self.shield_flow = misc.SimPositioner('Cryojet Shield Flow',
                                         pos=5.0,  units='L/min')
        self.level = misc.SimPositioner('Cryogen Level', pos=90.34, units='%')
        self.fill_status = misc.SimPositioner('Fill Status', pos=1)
        self.nozzle = misc.SimShutter('Cryojet Nozzle Actuator')

    def stop_flow(self):
        self.sample_flow.set(0.0)

    def resume_flow(self):
        self.sample_flow.set(8.0)

__all__ = ['Cryojet', 'SimCryojet']