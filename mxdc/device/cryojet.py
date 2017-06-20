
from gi.repository import GObject

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


class CryojetBase(BaseDevice):
    """EPICS Based cryojet device object at the CLS."""
    implements(ICryojet)

    temperature = GObject.Property(type=float, default=0.0)
    shield = GObject.Property(type=float, default=0.0)
    sample = GObject.Property(type=float, default=0.0)
    level = GObject.Property(type=float, default=0.0)

    def __init__(self, *args, **kwargs):
        BaseDevice.__init__(self)
        self.name = 'Cryojet'
        self._previous_flow = 7.0
        self.setup(*args, **kwargs)

    def setup(self, *args, **kwargs):
        pass

    def stop_flow(self):
        """Stop the flow of the cold nitrogen stream. The current setting for
        flow rate is saved.
        """
        self._previous_flow = self.sample_fbk.get()
        self.sample_sp.set(0.0)

    def resume_flow(self):
        """Restores the flow rate to the previously saved setting."""
        self.sample_sp.set(self._previous_flow)

    def on_temp(self, obj, val):
        if val < 110:
            self.set_state(health=(0, 'temp'))
        elif val < 115:
            self.set_state(health=(2, 'temp', 'Temp. high!'))
        else:
            self.set_state(health=(4, 'temp', 'Temp. too high!'))
        self.set_property('temperature', val)

    def on_sample(self, obj, val):
        if val > 5:
            self.set_state(health=(0, 'sample'))
        elif val > 4:
            self.set_state(health=(2, 'sample', 'Sample Flow Low!'))
        else:
            self.set_state(health=(4, 'sample', 'Sample Flow Too Low!'))
        self.set_property('sample', val)

    def on_shield(self, obj, val):
        if val > 5:
            self.set_state(health=(0, 'shield'))
        elif val > 4:
            self.set_state(health=(2, 'shield', 'Shield Flow Low!'))
        else:
            self.set_state(health=(4, 'shield', 'Shield Flow Too Low!'))
        self.set_property('shield', val)

    def on_level(self, obj, val):
        if val < 15:
            self.set_state(health=(4, 'cryo', 'Cryogen too low!'))
        elif val < 20:
            self.set_state(health=(2, 'cryo', 'Cryogen low!'))
        else:
            self.set_state(health=(0, 'cryo'))
        self.set_property('level', val)

    def on_nozzle(self, obj, val):
        if val:
            self.set_state(health=(1, 'nozzle', 'Retracted!'))
        else:
            self.set_state(health=(0, 'nozzle', 'Restored'))


class Cryojet(CryojetBase):
    def setup(self, name, level_name, nozzle_name):
        self.temp_fbk = self.add_pv('{}:sensorTemp:get'.format(name))
        self.sample_fbk = self.add_pv('{}:SampleFlow:get'.format(name))
        self.shield_fbk = self.add_pv('{}:ShieldFlow:get'.format(name))
        self.sample_sp = self.add_pv('{}:SampleFlow:set'.format(name))
        self.level_fbk = self.add_pv('{}:ch1LVL:get'.format(level_name))
        self.fill_status = self.add_pv('{}:status:ch1:N.SVAL'.format(level_name))
        self.nozzle = CryojetNozzle(nozzle_name)

        # connect signals for monitoring state
        self.temp_fbk.connect('changed', self.on_temp)
        self.level_fbk.connect('changed', self.on_level)
        self.sample_fbk.connect('changed', self.on_sample)
        self.sample_fbk.connect('changed', self.on_shield)
        self.nozzle.connect('changed', self.on_nozzle)

    def on_level(self, obj, val):
        if val < 150:
            self.set_state(health=(4, 'cryo', 'Cryogen too low!'))
        elif val < 200:
            self.set_state(health=(2, 'cryo', 'Cryogen low!'))
        else:
            self.set_state(health=(0, 'cryo'))
        self.set_property('level', val)

class Cryojet5(CryojetBase):
    def setup(self, name, nozzle_name):
        self.temp_fbk = self.add_pv('{}:SAMPLET:TEMP:FBK'.format(name))
        self.sample_fbk = self.add_pv('{}:SAMPLEF:FLOW:FBK'.format(name))
        self.shield_fbk = self.add_pv('{}:SHIELDF:FLOW:FBK'.format(name))
        self.sample_sp = self.add_pv('{}:SAMPLET:FLOW'.format(name))
        self.level_fbk = self.add_pv('{}:LEVEL:LEVL:FBK'.format(name))
        self.fill_status = self.add_pv('{}:AUTOFILL:STEP'.format(name))
        self.nozzle = CryojetNozzle(nozzle_name)

        # connect signals for monitoring state
        self.temp_fbk.connect('changed', self.on_temp)
        self.level_fbk.connect('changed', self.on_level)
        self.sample_fbk.connect('changed', self.on_sample)
        self.shield_fbk.connect('changed', self.on_shield)
        self.nozzle.connect('changed', self.on_nozzle)


class SimCryojet(CryojetBase):
    def setup(self, *args, **kwargs):
        self.nozzle = misc.SimShutter('Sim Cryo Nozzle')
        self.name = 'Sim Cryojet'


__all__ = ['Cryojet', 'Cryojet5', 'SimCryojet']
