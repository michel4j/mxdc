import time
from threading import Lock

import numpy
from gi.repository import GObject
from zope.interface import implements

from interfaces import IMotor
from mxdc.devices.base import BaseDevice
from mxdc.utils import converter
from mxdc.utils.decorators import async_call
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class MotorError(Exception):
    """Base class for errors in the motor module."""


class MotorBase(BaseDevice):
    """Base class for motors.
    
    Signals:
        - `changed` (float): Emitted everytime the position of the motor changes.
          Data contains the current position of the motor.
        - `target` (float): Emitted everytime the requested position of the motor changes.
          Data is a tuple containing the previous set point and the current one.
        - `time` (float): Emitted everytime the motor changes.
          Data is a 2-tuple with the current position and the timestamp of the last change.
        - `starting` (None): Emitted when this a command to move has been accepted by this instance of the motor.
        - `done` (None): Emitted within the instance when a commanded move has completed.
    """
    implements(IMotor)

    # Motor signals
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "starting": (GObject.SignalFlags.RUN_FIRST, None, []),
        "done": (GObject.SignalFlags.RUN_FIRST, None, []),
        "target": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "time": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, name, precision=2, units=''):
        super(MotorBase, self).__init__()
        self.name = name
        self.description = name
        self.moving = False
        self.command_active = False
        self.starting = False
        self.target_position = 0
        self.previous_position = None
        self.units = units
        self.default_precision = precision

        self.moving_value = 1
        self.disabled_value = 0
        self.calibrated_value = 1
        self.setup()

    def setup(self):
        """
        Prepare all the components of the motor when it is started. Subclasses must implement it
        """
        raise NotImplementedError

    def do_starting(self):
        self.starting = True

    def do_done(self):
        self.starting = False

    def do_busy(self, state):
        if self.starting and not state:
            self.set_state(done=None)

    # general notification callbacks
    def notify_change(self, obj, value):
        """
        Callback to Emit "changed" and "time" signals whenn the motor position changes

        @param obj: process variable object
        @param value: value of process variable
        """
        t = obj.time_state or time.time()
        self.set_state(time=t)
        self.set_state(changed=self.get_position())

    def notify_target(self, obj, value):
        """
        Callback to emit "target" signal when the motor target is changed.

        @param obj: process variable object
        @param value: value of process variable
        """
        self.set_state(target=(self.previous_position, value))
        self.previous_position = value

    def notify_motion(self, obj, state):
        """
        Callback to emit "starting" and "busy" signal when the motor starts moving.

        @param obj: process variable object
        @param value: value of process variable
        """
        if state == self.moving_value:
            self.moving = True
            if self.command_active:
                self.set_state(starting=None)
                self.command_active = False
        else:
            self.moving = False

        self.set_state(busy=self.moving)
        if not self.moving:
            logger.debug("(%s) stopped at %f" % (self.name, self.get_position()))

    def notify_calibration(self, obj, state):
        """
        Callback to emit "health" signal changes when the motor calibration changes.

        @param obj: process variable object
        @param value: value of process variable
        """
        if state == self.calibrated_value:
            self.set_state(health=(0, 'calib'))
        else:
            self.set_state(health=(4, 'calib', 'Device Not Calibrated!'))

    def notify_enable(self, obj, val):
        """
        Callback to emit "enabled" signal when the motor-enabled state is changed.

        @param obj: process variable object
        @param value: value of process variable
        """
        self.set_state(enabled=(val != self.disabled_value))

    # main motor utility interface methods
    def get_precision(self):
        """
        Get the number of decimal places, of the precition of the motor
        @return: (integer)
        """
        return self.default_precision

    def has_reached(self, value):
        """
        Check if the motor has reached a given position.

        @param value: query position
        @return: (boolean)
        """
        current = self.get_position()
        precision = self.get_precision()
        if self.units == 'deg':
            value = value % 360.0
            current = current % 360.0
        return abs(round(current - value, precision)) <= 10 ** -precision

    def wait_start(self, timeout=10, poll=0.01):
        """
        Wait for motor to start moving
        @param timeout: Maximum time to wait before failing
        @param poll: Time step between checking motor state
        @return: (boolean), True if motor started successfully
        """
        if self.command_active and not self.busy_state:
            logger.debug('Waiting for {} to start '.format(self.name))
            while self.command_active and not self.busy_state and timeout > 0:
                timeout -= poll
                time.sleep(poll)
                if self.has_reached(self.target_position):
                    self.command_active = False
                    logger.debug('{} already at {:g}'.format(self.name, self.target_position))
            if timeout <= 0:
                logger.warning('({}) Timed out. Did not move after {:g} sec.'.format(self.name, timeout))
                return False
        return True

    def wait_stop(self, target=None, timeout=120, poll=0.01):
        """
        Wait for motor to stop moving.

        @param target: Optional target to check
        @param timeout: Maximum time to wait before failing
        @param poll: Time step between checking motor state
        @return: (boolean), True if motor stopped successfully or if it is not moving.
        """
        if target is not None:
            logger.debug('Waiting for {} to reach {:g}.'.format(self.name, target))
            while (self.busy_state or not self.has_reached(target)) and timeout > 0:
                timeout -= poll
                time.sleep(poll)

            if timeout <= 0:
                logger.warning(
                    '({}) Timed-out. Did not reach {:g} after {:g} sec.'.format(
                        self.name, self.target_position, timeout)
                )
                return False
        else:
            logger.debug('Waiting for {} to stop '.format(self.name))
            while self.busy_state and timeout > 0:
                timeout -= poll
                time.sleep(poll)
            if timeout <= 0:
                logger.warning(
                    '({}) Timed-out. Did not stop moving after {:d} sec.'.format(self.name, timeout)
                )
                return False
        return True

    def wait(self, start=True, stop=True):
        """
        Wait for the motor busy state to change.

        @param start: (bool) Wait for the motor to start moving.
        @param stop: (bool): Wait for the motor to stop moving.
        @return: (bool), True if successful
        """
        success = True
        target = self.target_position if self.command_active else None
        if start:
            success &= self.wait_start()
        if stop:
            success &= self.wait_stop()
        return success


