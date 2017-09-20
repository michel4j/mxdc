import os
import time

import numpy
from gi.repository import GObject
from zope.interface import implements

from mxdc import registry
from mxdc.com import ca
from mxdc.com.ca import PV
from mxdc.device.base import BaseDevice
from mxdc.device.motor import MotorBase
from mxdc.interface.devices import *
from mxdc.utils import converter, misc
from mxdc.utils.decorators import async
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class PositionerBase(BaseDevice):
    """Base class for a simple positioning device.
    
    Signals:
        - `changed` : Data is the new value of the device.
    """
    implements(IPositioner)
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST,
                    None,
                    (object,)),
    }

    def __init__(self):
        BaseDevice.__init__(self)
        self.units = ''

    def _signal_change(self, obj, value):
        self.set_state(changed=self.get())

    def set(self, value):
        """Set the value.
        Args:
            - `value` : New value to set.
        """
        raise NotImplementedError, 'Derived class must implement this method'

    def set_position(self, value):
        return self.set(value)

    def get(self):
        """
        Returns:
            - The current value.
        """
        raise NotImplementedError, 'Derived class must implement this method'

    def get_position(self):
        return self.get()


class SimPositioner(PositionerBase):
    def __init__(self, name, pos=0.0, units="", active=True, delay=True, noise=0):
        PositionerBase.__init__(self)
        self.name = name
        self._pos = pos
        self._fbk = self._pos
        self._delay = delay
        self._noise = noise
        self._step = 0.0
        self._min_step = 0.0

        self.units = units
        if active:
            self.set_state(changed=self._pos, active=active, health=(0, ''))
        else:
            self.set_state(changed=self._pos, active=active, health=(16, 'disabled'))

        if not isinstance(pos, (list, tuple)) and (self._noise > 0 or self._delay):
            GObject.timeout_add(1000, self._drive)

    def set(self, pos, wait=False):
        self._pos = pos
        if not self._delay:
            self._fbk = pos
            self.set_state(changed=self._pos)

    def get(self):
        return self._fbk

    def _drive(self):
        if abs(self._pos - self._fbk) > self._noise:
            self._fbk += (self._pos - self._fbk)/3
        else:
            self._fbk = numpy.random.normal(self._pos, 0.5*self._noise/2.35)
        if self._fbk != self._pos:
            self.set_state(changed=self._fbk)
        return True


