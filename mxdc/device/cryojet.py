from zope.interface import implements
from mxdc.device.base import BaseDevice
from mxdc.utils.log import get_module_logger
from mxdc.interface.devices import ICryojet
from mxdc.device import misc


_logger = get_module_logger('devices')

class CryojetNozzle(misc.BasicShutter):
    """A specialized in-out actuator for pneumatic Cryojet nozzles at the CLS."""
    def __init__(self, name):
        """
        Args:
            `name` (str): Process variable root name.
        """
        open_name = "%s:opr:open" % name
        close_name = "%s:opr:close" % name
        state_name = "%s:out" % name
        misc.BasicShutter.__init__(self, open_name, close_name, state_name)
        self._messages = ['Restoring', 'Retracting']
        self._name = 'Cryojet Nozzle'

class Cryojet(BaseDevice):
    """EPICS Based cryojet device object at the CLS."""
    
    implements(ICryojet)
    
    def __init__(self, cname, lname, nname=''):
        """
        Args:
            - `cname` (str): Root name for EPICS cryojet record.
            - `lname` (str): root name for EPICS cryojet-level controller record.
        
        Kwargs:
            - `nname` (str): Root name of the EPICS cryojet nozzle record.
        """
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
        self.nozzle = CryojetNozzle(nname)

        self.fill_status = self.add_pv('%s:status:ch1:N.SVAL' % lname)
        self.add_devices(self.temperature, self.sample_flow, self.shield_flow)
        self._previous_flow = 7.0
        
        # connect signals for monitoring state
        self.temperature.connect('changed', self._on_temperature_changed)
        self.level.connect('changed', self._on_level_changed)
        self.nozzle.connect('changed', self._on_noz_change)
        

    def _on_temperature_changed(self, obj, val):
        if val < 110:
            self.set_state(health=(0, 'temp'))
        elif val < 115:
            self.set_state(health=(2, 'temp', 'Temp. high!'))
        else:
            self.set_state(health=(4, 'temp', 'Temp. too high!'))

    def _on_level_changed(self, obj, val):
        if  val < 150:
            self.set_state(health=(4, 'cryo', 'Cryogen too low!'))
        elif val < 200:
            self.set_state(health=(2, 'cryo', 'Cryogen low!'))
        elif val <= 1000:
            self.set_state(health=(0, 'cryo'))
            
    def _on_noz_change(self, obj, val):
        if val:
            self.set_state(health=(1, 'nozzle', 'Retracted!'))
        else:
            self.set_state(health=(0, 'nozzle', 'Restored'))
                       
    def stop_flow(self):
        """Stop the flow of the cold nitrogen stream. The current setting for
        flow rate is saved.
        """
        self._previous_flow = self.sample_flow.get()
        self.sample_flow.set(0.0)

    def resume_flow(self):
        """Restores the flow rate to the previously saved setting."""
        self.sample_flow.set(self._previous_flow)
    

class SimCryojet(BaseDevice):
    """Simulated cryoject device."""
    implements(ICryojet)
    def __init__(self, name):
        """Args:
            name (str): Name of the device.
        """
        BaseDevice.__init__(self)
        self.name = name
        self.temperature = misc.SimPositioner('Cryojet Temperature',
                                        pos=101.2, units='Kelvin')
        self.sample_flow = misc.SimPositioner('Cryojet Sample Flow',
                                         pos=8.0, units='L/min')
        self.shield_flow = misc.SimPositioner('Cryojet Shield Flow',
                                         pos=5.0, units='L/min')
        self.level = misc.SimPositioner('Cryogen Level', pos=90.34, units='%')
        self.fill_status = misc.SimPositioner('Fill Status', pos=1)
        self.nozzle = misc.SimShutter('Cryojet Nozzle Actuator')
        self.set_state(active=True, health=(0,''))

    def stop_flow(self):
        """Stop the flow of the cold nitrogen stream. The current setting for
        flow rate is saved.
        """
        self.sample_flow.set(0.0)

    def resume_flow(self):
        """Restores the flow rate to the previously saved setting."""
        self.sample_flow.set(8.0)

__all__ = ['Cryojet', 'SimCryojet']
