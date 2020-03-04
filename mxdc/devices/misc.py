import os
import time

import numpy
from gi.repository import GLib
from zope.interface import implementer

from mxdc import Registry, Signal, Device
from mxdc.com.ca import PV
from mxdc.devices.motor import MotorBase
from mxdc.utils import converter
from mxdc.utils.log import get_module_logger
from .interfaces import *

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


@implementer(IPositioner)
class PositionerBase(Device):
    """Base class for a simple positioning devices.
    
    Signals:
        - `changed` : Data is the new value of the devices.
    """

    class Signals:
        changed = Signal("changed", arg_types=(object,))

    def __init__(self):
        super().__init__()
        self.units = ''

    def _signal_change(self, obj, value):
        self.set_state(changed=self.get())

    def set(self, value):
        """Set the value.
        Args:
            - `value` : New value to set.
        """
        raise NotImplementedError('Derived class must implement this method')

    def set_position(self, value):
        return self.set(value)

    def get(self):
        """
        Returns:
            - The current value.
        """
        raise NotImplementedError('Derived class must implement this method')

    def get_position(self):
        return self.get()


class SimPositioner(PositionerBase):
    def __init__(self, name, pos=0.0, units="", active=True, delay=True, noise=0):
        super().__init__()
        self.name = name
        self._pos = pos
        self._fbk = self._pos
        self._delay = delay
        self._noise = noise
        self._step = 0.0
        self._min_step = 0.0

        self.units = units
        if active:
            self.set_state(changed=self._pos, active=active, health=(0, '',''))
        else:
            self.set_state(changed=self._pos, active=active, health=(16, 'disabled',''))

        if not isinstance(pos, (list, tuple)) and (self._noise > 0 or self._delay):
            GLib.timeout_add(1000, self._drive)

    def set(self, pos, wait=False):
        self._pos = pos
        if not self._delay:
            self._fbk = pos
            self.set_state(changed=self._pos)

    def get(self):
        return self._fbk

    def _drive(self):
        if abs(self._pos - self._fbk) >= self._noise:
            self._fbk += (self._pos - self._fbk) / 3
        else:
            self._fbk = numpy.random.normal(self._pos, 0.5 * self._noise / 2.35)
        if self._fbk != self._pos:
            self.set_state(changed=self._fbk)
        return True


class Positioner(PositionerBase):
    """Simple EPICS based positioning devices.
    """

    def __init__(self, name, fbk_name=None, scale=100, units="", wait_time=0):
        """Args:
            - `name` (str): Name of positioner PV for setting the value
        
        Kwargs:
            - `fbk_name` (str): Name of PV for getting current value. If not 
              provided, the same PV will be used to both set and get.
            - `scale` (float): A percentage to scale the set and get values by.
            - `units` (str): The units of the value.
        """
        super().__init__()
        self.set_pv = self.add_pv(name)
        self.scale = scale
        if fbk_name is None:
            self.fbk_pv = self.set_pv
        else:
            self.fbk_pv = self.add_pv(fbk_name)
        self.DESC = PV('%s.DESC' % name)  # devices should work without desc pv so not using add_pv
        self.name = name
        self.units = units
        self._wait_time = wait_time

        self.fbk_pv.connect('changed', self._signal_change)
        self.DESC.connect('changed', self._on_name_change)

    def _on_name_change(self, pv, val):
        if val != '':
            self.name = val

    def __repr__(self):
        return '<%s:%s, target:%s, feedback:%s>' % (self.__class__.__name__,
                                                    self.name,
                                                    self.set_pv.name,
                                                    self.fbk_pv.name)

    def set(self, pos, wait=False):
        if self.scale is None:
            self.set_pv.put(pos)
        else:
            val = self.scale * pos / 100
            self.set_pv.put(val)
        if wait:
            time.sleep(self._wait_time)

    def get(self):
        if self.scale is None:
            return self.fbk_pv.get()
        else:
            val = 100 * (self.fbk_pv.get() or 0.0) / self.scale
            return val


class ChoicePositioner(PositionerBase):
    def __init__(self, pv, choices=(), units=""):
        super().__init__()
        self.units = units
        self.dev = self.add_pv(pv)
        self.choices = choices
        self.dev.connect('changed', self._signal_change)

    def get(self):
        val = self.dev.get()
        if val in self.choices:
            return val
        elif val is not None:
            return self.choices[val]
        else:
            return self.choices[0]

    def set(self, value, wait=False):
        if value in self.choices:
            self.dev.put(self.choices.index(value))
        else:
            self.dev.put(value)