class Positioner(PositionerBase):
    """Simple EPICS based positioning device.
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
        PositionerBase.__init__(self)
        self.set_pv = self.add_pv(name)
        self.scale = scale
        if fbk_name is None:
            self.fbk_pv = self.set_pv
        else:
            self.fbk_pv = self.add_pv(fbk_name)
        self.DESC = PV('%s.DESC' % name)  # device should work without desc pv so not using add_pv
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
            self.set_pv.set(pos)
        else:
            val = self.scale * pos / 100
            self.set_pv.set(val)
        if wait:
            time.sleep(self._wait_time)

    def get(self):
        if self.scale is None:
            return self.fbk_pv.get()
        else:
            val = 100 * (self.fbk_pv.get() / self.scale)
            return val


class ChoicePositioner(PositionerBase):
    def __init__(self, pv, choices=[], units=""):
        PositionerBase.__init__(self)
        self.units = units
        self.dev = self.add_pv(pv)
        self.choices = choices
        self.dev.connect('changed', self._signal_change)

    def get(self):
        val = self.dev.get()
        if not val in self.choices:
            return self.choices[val]
        else:
            return val

    def set(self, value, wait=False):
        if value in self.choices:
            self.dev.put(self.choices.index(value))
        else:
            self.dev.put(value)


class SimChoicePositioner(PositionerBase):
    def __init__(self, name, value, choices=[], units="", active=True):
        self.name = name
        PositionerBase.__init__(self)
        self.units = units
        self.choices = choices
        self._pos = value
        if active:
            self.set_state(changed=self._pos, active=active, health=(0, ''))
        else:
            self.set_state(changed=self._pos, active=active, health=(16, 'disabled'))

    def get(self):
        return self._pos

    def set(self, value, wait=False):
        logger.info('%s requesting %s' % (self.name, value))
        self._pos = value
        self.set_state(changed=self._pos)


class SampleLight(Positioner):
    implements(IOnOff)

    def __init__(self, set_name, fbk_name, onoff_name, scale=100, units=""):
        Positioner.__init__(self, set_name, fbk_name, scale, units)
        self.onoff_cmd = self.add_pv(onoff_name)

    def set_on(self):
        self.onoff_cmd.put(1)

    on = set_on

    def set_off(self):
        self.onoff_cmd.put(0)

    off = set_off

    def is_on(self):
        return self.onoff_cmd.get() == 1


class OnOffToggle(BaseDevice):
    implements(IOnOff)
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, pv_name):
        super(OnOffToggle, self).__init__()
        self.onoff_cmd = self.add_pv(pv_name)
        self.onoff_cmd.connect('changed', self.on_changed)

    def set_on(self):
        self.onoff_cmd.put(1)

    on = set_on

    def set_off(self):
        self.onoff_cmd.put(0)

    off = set_off

    def is_on(self):
        return self.changed_state

    def on_changed(self, obj, val):
        self.set_state(changed=(val == 1))


class SimLight(SimPositioner):
    implements(IOnOff)

    def __init__(self, name, pos=0, units="", active=True):
        SimPositioner.__init__(self, name, pos, units, active)
        self._on = 0

    def set_on(self):
        self._on = 1

    def set_off(self):
        self._on = 0

    def is_on(self):
        return self._on == 1


class PositionerMotor(MotorBase):
    """Adapts a positioner so that it behaves like a Motor (ie, provides the
    `IMotor` interface.
    """
    implements(IMotor)
    __used_for__ = IPositioner

    def __init__(self, positioner):
        """
        Args:
            - `positioner` (:class:`PositionerBase`)
        """
        MotorBase.__init__(self, 'Positioner Motor')
        self.positioner = positioner
        self.name = positioner.name
        self.units = positioner.units
        self.positioner.connect('changed', self._signal_change)

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

    def wait(self):
        ca.flush()


registry.register([IPositioner], IMotor, '', PositionerMotor)


class Attenuator(PositionerBase):
    def __init__(self, bitname, energy):
        super(Attenuator, self).__init__()
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
        if self._energy.connected():
            e = self._energy.get()
        else:
            return 999.0
        bitmap = ''
        for f in self._filters:
            if f.connected():
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
        super(Attenuator2, self).__init__(bitname=bitname, energy=energy)
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


class BasicShutter(BaseDevice):
    implements(IShutter)

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST,
                    None,
                    (bool,)),
    }

    def __init__(self, open_name, close_name, state_name):
        BaseDevice.__init__(self)
        # initialize variables
        self._open_cmd = self.add_pv(open_name)
        self._close_cmd = self.add_pv(close_name)
        self._state = self.add_pv(state_name)
        self._state.connect('changed', self._signal_change)
        self._messages = ['Opening', 'Closing']
        self.name = open_name.split(':')[0]

    def is_open(self):
        """Convenience function for open state"""
        return self.changed_state

    def open(self, wait=False):
        if self.changed_state:
            return
        logger.debug(' '.join([self._messages[0], self.name]))
        self._open_cmd.set(1)
        ca.flush()
        self._open_cmd.set(0)
        if wait:
            self.wait(state=True)

    def close(self, wait=False):
        if not self.changed_state:
            return
        logger.debug(' '.join([self._messages[1], self.name]))
        self._close_cmd.set(1)
        ca.flush()
        self._close_cmd.set(0)
        if wait:
            self.wait(state=False)

    def wait(self, state=True, timeout=5.0):
        while self.changed_state != state and timeout > 0:
            time.sleep(0.1)
            timeout -= 0.1
        if timeout <= 0:
            logger.warning('Timed-out waiting for %s.' % (self.name))

    def _signal_change(self, obj, value):
        if value == 1:
            self.set_state(changed=True)
        else:
            self.set_state(changed=False)


class StateLessShutter(BaseDevice):
    implements(IShutter)

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST,
                    None,
                    (bool,)),
    }

    def __init__(self, open_name, close_name):
        BaseDevice.__init__(self)
        # initialize variables
        self._open_cmd = self.add_pv(open_name)
        self._close_cmd = self.add_pv(close_name)
        self._messages = ['Opening', 'Closing']
        self.name = open_name.split(':')[0]

    def open(self, wait=False):
        logger.debug(' '.join([self._messages[0], self.name]))
        self._open_cmd.toggle(1, 0)

    def close(self, wait=False):
        logger.debug(' '.join([self._messages[1], self.name]))
        self._close_cmd.toggle(1, 0)

    def wait(self, state=True, timeout=5.0):
        logger.warning('Stateless Shutter wont wait (%s).' % (self.name))


class ShutterGroup(BaseDevice):
    implements(IShutter)
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST,
                    None,
                    (bool,)),
    }

    def __init__(self, *args, **kwargs):
        super(ShutterGroup, self).__init__()
        self._dev_list = list(args)
        self.add_devices(*self._dev_list)
        self.name = 'Beamline Shutters'
        for dev in self._dev_list:
            dev.connect('changed', self._on_change)

    def is_open(self):
        """Convenience function for open state"""
        return self.changed_state

    def _on_change(self, obj, val):
        if val:
            if misc.every([dev.changed_state for dev in self._dev_list]):
                self.set_state(changed=True, health=(0, 'state'))
        else:
            self.set_state(changed=False, health=(2, 'state', 'Not Open!'))

    @async
    def open(self, wait=False):
        for dev in self._dev_list:
            dev.open(wait=True)

    @async
    def close(self, wait=False):
        newlist = self._dev_list[:]
        newlist.reverse()
        for i, dev in enumerate(newlist):
            dev.close(wait=True)

    def wait(self, state=True, timeout=5.0):
        while self.changed_state != state and timeout > 0:
            time.sleep(0.1)
            timeout -= 0.1
        if timeout <= 0:
            logger.warning('Timed-out waiting for %s.' % (self.name))


class SimShutter(BaseDevice):
    implements(IShutter)

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST,
                    None,
                    (object,)),
    }

    def __init__(self, name):
        BaseDevice.__init__(self)
        self.name = name
        self._state = False
        self.set_state(active=True, changed=self._state)

    def is_open(self):
        """Convenience function for open state"""
        return self.changed_state

    def open(self, wait=False):
        self._state = True
        self.set_state(changed=True)

    def close(self, wait=False):
        self._state = False
        self.set_state(changed=False)

    def wait(self, state=True, timeout=5.0):
        pass


class Shutter(BasicShutter):
    def __init__(self, name):
        open_name = "%s:opr:open" % name
        close_name = "%s:opr:close" % name
        state_name = "%s:state" % name
        BasicShutter.__init__(self, open_name, close_name, state_name)


class Collimator(BaseDevice):
    implements(ICollimator)

    def __init__(self, x, y, width, height, name='Collimator'):
        BaseDevice.__init__(self)
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.add_devices(x, y, width, height)

    def wait(self):
        self.width.wait()
        self.height.wait()
        self.x.wait()
        self.y.wait()

    def stop(self):
        self.width.stop()
        self.height.stop()
        self.x.stop()
        self.y.stop()


class SimStorageRing(BaseDevice):
    implements(IStorageRing)
    __gsignals__ = {
        "beam": (GObject.SignalFlags.RUN_FIRST,
                 None,
                 (bool,)),
    }

    def __init__(self, name, pv1=None, pv2=None, pv3=None):
        BaseDevice.__init__(self)
        self.name = name
        self.message = 'Sim SR Testing!'
        self.set_state(beam=False, active=True, health=(0, ''))
        # GObject.timeout_add(1200000, self._change_beam)

    def _change_beam(self):
        _beam = not self.beam_state
        if self.health_state[0] == 0:
            _health = 4
            _message = "Beam dump."
        else:
            _health = 0
            _message = "Beam available."
        self.set_state(beam=_beam, health=(_health, 'mode', _message), active=True)
        return True

    def beam_available(self):
        return self.beam_state

    def wait_for_beam(self, timeout=60):
        while not self.beam_available() and timeout > 0:
            time.sleep(0.05)
            timeout -= 0.05
        logger.warn('Timed out waiting for beam!')


class DiskSpaceMonitor(BaseDevice):
    """An object which periodically monitors a given path for available space."""

    def __init__(self, descr, path, warn=0.05, critical=0.025, freq=5.0):
        """
        Args:
            - `descr` (str): A description.
            - `path` (str): Path to monitor.
            
        Kwargs:
            - `warn` (float): Warn if fraction of used space goes above this
              value.
            - `critical` (float): Raise and error i if fraction of used space 
              goes above this value.              
            -`freq` (float): Frequency in minutes to check disk usage. Default (5)
        """
        BaseDevice.__init__(self)
        self.name = descr
        self.path = path
        self.warn_threshold = warn
        self.error_threshold = critical
        self.frequency = int(freq * 60 * 1000)
        self.set_state(active=True)
        self._check_space()
        GObject.timeout_add(self.frequency, self._check_space)

    def _humanize(self, sz):
        symbols = ('', 'K', 'M', 'G', 'T', 'P')
        base_sz = numpy.ones(len(symbols))
        base_sz[1:] = 1 << (numpy.arange(len(symbols) - 1) + 1) * 10
        idx = numpy.where(base_sz <= sz)[0][-1]
        value = float(sz) / base_sz[idx]
        return "%0.2f %sB" % (value, symbols[idx])

    def _check_space(self):
        try:
            fs_stat = os.statvfs(self.path)
        except OSError:
            logger.error('Error accessing path {0}'.format(self.path))
        else:
            total = float(fs_stat.f_frsize * fs_stat.f_blocks)
            avail = float(fs_stat.f_frsize * fs_stat.f_bavail)
            fraction = avail / total
            msg = '%s (%0.1f %%) available.' % (self._humanize(avail), fraction * 100)
            if fraction < self.error_threshold:
                self.set_state(health=(4, 'usage', msg))
                logger.error(msg)
            elif fraction < self.warn_threshold:
                self.set_state(health=(2, 'usage', msg))
                logger.warn(msg)
            else:
                self.set_state(health=(0, 'usage', msg))
        return True


class StorageRing(BaseDevice):
    implements(IStorageRing)
    __gsignals__ = {
        "beam": (GObject.SignalFlags.RUN_FIRST,
                 None,
                 (bool,)),
    }

    def __init__(self, pv1, pv2, pv3):
        BaseDevice.__init__(self)
        self.name = "Storage Ring"
        self.mode = self.add_pv(pv1)
        self.current = self.add_pv(pv2)
        self.control = self.add_pv('%s:shutters' % pv3)
        self.messages = [
            self.add_pv('%s:msg:L1' % pv3),
            self.add_pv('%s:msg:L2' % pv3),
            self.add_pv('%s:msg:L3' % pv3)]

        self.mode.connect('changed', self._on_mode_change)
        self.current.connect('changed', self._on_current_change)
        self.control.connect('changed', self._on_control_change)
        self._last_current = 0.0

    def beam_available(self):
        return self.beam_state

    def wait_for_beam(self, timeout=60):
        while not self.beam_available() and timeout > 0:
            time.sleep(0.05)
            timeout -= 0.05
        logger.warn('Timed out waiting for beam!')

    def _get_message(self):
        return ', '.join([pv.get() for pv in self.messages])

    def _check_beam(self):
        if self.health_state[0] == 0:
            self.set_state(beam=True)
        else:
            self.set_state(beam=False)

    def _on_mode_change(self, obj, val):
        if val != 4:
            self.set_state(health=(4, 'mode', self._get_message()))
        else:
            self.set_state(health=(0, 'mode'))
        self._check_beam()

    def _on_control_change(self, obj, val):
        if val != 1:
            self.set_state(health=(1, 'control', 'Beamlines disabled.'))
        else:
            self.set_state(health=(0, 'control'))
        self._check_beam()

    def _on_current_change(self, obj, val):
        if val <= 5:
            if (self._last_current - val) >= 50.0:
                self.set_state(health=(4, 'beam', 'Beam lost!'))
            else:
                self.set_state(health=(4, 'beam', self._get_message()))
        else:
            self.set_state(health=(0, 'beam'))
        self._last_current = val
        self._check_beam()


class Enclosures(BaseDevice):
    __gsignals__ = {
        "ready": (GObject.SignalFlags.RUN_FIRST,
                  None,
                  (bool,)),
    }

    def __init__(self, **kwargs):
        BaseDevice.__init__(self)
        self.name = "Beamline Enclosures"
        self.hutches = {}
        for k, n in kwargs.items():
            p = self.add_pv(n)
            self.hutches[k] = p
            p.connect('changed', self._on_change)

    def _get_message(self):
        if self.ready_state:
            return "All enclosures secure"
        else:
            msg = ", ".join([k.upper() for k, v in self.hutches.items() if v.get() == 0])
            return "%s not secure" % msg

    def _on_change(self, obj, val):
        rd = all([p.get() == 1 for p in self.hutches.values()])
        self.set_state(ready=rd)
        if not rd:
            self.set_state(health=(2, 'ready', self._get_message()))
        else:
            self.set_state(health=(0, 'ready', self._get_message()))
