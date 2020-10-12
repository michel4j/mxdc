import os
import time

import numpy
from gi.repository import GLib
from zope.interface import implementer

from mxdc import Registry, Signal, Device
from mxdc.com.ca import PV
from mxdc.devices.interfaces import IPositioner, IOnOff, IMotor
from mxdc.devices.motor import BaseMotor
from mxdc.utils import converter
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


@implementer(IPositioner)
class BasePositioner(Device):
    """
    Base class for a simple positioning devices.
    
    Signals:
        - `changed` : Data is the new value of the devices.
    """

    class Signals:
        changed = Signal("changed", arg_types=(object,))

    def __init__(self):
        super().__init__()
        self.units = ''

    def signal_change(self, obj, value):
        self.set_state(changed=self.get())

    def set(self, value):
        """
        Set the value of the positioner

        :param value: new value
        """
        raise NotImplementedError('Derived class must implement this method')

    def set_position(self, value):
        """
        Alias for the :func:`set` method.
        """
        return self.set(value)

    def get(self):
        """
        Get the current position
        """
        raise NotImplementedError('Derived class must implement this method')

    def get_position(self):
        """
        Alias for the :func:`get` method.
        """
        return self.get()


class SimPositioner(BasePositioner):
    """
    Simulated positioner

    :param name: name of device
    :param pos: initial position
    :param units: units
    :param active: initial active state
    :param delay: bool, delay position signal
    :param noise: simulated noise level
    """
    def __init__(self, name, pos=0.0, units="", active=True, delay=True, noise=2):
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
            self.set_state(changed=self._pos, active=active, enabled=active, health=(0, '',''))
        else:
            self.set_state(changed=self._pos, active=active, enabled=active, health=(16, 'disabled',''))

        if not isinstance(pos, (list, tuple)) and (self._noise > 0 or self._delay):
            GLib.timeout_add(50, self._drive)

    def set(self, pos, wait=False):
        self._pos = pos
        if not self._delay:
            self._fbk = pos
            self.set_state(changed=self._pos)

    def get(self):
        return self._fbk

    def _drive(self):
        self._fbk *= (1 - numpy.random.normal(0, 1)*self._noise/100)
        return True


class Positioner(BasePositioner):
    """
    Simple EPICS based positioning devices.

    :param name: process variable name

    Kwargs:
        - `fbk_name` (str): optional Name of PV for getting current value. If not
          provided, the same PV will be used to both set and get.
        - `scale` (float): A percentage to scale the set and get values by.
        - `units` (str): The units of the value.
    """

    def __init__(self, name, fbk_name=None, scale=100, units="", wait_time=0):
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

        self.fbk_pv.connect('changed', self.signal_change)
        self.DESC.connect('changed', self._on_name_change)

    def _on_name_change(self, pv, val):
        if val != '':
            self.name = val

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


class ChoicePositioner(BasePositioner):
    """
    An Enumerated EPICS choice positioner

    :param pv: name of process variable

    kwargs:
        - choices: tuple of values to translate to
        - units: device units
    """
    def __init__(self, pv, choices=(), units=""):
        super().__init__()
        self.units = units
        self.dev = self.add_pv(pv)
        self.choices = choices
        self.set_state(enabled=True)
        self.dev.connect('changed', self.signal_change)

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


class SimChoicePositioner(BasePositioner):
    """
    Simulated choice positioner

    :param pv: name of process variable
    :param value: initial value of positioner

    kwargs:
        - choices: tuple of values to translate to
        - units: device units
    """
    def __init__(self, name, value, choices=(), units="", active=True):
        self.name = name
        super().__init__()
        self.units = units
        self.choices = choices
        self._pos = value
        if active:
            self.set_state(changed=self._pos, active=active, enabled=active, health=(0, '', ''))
        else:
            self.set_state(changed=self._pos, active=active, enabled=active, health=(16, 'disabled', ''))

    def get(self):
        return self._pos

    def set(self, value, wait=False):
        logger.info('%s requesting %s' % (self.name, value))
        self._pos = value
        self.set_state(changed=self._pos)


@implementer(IOnOff)
class SampleLight(Positioner):
    """
    Illumination controller device. This device is a Positioner that can in addition be turned On and Off.

    :param set_name: name of PV for setting illumination level
    :param fbk_name: name of PV for getting the illumination level
    :param onoff_name: name of PV for toggling the light on or off

    kwargs:
        - scale: scale value for illumination level
        - units: units of the device

    """

    def __init__(self, set_name, fbk_name, onoff_name, scale=100, units=""):
        super().__init__(set_name, fbk_name, scale, units)
        self.onoff_cmd = self.add_pv(onoff_name)

    def set_on(self):
        """
        Turn on the device
        """
        self.onoff_cmd.put(1)

    def on(self):
        """
        Alias for :func:`set_on`

        """
        self.set_on()

    def set_off(self):
        """
        Turn off the device
        """
        self.onoff_cmd.put(0)

    def off(self):
        """
        Alias for :func:`set_off`

        """
        self.set_off()

    def is_on(self):
        """
        Check if the light is on or off
        """
        return self.onoff_cmd.get() == 1