class SimMotor(MotorBase):
    implements(IMotor)

    def __init__(self, name, pos=0, units='mm', speed=10.0, active=True, precision=3, health=(0, '')):
        super(SimMotor, self).__init__(name, precision=precision, units=units)
        self.default_speed = speed

        self._status = 0
        self._step_time = .001  # 1000 steps per second
        self._stopped = False
        self._enabled = True
        self._lock = Lock()
        self._active = active
        self._health = health
        self._position = pos
        self._target = None

        self.configure(speed=speed)
        self.initialize()

    def setup(self):
        pass

    def initialize(self):
        self.set_state(health=self._health, active=self._active)
        self.notify_target(self, self._position)
        self.notify_change(self, self._position)

    def get_position(self):
        return self._position

    def configure(self, *args, **kwargs):
        with self._lock:
            if 'speed' in kwargs:
                self._speed = kwargs['speed']  # speed
                self._step_size = self._speed * self._step_time

    @async_call
    def _move_action(self, target):
        self._stopped = False
        self.command_active = True
        with self._lock:
            self.set_state(busy=True)
            self.set_state(target=(self._target, target))
            self._target = target
            _num_steps = int(abs(self._position - target) / self._step_size)
            targets = numpy.linspace(self._position, target, _num_steps)

            self.command_active = False
            for pos in targets:
                self._position = pos
                self.set_state(changed=self._position, time=time.time())
                if self._stopped:
                    break
                time.sleep(self._step_time)
        self.set_state(busy=False)

    def move_to(self, pos, wait=False, force=False, **kwargs):
        self.configure(**kwargs)
        if pos == self._position:
            logger.debug("(%s) is already at %s" % (self.name, pos))
            return
        self._move_action(pos)
        if wait:
            self.wait()

    def move_by(self, pos, wait=False, **kwargs):
        self.configure(**kwargs)
        self.move_to(self._position + pos, wait)

    def stop(self):
        self._stopped = True