class SimChoicePositioner(PositionerBase):
    def __init__(self, name, value, choices=(), units="", active=True):
        self.name = name
        super().__init__()
        self.units = units
        self.choices = choices
        self._pos = value
        if active:
            self.set_state(changed=self._pos, active=active, health=(0, '', ''))
        else:
            self.set_state(changed=self._pos, active=active, health=(16, 'disabled', ''))

    def get(self):
        return self._pos

    def set(self, value, wait=False):
        logger.info('%s requesting %s' % (self.name, value))
        self._pos = value
        self.set_state(changed=self._pos)


@implementer(IOnOff)
class SampleLight(Positioner):

    def __init__(self, set_name, fbk_name, onoff_name, scale=100, units=""):
        super().__init__(set_name, fbk_name, scale, units)
        self.onoff_cmd = self.add_pv(onoff_name)

    def set_on(self):
        self.onoff_cmd.put(1)

    on = set_on

    def set_off(self):
        self.onoff_cmd.put(0)

    off = set_off

    def is_on(self):
        return self.onoff_cmd.get() == 1


@implementer(IOnOff)
class OnOffToggle(Device):

    class Signals:
        changed = Signal("changed", arg_types=(bool,))

    def __init__(self, pv_name, values=(1, 0)):
        super().__init__()
        self.on_value, self.off_value = values
        self.onoff_cmd = self.add_pv(pv_name)
        self.onoff_cmd.connect('changed', self.on_changed)

    def set_on(self):
        self.onoff_cmd.put(self.on_value)

    on = set_on

    def set_off(self):
        self.onoff_cmd.put(self.off_value)

    off = set_off

    def is_on(self):
        return self.is_changed()

    def on_changed(self, obj, val):
        self.set_state(changed=(val == self.on_value))


@implementer(IOnOff)
class SimLight(SimPositioner):

    def __init__(self, name, pos=0, units="", active=True):
        super().__init__(name, pos, units, active)
        self._on = 0

    def set_on(self):
        self._on = 1

    def set_off(self):
        self._on = 0

    def is_on(self):
        return self._on == 1


@implementer(IMotor)
class PositionerMotor(MotorBase):
    """Adapts a positioner so that it behaves like a Motor (ie, provides the
    `IMotor` interface.
    """
    __used_for__ = IPositioner

    def __init__(self, positioner):
        """
        Args:
            - `positioner` (:class:`PositionerBase`)
        """
        super().__init__('Positioner Motor')
        self.positioner = positioner
        self.name = positioner.name
        self.units = positioner.units
        self.positioner.connect('changed', self.on_change)

    def configure(self, props):
        pass

    def move_to(self, pos, wait=False):
        self.positioner.set(pos, wait)

    def move_by(self, val, wait=False):
        self.positioner.set(self.positioner.get() + val, wait)

    def stop(self):
        pass

    def get_position(self):
        return self.positioner.get()

    def wait(self, **kwargs):
        time.sleep(0.02)


Registry.add_adapter([IPositioner], IMotor, '', PositionerMotor)


class Attenuator(PositionerBase):
    def __init__(self, bitname, energy):
        super().__init__()
        fname = bitname[:-1]
        self._filters = [
            PV('%s4:bit' % fname),
            PV('%s3:bit' % fname),
            PV('%s2:bit' % fname),
            PV('%s1:bit' % fname),
        ]
        self._energy = PV(energy)
        self.units = '%'
        self.name = 'Attenuator'
        for f in self._filters:
            f.connect('changed', self._signal_change)
        self._energy.connect('changed', self._signal_change)

    def get(self):
        if self._energy.is_connected():
            e = self._energy.get()
        else:
            return 999.0
        bitmap = ''
        for f in self._filters:
            if f.is_connected():
                bitmap += '%d' % f.get()
            else:
                return 999.0
        thickness = int(bitmap, 2) / 10.0
        if e < .1:
            e = 0.1
        if e > 100:
            e = 100.0
        attenuation = 1.0 - numpy.exp(-4.4189e12 * thickness /
                                      (e * 1000 + 1e-6) ** 2.9554)
        if attenuation < 0:
            attenuation = 0
        elif attenuation > 1.0:
            attenuation = 1.0
        self._bitmap = bitmap
        return attenuation * 100.0

    def _set_bits(self, bitmap):
        for i in range(4):
            self._filters[i].put(int(bitmap[i]))

    def set(self, target, wait=False):
        e = self._energy.get()
        if target > 99.9:
            target = 99.9
        elif target < 0.0:
            target = 0.0
        frac = target / 100.0

        # calculate required aluminum thickness
        thickness = numpy.log(1.0 - frac) * (e * 1000 + 1e-6) ** 2.9554 / -4.4189e12
        thk = int(round(thickness * 10.0))
        if thk > 15: thk = 15

        # bitmap of thickness is fillter pattern
        bitmap = '%04d' % int(converter.dec_to_bin(thk))
        self._set_bits(bitmap)
        logger.info('Attenuation of %f %s requested' % (target, self.units))
        logger.debug('Filters [8421] set to [%s] (0=off,1=on)' % bitmap)

        if wait:
            timeout = 5.0
            while timeout > 0 and self._bitmap != bitmap:
                timeout -= 0.05
                time.sleep(0.05)
            if timeout <= 0:
                logger.warning('Attenuator timed out going to [%s]' % (bitmap))

    def _signal_change(self, obj, value):
        self.set_state(changed=self.get())


