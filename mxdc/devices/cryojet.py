from enum import Enum
from gi.repository import GObject
from zope.interface import implementer

import mxdc.devices.shutter
from mxdc.devices import misc
from mxdc import Device, Signal, Property
from mxdc.utils.log import get_module_logger

from .interfaces import ICryostat

logger = get_module_logger(__name__)


class CryoJetNozzle(mxdc.devices.shutter.EPICSShutter):
    """
    A specialized in-out actuator for pneumatic Cryojet nozzles.

    :param name: The process variable name of the devices
    """

    def __init__(self, name):
        open_name = "%s:opr:open" % name
        close_name = "%s:opr:close" % name
        state_name = "%s:out" % name
        mxdc.devices.shutter.EPICSShutter.__init__(self, open_name, close_name, state_name)
        self._messages = ['Restoring', 'Retracting']
        self._name = 'Cryojet Nozzle'


@implementer(ICryostat)
class CryostatBase(Device):
    """
    Base class for all cryostat devices.  A cryostat maintains low temperatures at the sample position.

    Signals:
        - temp (float,): Sample temperature
        - level (float,): Cryogen level
        - sample (float,): Cryogen flow-rate
        - shield (float,): Shield flow-rate
    """

    class Positions(Enum):
        IN, OUT = range(2)

    class Signals:
        temp = Signal('temp', arg_types=(float,))
        level = Signal('level', arg_types=(float,))
        sample = Signal('sample', arg_types=(float,))
        shield = Signal('shield', arg_types=(float,))
        pos = Signal('position', arg_types=(object,))

    # Properties
    temperature = Property(type=float, default=0.0)
    shield = Property(type=float, default=0.0)
    sample = Property(type=float, default=0.0)
    level = Property(type=float, default=0.0)

    def configure(self, temp=None, sample=None, shield=None, position=None):
        """
        Configure the Cryostat.

        :param temp: Set the target sample temperature
        :param sample: Set the sample flow rate
        :param shield: Set the shield flow rate
        :param position: If the cryostat set the position. Should be one of Positions.IN, Positions.OUT
        """

    def stop(self):
        """
        Stop the cryostat
        """

    def start(self):
        """
        Start the cryostat
        """



@implementer(ICryostat)
class CryoJetBase(Device):
    """
    Cryogenic Nozzle Jet Device

    """

    temperature = Property(type=float, default=0.0)
    shield = Property(type=float, default=0.0)
    sample = Property(type=float, default=0.0)
    level = Property(type=float, default=0.0)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.name = 'Cryojet'
        self._previous_flow = 7.0
        self.setup(*args, **kwargs)

    def setup(self, *args, **kwargs):
        pass

    def stop_flow(self):
        """
        Stop the flow of the cold nitrogen stream. The current setting for
        flow rate is saved.
        """
        self._previous_flow = self.sample_fbk.get()
        self.sample_sp.put(0.0)

    def resume_flow(self):
        """
        Restores the flow rate to the previously saved setting.
        """
        self.sample_sp.put(self._previous_flow)

    def on_temp(self, obj, val):
        if val < 110:
            self.set_state(health=(0, 'temp', ''))
        elif val < 115:
            self.set_state(health=(2, 'temp', 'Temp. high!'))
        else:
            self.set_state(health=(4, 'temp', 'Temp. too high!'))
        self.set_property('temperature', val)

    def on_sample(self, obj, val):
        if val > 5:
            self.set_state(health=(0, 'sample', ''))
        elif val > 4:
            self.set_state(health=(2, 'sample', 'Sample Flow Low!'))
        else:
            self.set_state(health=(4, 'sample','Sample Flow Too Low!'))
        self.set_property('sample', val)

    def on_shield(self, obj, val):
        if val > 5:
            self.set_state(health=(0, 'shield', ''))
        elif val > 4:
            self.set_state(health=(2, 'shield','Shield Flow Low!'))
        else:
            self.set_state(health=(4, 'shield','Shield Flow Too Low!'))
        self.set_property('shield', val)

    def on_level(self, obj, val):
        if val < 15:
            self.set_state(health=(4, 'cryo','Cryogen too low!'))
        elif val < 20:
            self.set_state(health=(2, 'cryo','Cryogen low!'))
        else:
            self.set_state(health=(0, 'cryo', ''))

        self.set_property('level', val)

    def on_nozzle(self, obj, val):
        if val:
            self.set_state(health=(1, 'nozzle', 'Retracted!'))
        else:
            self.set_state(health=(0, 'nozzle', 'Restored'))