class Motor(MotorBase):
    """Base Motor object for EPICS based motor records."""

    implements(IMotor)

    def __init__(self, name, **kwargs):
        name_parts = name.split(':')
        units = name_parts[-1]
        self.name_root = ':'.join(name_parts[:-1])
        super(Motor, self).__init__(name, **kwargs)
        self.connect_monitors()

    def connect_monitors(self):
        """
        Connect all pv monitors. Must be implemented in all subclasses
        """
        raise NotImplementedError

    def on_desc(self, pv, val):
        self.description = val

    def on_log(self, obj, message):
        msg = "({}) {}".format(self.name, message)
        logger.debug(msg)

    def get_precision(self):
        return self.PREC.get() or self.default_precision

    def get_position(self):
        val = self.RBV.get()
        val = 0.0001 if val is None else val
        return val

    def move_to(self, pos, wait=False, force=False, **kwargs):
        """Request the motor to move to an absolute position. By default, the 
        command will not be sent to the motor if its current position is the 
        same as the requested position within its preset precision. In addition
        the command will not be sent if the motor health severity is not zero
        (GOOD). 
        
        Args:
            - `pos` (float): Target position to move to.
        
        Kwargs:
            - `wait` (bool): Whether to wait for move to complete or return 
              immediately.
            - `force` (bool): Force a command to be sent to the motor even if the
              target is the same as the current position.        
        """
        # Do not move if motor state is not sane.
        sanity, msg = self.health_state
        if sanity != 0:
            logger.warning("({}) not sane. Reason: '{}'. Move cancelled!".format(self.name, msg))
            return

        # Do not move if requested position is within precision error
        # from current position.
        if self.has_reached(pos):
            logger.debug("({}) is already at {:g}. Move Cancelled!".format(self.name, pos))
            return

        self.command_active = True
        self.target_position = pos
        current_position = self.get_position()
        self.VAL.put(self.target_position)

        logger.debug("({}) moving from {:g} to {:g}".format(self.name, current_position, self.target_position))

        if wait:
            self.wait()

    def move_by(self, val, wait=False, force=False, **kwargs):
        """Similar to :func:`move_to`, except request the motor to move by a 
        relative amount.
        
        Args:
            - `val` (float): amount to move position by.
        
        Kwargs:
            - `wait` (bool): Whether to wait for move to complete or return 
              immediately.
            - `force` (bool): Force a command to be sent to the motor even if the
              target is the same as the current position.        
        """
        if val == 0.0:
            return
        cur_pos = self.get_position()
        self.move_to(cur_pos + val, wait, force)

    def stop(self):
        """Stop the motor from moving."""
        self.STOP.put(1)


class VMEMotor(Motor):
    """CLS "vme" type motors."""

    def __init__(self, name, encoded=False, *args, **kwargs):
        self.use_encoder = encoded
        super(VMEMotor, self).__init__(name, *args, **kwargs)

    def setup(self):
        self.moving_value = 1

        self.VAL = self.add_pv(self.name)
        self.DESC = self.add_pv("{}:desc".format(self.name_root))
        if self.use_encoder:
            self.RBV = self.add_pv("{}:fbk".format(self.name), timed=True)
            self.PREC = self.add_pv("{}:fbk.PREC".format(self.name))
        else:
            self.RBV = self.add_pv("{}:sp".format(self.name), timed=True)
            self.PREC = self.add_pv("{}:sp.PREC".format(self.name))
        self.STAT = self.add_pv("{}:status".format(self.name_root))
        self.MOVN = self.STAT
        self.STOP = self.add_pv("{}:stop".format(self.name_root))
        self.SET = self.add_pv("{}:setPosn".format(self.name))
        self.CALIB = self.add_pv("{}:calibDone".format(self.name_root))
        self.ENAB = self.CALIB
        self.CCW_LIM = self.add_pv("{}:ccw".format(self.name_root))
        self.CW_LIM = self.add_pv("{}:cw".format(self.name_root))

    def connect_monitors(self):
        self.RBV.connect('time', self.notify_change)
        self.VAL.connect('changed', self.notify_target)
        self.MOVN.connect('changed', self.notify_motion)
        self.CALIB.connect('changed', self.notify_calibration)
        self.ENAB.connect('changed', self.notify_enable)
        self.DESC.connect('changed', self.on_desc)


