import math
import random

from gi.repository import GLib
from zope.interface import Interface, Attribute
from zope.interface import implementer

from mxdc import Signal, Device
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class IBeamTuner(Interface):
    """
    A Beam Tuner object.
    """

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


@implementer(IBeamTuner)
class BaseTuner(Device):
    """
    Base device for all Beam Tuners.  A beam tuner links to a beam intensity monitor and reports
    the percentage intensity compared to the expected value for the intensity monitor.  It also allows
    tweak the beam up or down. Optionally it can be an abstraction for a device which performs automated
    optimization of the beam.

    Signals:
        - *changed* (float,): emitted with the current value of the tuner
        - *percent* (float,): percentage of current value compared to expected
    """
    class Signals:
        changed = Signal("changed", arg_types=(float,))
        percent = Signal("percent", arg_types=(float,))

    def __init__(self):
        super().__init__()
        self.tunable = False

    def is_tunable(self):
        """
        Check if Tuner is actually tunable, or just a dummy tuner.
        """
        return self.tunable

    def tune_up(self):
        """
        Tweak the beam up.
        """
        pass

    def tune_down(self):
        """
        Tweak the beam down.
        """

    def get_value(self):
        """
        Return current value
        """
        return 0.0

    def reset(self):
        """
        Reset the beam tuner
        """
        pass

    def pause(self):
        """
        Pause optimization.
        """

    def resume(self):
        """
        Pause optimization.
        """

    def start(self):
        """
        Start optimization.
        """

    def stop(self):
        """
        Stop optimization.
        """



class BOSSTuner(BaseTuner):
    """
    Beam Tuner abstraction for the original ELETTRA Beamline Optimisation and Stabilization System (BOSS).

    :param name: Device name, i.e. root name for all process variables
    :param picoameter: Picoameter Process variable name
    :param current: Ring current process variable name
    :param reference: Optional reference process variable
    :param control: Optional process variable which indicates if control is enabled
    :param off_value: If the picoameter goes below this value, pause optimization
    :param pause_value: Set the threshold to this value when pausing.
    """
    def __init__(self, name, picoameter, current, reference=None, control=None, off_value=5e3, pause_value=1e13):

        super().__init__()
        self.name = name
        self.enable_cmd = self.add_pv('{}:EnableDacOUT'.format(name))
        self.enabled_fbk = self.add_pv('{}:EnableDacIN'.format(name))
        self.beam_threshold = self.add_pv('{}:OffIntOUT'.format(name))
        self.value_fbk = self.add_pv('{}'.format(picoameter))
        self.current_fbk = self.add_pv(current)
        self.enabled_fbk.connect('changed', self.on_state_changed)
        self.value_fbk.connect('changed', self.on_value_changed)
        if reference:
            self.reference_fbk = self.add_pv(reference)
        else:
            self.reference_fbk = self.value_fbk

        if control:
            self.control = self.add_pv(control)
            self.control.connect('changed', self.check_enable)

        self.local_paused = False
        self._off_value = off_value
        self._pause_value = pause_value

    def is_paused(self):
        return self.beam_threshold.get() > 0.9 * self._pause_value

    def reset(self):
        self.stop()
        self.start()

    def get_value(self):
        return self.value_fbk.get()

    def pause(self):
        logger.debug('Pausing BOSS')
        if not self.is_paused():
            self.local_paused = True
            self._off_value = self.beam_threshold.get()
            self.beam_threshold.put(self._pause_value)

    def resume(self):
        logger.debug('Resuming BOSS')
        if self.is_paused() and self.local_paused:
            self.local_paused = False
            self.beam_threshold.put(self._off_value)

    def start(self):
        logger.debug('Enabling BOSS')
        if self.is_active():
            self.enable_cmd.put(1)

    def stop(self):
        logger.debug('Disabling Beam Stabilization')
        if self.is_active():
            self.enable_cmd.put(0)

    def check_enable(self, obj, val):
        if val:
            self.resume()
        else:
            self.pause()

    def on_state_changed(self, obj, val):
        self.set_state(enabled=(val == 1))

    def on_value_changed(self, obj, val):
        ref = self.reference_fbk.get()
        cur = self.current_fbk.get()
        tgt = 0.0 if cur == 0 else val / cur
        perc = 0.0 if ref == 0 else 100.0 * tgt / ref
        self.set_state(changed=val, percent=perc)


class MOSTABTuner(BaseTuner):
    """
    Beam Tuner abstraction for the D-MOSTAB beam stabilisation hardware.

    :param name: Device name, i.e. root name for all process variables
    :param picoameter: Picoameter Process variable name
    :param current: Ring current process variable name
    :param reference: Optional reference process variable
    :param tune_step: step size to use for tune_up() and tune_down() methods.
    """

    def __init__(self, name, picoameter, current, reference=None, tune_step=50):
        super().__init__()
        self.name = name
        self.tunable = True
        self.tune_cmd = self.add_pv('{}:outPut'.format(name))
        self.reset_cmd = self.add_pv('{}:Reset.PROC'.format(picoameter))
        self.acquire_cmd = self.add_pv('{}:Acquire'.format(picoameter))
        self.value_fbk = self.add_pv('{}:SumAll:MeanValue_RBV'.format(picoameter))
        self.current_fbk = self.add_pv(current)
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
        if self.is_active():
            self.reset()

    def stop(self):
        if self.is_active():
            self.acquire_cmd.put(0)

    def on_state_changed(self, obj, val):
        self.set_state(enabled=(val == 1))

    def on_value_changed(self, obj, val):
        ref = self.reference_fbk.get()
        cur = self.current_fbk.get()
        tgt = 0.0 if cur == 0 else val / cur
        perc = 0.0 if ref == 0 else 100.0 * tgt / ref
        if cur > 10.0:
            # dynamic tune step
            self.tune_step = min(100, 5 * 2 ** round((90.0 - max(0, min(90, perc))) / 10, 0))
        else:
            self.tune_step = 0  # disable tuning if no beam
        self.set_state(changed=val, percent=perc)


class SimTuner(BaseTuner):
    """
    A Simulated Beam Tuner

    :param name:  Name of device
    """
    def __init__(self, name):
        super().__init__()
        self.set_state(active=True)
        self.name = name
        self.pos = -1.0
        self.reference = 10000
        self.value = self._calc_int()
        self.tunable = True
        GLib.timeout_add(50, self._change_value)

    def tune_up(self):
        self.pos += 0.01

    def tune_down(self):
        self.pos -= 0.01

    def reset(self):
        self.pos = -1.0

    def _calc_int(self):
        return self.reference * (1 / math.sqrt(0.4 * math.pi)) * math.exp(-0.5 * (self.pos ** 2) / 0.2) / 0.892

    def _change_value(self):
        self.value = self._calc_int()
        noise = 10 * (random.random() - 0.5)
        value = noise + self.value
        perc = 100.0 * value / self.reference
        self.set_state(changed=value, percent=perc)
        return True


__all__ = ['BOSSTuner', 'MOSTABTuner', 'SimTuner']