class CryoJet(CryoJetBase):
    def setup(self, name, level_name, nozzle_name):
        self.temp_fbk = self.add_pv('{}:sensorTemp:get'.format(name))
        self.sample_fbk = self.add_pv('{}:SampleFlow:get'.format(name))
        self.shield_fbk = self.add_pv('{}:ShieldFlow:get'.format(name))
        self.sample_sp = self.add_pv('{}:sampleFlow:set'.format(name))
        self.level_fbk = self.add_pv('{}:ch1LVL:get'.format(level_name))
        self.fill_status = self.add_pv('{}:status:ch1:N.SVAL'.format(level_name))
        self.nozzle = CryoJetNozzle(nozzle_name)

        # connect signals for monitoring state
        self.temp_fbk.connect('changed', self.on_temp)
        self.level_fbk.connect('changed', self.on_level)
        self.sample_fbk.connect('changed', self.on_sample)
        self.sample_fbk.connect('changed', self.on_shield)
        self.nozzle.connect('changed', self.on_nozzle)

    def on_level(self, obj, val):
        if val < 150:
            self.set_state(health=(4, 'cryo','Cryogen too low!'))
        elif val < 200:
            self.set_state(health=(2, 'cryo','Cryogen low!'))
        else:
            self.set_state(health=(0, 'cryo', ''))
        self.set_property('level', val/10.)


class CryoJet5(CryoJetBase):
    def setup(self, name, nozzle_name):
        self.temp_fbk = self.add_pv('{}:sample:temp:fbk'.format(name))
        self.sample_fbk = self.add_pv('{}:sample:flow:fbk'.format(name))
        self.shield_fbk = self.add_pv('{}:shield:flow:fbk'.format(name))
        self.sample_sp = self.add_pv('{}:sample:flow'.format(name))
        self.level_fbk = self.add_pv('{}:autofill:level:fbk'.format(name))
        self.fill_status = self.add_pv('{}:autofill:state'.format(name))
        self.nozzle = CryoJetNozzle(nozzle_name)

        # connect signals for monitoring state
        self.temp_fbk.connect('changed', self.on_temp)
        self.level_fbk.connect('changed', self.on_level)
        self.sample_fbk.connect('changed', self.on_sample)
        self.shield_fbk.connect('changed', self.on_shield)
        self.nozzle.connect('changed', self.on_nozzle)


class SimCryoJet(CryoJetBase):
    def setup(self, *args, **kwargs):
        self.nozzle = mxdc.devices.shutter.SimShutter('Sim Cryo Nozzle')

        self.temp_fbk = misc.SimPositioner('Cryo Temperature', pos=102.5, noise=3)
        self.sample_fbk = misc.SimPositioner('Cryo Sample flow', pos=6.5, noise=1)
        self.shield_fbk = misc.SimPositioner('Cryo Shield flow', pos=9.5, noise=1)
        self.level_fbk = misc.SimPositioner('Cryo Level', pos=35.5, noise=10)

        self.name = 'Sim CryoJet'
        # connect signals for monitoring state
        self.temp_fbk.connect('changed', self.on_temp)
        self.level_fbk.connect('changed', self.on_level)
        self.sample_fbk.connect('changed', self.on_sample)
        self.shield_fbk.connect('changed', self.on_shield)
        self.nozzle.connect('changed', self.on_nozzle)


    def _simulate_nozzle(self, *args, **kwargs):
        if self.nozzle.is_open():
            self.nozzle.close()
        else:
            self.nozzle.open()
        return True

    def stop_flow(self):
        """
        Stop the flow of the cold nitrogen stream. The current setting for
        flow rate is saved.
        """
        self._previous_flow = self.sample_fbk.get()
        self.sample_fbk.put(0.0)

    def resume_flow(self):
        """
        Restores the flow rate to the previously saved setting.
        """
        self.sample_fbk.put(self._previous_flow)


__all__ = ['CryoJet', 'CryoJet5', 'SimCryoJet']