class APSMotor(VMEMotor):
    """"APS" type motor records."""

    def setup(self):
        self.moving_value = 0
        self.calibrated_value = 0
        self.disabled_value = 1

        self.DESC = self.add_pv("{}.DESC".format(self.name))
        self.VAL = self.add_pv("{}.VAL".format(self.name))
        self.PREC = self.add_pv("{}.PREC".format(self.name))
        self.EGU = self.add_pv("{}.EGU".format(self.name))
        self.RBV = self.add_pv("{}.RBV".format(self.name))
        self.MOVN = self.add_pv("{}.DMOV".format(self.name))
        self.STOP = self.add_pv("{}.STOP".format(self.name))
        self.CALIB = self.add_pv("{}.SET".format(self.name))
        self.STAT = self.add_pv("{}.STAT".format(self.name))
        self.ENAB = self.CALIB


class PseudoMotor(VMEMotor):
    """CLS Pseudo Motor."""

    def __init__(self, name, version=2, *args, **kwargs):
        self.version = version
        super(PseudoMotor, self).__init__(name, *args, **kwargs)

    def setup(self):
        self.VAL = self.add_pv(self.name)
        self.DESC = self.add_pv("%s:desc" % (self.name_root))
        self.STAT = self.add_pv("%s:status" % self.name_root)
        self.STOP = self.add_pv("%s:stop" % self.name_root)
        self.CALIB = self.add_pv("%s:calibDone" % self.name_root)
        self.LOG = self.add_pv("%s:log" % self.name_root)
        self.ENAB = self.add_pv("%s:enabled" % (self.name_root))

        if self.version == 2:
            self.moving_value = 1
            self.PREC = self.add_pv("%s:fbk.PREC" % (self.name))
            self.RBV = self.add_pv("%s:fbk" % (self.name), timed=True)
            self.MOVN = self.add_pv("%s:moving" % self.name_root)

        else:
            self.moving_value = 0
            self.PREC = self.add_pv("%s:sp.PREC" % (self.name))
            self.RBV = self.add_pv("%s:sp" % (self.name), timed=True)
            self.MOVN = self.add_pv("%s:stopped" % self.name_root)

    def connect_monitors(self):
        super(PseudoMotor, self).connect_monitors()
        self.LOG.connect('changed', self.on_log)


class JunkEnergyMotor(Motor):
    implements(IMotor)

    def __init__(self, name1, name2, encoder=None, mono_unit_cell=5.4310209, **kwargs):
        self.name1 = name1
        self.name2 = name2
        self.name2_root = ':'.join(name2.split(':')[:-1])
        self.encoder = encoder
        self.mono_unit_cell = mono_unit_cell
        kwargs['units'] = 'keV'
        super(JunkEnergyMotor, self).__init__(self.name1, **kwargs)
        self.description = 'Energy'

    def setup(self):
        self.VAL = self.add_pv(self.name1)
        if self.encoder is not None:
            self.RBV = self.add_pv(self.encoder, timed=True)
            self.PREC = self.add_pv("{}.PREC".format(self.encoder))
        else:
            self.RBV = self.add_pv("{}:sp".format(self.name2), timed=True)
            self.PREC = self.add_pv("{}:sp.PREC".format(self.name2))
        self.MOVN = self.add_pv("{}:moving:fbk".format(self.name1))
        self.STOP = self.add_pv("{}:stop".format(self.name1))
        self.CALIB = self.add_pv("{}:calibDone".format(self.name2_root))
        self.STAT = self.add_pv("{}:status".format(self.name2_root))
        self.LOG = self.add_pv("{}:stsLog".format(self.name1))
        self.ENAB = self.add_pv('{}:enBraggChg'.format(self.name1))  # self.CALIB

    def connect_monitors(self):
        self.RBV.connect('changed', self.notify_change)
        self.VAL.connect('changed', self.notify_target)
        self.MOVN.connect('changed', self.notify_motion)
        self.CALIB.connect('changed', self.notify_calibration)
        self.ENAB.connect('changed', self.notify_enable)
        self.LOG.connect('changed', self.on_log)

    def get_position(self):
        return converter.bragg_to_energy(self.RBV.get(), unit_cell=self.mono_unit_cell)


