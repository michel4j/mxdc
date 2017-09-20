from gi.repository import GObject
from mxdc.device.base import BaseDevice
from mxdc.utils.log import get_module_logger
from zope.interface import implements
from zope.interface import Interface, Attribute, invariant
import random
import math
# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class IBeamTuner(Interface):
    """A Beam Tuner object."""

    tunable = Attribute('True or False, determines if the tuning is allowed or not')

    def tune_up(self):
        """Adjust up"""

    def tune_down(self):
        """Adjust down"""

    def get_value(self):
        """Get value"""

    def reset(self):
        """Reset Tuner."""

    def pause(self):
        """Pause tuner"""

    def resume(self):
        """Resume Tuner"""

    def start(self):
        """Start Tuner"""

    def stop(self):
        """Stop Tuner"""

class BaseTuner(BaseDevice):
    implements(IBeamTuner)
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "percent": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
    }

    def __init__(self):
        super(BaseTuner, self).__init__()
        self.tunable = False

    def tune_up(self):
        pass

    def tune_down(self):
        pass

    def get_value(self):
        return 0.0

    def reset(self):
        pass

    def pause(self):
       pass

    def resume(self):
        pass

    def start(self):
        pass

    def stop(self):
        pass


class BOSSTuner(BaseTuner):
    def __init__(self, name, reference=None, off_value=5000, pause_value=1e8):
        BaseTuner.__init__(self)
        self.name = name
        self.enable_cmd = self.add_pv('{}:EnableDacOUT'.format(name))
        self.enabled_fbk = self.add_pv('{}:EnableDacIN'.format(name))
        self.beam_threshold = self.add_pv('{}:OffIntOUT'.format(name))
        self.value_fbk = self.add_pv('{}:PA_IntRAW'.format(name))
        self.enabled_fbk.connect('changed', self.on_state_changed)
        self.value_fbk.connect('changed', self.on_value_changed)
        if reference:
            self.reference_fbk = self.add_pv(reference)
        else:
            self.reference_fbk = self.value_fbk
        self._off_value = off_value
        self._pause_value = pause_value


    def reset(self):
        self.stop()
        self.start()

    def get_value(self):
        return self.value_fbk.get()

    def pause(self):
        logger.debug('Pausing BOSS')
        if self.active_state and self.enabled_state and self.beam_threshold.get() != self._pause_value:
            self._off_value = self.beam_threshold.get()
            self.beam_threshold.set(self._pause_value)

    def resume(self):
        logger.debug('Resuming BOSS')
        if self.active_state:
            self.beam_threshold.set(self._off_value)

    def start(self):
        logger.debug('Enabling BOSS')
        if self.active_state:
            self.enable_cmd.put(1)

    def stop(self):
        logger.debug('Disabling Beam Stabilization')
        if self.active_state:
            self.enable_cmd.put(0)

    def on_state_changed(self, obj, val):
        self.set_state(enabled=(val==1))

    def on_value_changed(self, obj, val):
        ref = self.reference_fbk.get()
        perc = 0.0 if ref != 0 else 100.0 * val/ref
        self.set_state(changed=val, percent=perc)


class MOSTABTuner(BaseTuner):
    def __init__(self, name, picoameter, reference=None, tune_step=50):
        BaseTuner.__init__(self)
        self.name = name
        self.tunable = True
        self.tune_cmd = self.add_pv('{}:outPut'.format(name))
        self.reset_cmd = self.add_pv('{}:Reset.PROC'.format(picoameter))
        self.acquire_cmd = self.add_pv('{}:Acquire'.format(picoameter))
        self.value_fbk = self.add_pv('{}:SumAll:MeanValue_RBV'.format(picoameter))
        self.value_fbk.connect('changed', self.on_value_changed)
        if reference:
            self.reference_fbk = self.add_pv(reference)
        else:
            self.reference_fbk = self.value_fbk
        self.tune_step = tune_step

    def tune_up(self):
        pos = self.tune_cmd.get()
        self.tune_cmd.put(pos + self.tune_step)

    def tune_down(self):
        pos = self.tune_cmd.get()
        self.tune_cmd.put(pos - self.tune_step)

    def reset(self):
        self.reset_cmd.put(1)
        self.acquire_cmd.put(1)

    def get_value(self):
        return self.value_fbk.get()

    def pause(self):
        self.acquire_cmd.put(0)

    def resume(self):
        self.acquire_cmd.put(1)

    def start(self):
        if self.active_state:
            self.reset()

    def stop(self):
        if self.active_state:
            self.acquire_cmd.put(0)

    def on_state_changed(self, obj, val):
        self.set_state(enabled=(val==1))

    def on_value_changed(self, obj, val):
        ref = self.reference_fbk.get()
        perc = 0.0 if ref != 0 else 100.0 * val/ref
        self.set_state(changed=val, percent=perc)


class SimTuner(BaseTuner):
    def __init__(self, name):
        BaseTuner.__init__(self)
        self.set_state(active=True)
        self.name = name
        self.pos = -1.0
        self.reference = 10000
        self.value = self._calc_int()
        self.tunable = True
        GObject.timeout_add(50, self._change_value)

    def tune_up(self):
        self.pos += 0.01

    def tune_down(self):
        self.pos -= 0.01

    def reset(self):
        self.pos = -1.0

    def _calc_int(self):
        return self.reference * (1/math.sqrt(0.4*math.pi)) * math.exp(-0.5*(self.pos**2)/0.2)/0.892

    def _change_value(self):
        self.value = self._calc_int()
        noise = 10 * (random.random() - 0.5)
        value = noise + self.value
        perc = 100.0 * value / self.reference
        self.set_state(changed=value, percent=perc)
        return True

__all__ = ['BOSSTuner', 'MOSTABTuner', 'SimTuner']