@implementer(IOnOff)
class OnOffToggle(Device):
    """
    A Device that can be toggled on/off.

    Signals:
        - changed: (bool,) state of the device

    :param pv_name: process variable name

    kwargs:
        - values: tuple of values representing (on value, off value) for the PV.

    """
    class Signals:
        changed = Signal("changed", arg_types=(bool,))

    def __init__(self, pv_name, values=(1, 0)):
        super().__init__()
        self.on_value, self.off_value = values
        self.onoff_cmd = self.add_pv(pv_name)
        self.onoff_cmd.connect('changed', self.on_changed)

    def set_on(self):
        """
        Turn on the device
        """
        self.onoff_cmd.put(self.on_value, wait=True)

    def on(self):
        """
        Alias for :func:`set_on`

        """
        self.set_on()

    def set_off(self):
        """
        Turn off the device
        """
        self.onoff_cmd.put(self.off_value, wait=True)

    def off(self):
        """
        Alias for :func:`set_off`

        """
        self.set_off()

    def is_on(self):
        """
        Check if the light is on or off
        """
        return self.is_changed()

    def on_changed(self, obj, val):
        self.set_state(changed=(val == self.on_value))


@implementer(IOnOff)
class SimLight(SimPositioner):
    """
    Simulated Illumination Device

    :param name: name of device
    :param pos: initial illumination level

    kwargs:
        - units: device units
        - active: initial active state
    """
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
class PositionerMotor(BaseMotor):
    """
    Adapts a positioner so that it behaves like a Motor (ie, provides the
    `IMotor` interface.

    :param positioner:  Positioner device

    """
    __used_for__ = IPositioner

    def __init__(self, positioner):
        super().__init__('Positioner Motor')
        self.positioner = positioner
        self.name = positioner.name
        self.units = positioner.units
        self.positioner.connect('changed', self.on_change)

    def move_to(self, pos, wait=False, force=False):
        self.positioner.set(pos, wait)

    def move_by(self, val, wait=False, force=False):
        self.positioner.set(self.positioner.get() + val, wait)

    def stop(self):
        pass

    def get_position(self):
        return self.positioner.get()

    def wait(self, **kwargs):
        pass


Registry.add_adapter([IPositioner], IMotor, '', PositionerMotor)


class Attenuator(BasePositioner):
    """
    A positioner for EPICS XIA attenuator boxes

    :param bitname: root name of attenuator PV
    :param energy: energy process variable name

    """
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
            f.connect('changed', self.signal_change)
        self._energy.connect('changed', self.signal_change)

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
        thk = min(15, int(round(thickness * 10.0)))

        # bitmap of thickness is fillter pattern
        bitmap = converter.dec_to_bin(thk)
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

    def signal_change(self, obj, value):
        self.set_state(changed=self.get())


class Attenuator2(Attenuator):
    """
    Second generation XIA attenuator EPICS device

    :param bitname: root name of attenuator PV
    :param energy: energy process variable name

    """

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
            f.connect('changed', self.signal_change)
        self._energy.connect('changed', self.signal_change)

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
    """
    A device which periodically monitors a given path for available space.

    :param descr: Description
    :param path: Path to monitor
    :param warn: Warn if Fraction of available space goes below
    :param critical: Raise alarm if Fraction of available space goes below
    :param freq: Frequency in minutes to check space
    """

    def __init__(self, descr, path, warn=0.05, critical=0.025, freq=10):
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
        return "{:0.1f} {}B".format(value, symbols[idx])

    def check_space(self):
        """
        Check disk space and emit health signals accordingly
        """
        try:
            fs_stat = os.statvfs(self.path)
        except OSError:
            logger.error('Error accessing path {0}'.format(self.path))
        else:
            total = float(fs_stat.f_frsize * fs_stat.f_blocks)
            avail = float(fs_stat.f_frsize * fs_stat.f_bavail)
            fraction = avail / total
            quantity = self.humanize(avail)
            msg = f'{quantity} ({fraction:0.0%}) available.'
            if fraction < self.error_threshold:
                self.set_state(health=(4, 'usage', msg))
                logger.error(msg)
            elif fraction < self.warn_threshold:
                self.set_state(health=(2, 'usage', msg))
                logger.warn(msg)
            else:
                self.set_state(health=(1, 'usage', msg))
        return True


class Enclosures(Device):
    """
    A device for monitoring beamline enclosures

    :params kwargs: name, pv_name pairs each representing one beamline enclosure to monitor
    """
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
        """
        Generate and return messages indicating the status of the enclosures
        """
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


class SimEnclosures(Device):
    """
    Simulated Enclusures

    :param name: Name of device
    """
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.set_state(active=True, health=(0, 'ready', self.get_messages()))

    def get_messages(self):
        return "All secure"


class CamScaleFromZoom(BasePositioner):
    """
    A positioner for converting camera zoom values to pixel size for the sample microscope video.

    :param zoom: zoom device

    kwargs:
        - width: width of camera video.

    """
    def __init__(self, zoom, width=1360.0):
        super().__init__()
        self.name = 'Sample Camera Scale'
        self.zoom = zoom
        self.factor = 1360./width
        self._position = 1.0
        self.zoom.connect('changed', self.on_zoom)
        self.zoom.connect('active', self.on_active)

    def on_zoom(self, obj, value):
        self._position = self.factor * 0.00227167 * numpy.exp(-0.26441385 * value)
        self.set_state(changed=self._position)

    def get(self):
        return self._position

    def set(self, value):
        self._position = value
        self.set_state(changed=self._position)

    def on_active(self, obj, active):
        self.set_state(active=active)


class PositionerCollection(BasePositioner):
    def __init__(self, *components):
        super().__init__()
        self.name = ','.join(dev.name for dev in components)
        self.components = components
        self.add_components(components)
        for dev in self.components:
            dev.connect('changed', self.on_changed)

    def on_changed(self, obj, value):
        self.emit('changed', self.get())

    def put(self, *values):
        for dev, value in zip(self.components, values):
            dev.put(value, wait=True)

    def get(self):
        return tuple(dev.get() for dev in self.components)

    def get_position(self):
        return self.get()

    def set_position(self, *values):
        self.put(*values)