class BraggEnergyMotor(VMEMotor):

    def __init__(self, name, encoder=None, mono_unit_cell=5.4310209, **kwargs):
        """
        VME Motor for Bragg based Energy
        @param name: PV name
        @param encoder: external encoder if not using internal encoder
        @param mono_unit_cell: Si-111 unti cell parameter
        """
        self.encoder = encoder
        self.mono_unit_cell = mono_unit_cell
        kwargs['units'] = 'keV'
        super(BraggEnergyMotor, self).__init__(name, **kwargs)
        self.description = 'Bragg Energy'

    def get_position(self):
        return converter.bragg_to_energy(self.RBV.get(), unit_cell=self.mono_unit_cell)

    def notify_change(self, obj, value):
        val = converter.bragg_to_energy(value, unit_cell=self.mono_unit_cell)
        self.set_state(time=obj.time_state)  # make sure time is set before changed value
        self.set_state(changed=val)

    def notify_target(self, obj, value):
        pass  # not needed for bragg

    def on_desc(self, pv, val):
        pass  # do not change description

    def move_to(self, pos, wait=False, force=False, **kwargs):
        # Do not move if motor state is not sane.
        sanity, msg = self.health_state
        if sanity != 0:
            logger.warning("({}) not sane. Reason: '{}'. Move cancelled!".format(self.name, msg))
            return

        # Do not move if requested position is within precision error
        # from current position.
        if self.has_reached(pos):
            logger.debug("({}) is already at {:g}. Move Cancelled!".format(self.name, pos))
            return

        self.command_active = True
        self.target_position = pos
        bragg_target = converter.energy_to_bragg(self.target_position, unit_cell=self.mono_unit_cell)
        current_position = self.get_position()
        self.VAL.put(bragg_target)
        self.notify_target(None, self.target_position)

        logger.debug("({}) moving from {:g} to {:g}".format(self.name, current_position, self.target_position))

        if wait:
            self.wait()


class ResolutionMotor(MotorBase):
    def __init__(self, energy, distance, detector_size):
        MotorBase.__init__(self, 'Resolution')
        self.description = 'Max Detector Resolution'
        self.energy = energy
        self.detector_size = detector_size
        self.distance = distance
        self.moving_value = True
        self.energy.connect('changed', self.notify_change)
        self.distance.connect('changed', self.notify_change)

        self.distance.connect('busy', self.notify_motion)
        self.distance.connect('starting', lambda obj, val: self.set_state(starting=val))
        self.distance.connect('done', lambda obj: self.set_state(done=None))

    def setup(self):
        pass  # no process variables needed

    def get_position(self):
        return converter.dist_to_resol(self.distance.get_position(), self.detector_size, self.energy.get_position())

    def move_by(self, val, wait=False, force=False, **kwargs):
        if val == 0.0: return
        self.move_to(val + self.get_position(), wait=wait, force=force)

    def move_to(self, val, wait=False, force=False, **kwargs):
        target = converter.resol_to_dist(val, self.detector_size, self.energy.get_position())
        self.distance.move_to(target, wait=wait, force=force)

    def stop(self):
        self.distance.stop()

    def wait(self, start=True, stop=True):
        self.distance.wait(start=start, stop=stop)