class Attenuator2(Attenuator):
    def __init__(self, bitname, energy):
        super().__init__(bitname=bitname, energy=energy)
        fname = bitname[:-1]
        self._filters = [
            PV('%s4:ctl' % fname),
            PV('%s3:ctl' % fname),
            PV('%s2:ctl' % fname),
            PV('%s1:ctl' % fname),
        ]
        self._open = [
            PV('%s4:opr:open' % fname),
            PV('%s3:opr:open' % fname),
            PV('%s2:opr:open' % fname),
            PV('%s1:opr:open' % fname),
        ]
        self._close = [
            PV('%s4:opr:close' % fname),
            PV('%s3:opr:close' % fname),
            PV('%s2:opr:close' % fname),
            PV('%s1:opr:close' % fname),
        ]
        self._energy = PV(energy)
        self.units = '%'
        self.name = 'Attenuator'
        for f in self._filters:
            f.connect('changed', self._signal_change)
        self._energy.connect('changed', self._signal_change)

    def _set_bits(self, bitmap):
        for i in range(4):
            val = int(bitmap[i])
            if self._filters[i].get() == val:
                continue
            if val == 1:
                self._close[i].put(1)
            else:
                self._open[i].put(1)


class DiskSpaceMonitor(Device):
    """An object which periodically monitors a given path for available space."""

    def __init__(self, descr, path, warn=0.05, critical=0.025, freq=5.0):
        """
        :param descr: Description
        :param path: Path to monitor
        :param warn: Warn if Fraction of available space goes below
        :param critical: Raise alarm if Fraction of available space goes below
        :param freq: Frequency in minutes to check space
        """
        super().__init__()
        self.name = descr
        self.path = path
        self.warn_threshold = warn
        self.error_threshold = critical
        self.frequency = int(freq * 60 * 1000)
        self.set_state(active=True)
        self.check_space()
        GLib.timeout_add(self.frequency, self.check_space)

    def humanize(self, size):
        """
        Convert disk space to human friendly units
        :param size: disk size
        :return: human friendly size string
        """
        symbols = ('', 'K', 'M', 'G', 'T', 'P')
        base_sz = numpy.ones(len(symbols))
        base_sz[1:] = 1 << (numpy.arange(len(symbols) - 1) + 1) * 10
        idx = numpy.where(base_sz <= size)[0][-1]
        value = float(size) / base_sz[idx]
        return "{:0.2f} {}B".format(value, symbols[idx])

    def check_space(self):
        """
        Check disk space and emit health signals accordingly
        :return:
        """
        try:
            fs_stat = os.statvfs(self.path)
        except OSError:
            logger.error('Error accessing path {0}'.format(self.path))
        else:
            total = float(fs_stat.f_frsize * fs_stat.f_blocks)
            avail = float(fs_stat.f_frsize * fs_stat.f_bavail)
            fraction = avail / total
            msg = '{} ({:0.1f} %) available.'.format(self.humanize(avail), fraction * 100)
            if fraction < self.error_threshold:
                self.set_state(health=(4, 'usage', msg))
                logger.error(msg)
            elif fraction < self.warn_threshold:
                self.set_state(health=(2, 'usage',msg))
                logger.warn(msg)
            else:
                self.set_state(health=(0, 'usage',msg))
        return True


class Enclosures(Device):
    def __init__(self, **kwargs):
        super().__init__()
        self.name = "Beamline Enclosures"
        self.hutches = {}
        self.ready = False
        for k, n in list(kwargs.items()):
            p = self.add_pv(n)
            self.hutches[k] = p
            p.connect('changed', self.handle_change)

    def get_messages(self):
        if self.ready:
            return "All secure"
        else:
            msg = ", ".join([k.upper() for k, v in list(self.hutches.items()) if v.get() == 0])
            return "{} not secure".format(msg)

    def handle_change(self, obj, val):
        self.ready = all([p.get() == 1 for p in list(self.hutches.values())])
        if not self.ready:
            self.set_state(health=(2, 'ready',self.get_messages()))
        else:
            self.set_state(health=(0, 'ready',self.get_messages()))
