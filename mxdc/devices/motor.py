import time
from threading import Lock

import numpy
from zope.interface import implementer

from mxdc import Signal, Device
from mxdc.utils import converter
from mxdc.utils.decorators import async_call
from mxdc.utils.log import get_module_logger
from .interfaces import IMotor

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class MotorError(Exception):
    """
    Base class for errors in the motor module.
    """


@implementer(IMotor)
class MotorBase(Device):
    """
    Base class for motors.
    
    Signals:
        changed: float, Emitted everytime the position of the motor changes.
          Data contains the current position of the motor.
        target: float, Emitted everytime the requested position of the motor changes.
          Data is a tuple containing the previous set point and the current one.
          Data is a 2-tuple with the current position and the timestamp of the last change.
        starting: bool, Emitted when this a command to move has been accepted by this instance of the motor.
    """

    # Motor signals
    class Signals:
        changed = Signal("changed", arg_types=(float,))
        starting = Signal("starting", arg_types=(bool,))
        target = Signal("target", arg_types=(object, float))
        done = Signal("done", arg_types=())

    def __init__(self, name, *args, precision=2, units=''):
        super().__init__()
        self.name = name
        self.description = name
        self.target_position = 0
        self.previous_position = None
        self.target_master = False  # tracks whether motion was requested from this client

        self.position = None
        self.targets = (None, None)
        self.units = units
        self.precision = precision

        self.moving_value = 1
        self.disabled_value = 0
        self.calibrated_value = 1
        self.setup()

    def setup(self):
        """
        Prepare all the components of the motor when it is started.
        """

    def is_starting(self):
        """
        Check if motor is starting, ie a command has been received but has not yet started moving.

        :return: True if starting, False otherwise
        """
        return self.get_state("starting")

    def is_moving(self):
        """
        Check if motor is moving, ie a command has been received.

        :return: True if moving, False otherwise
        """
        return self.get_state("busy")

    def move_to(self, pos, wait=False, force=False, **kwargs):
        """
        Move to an absolute position.

        :param pos: Target position
        :param wait: Block until move is done, default is non-blocking
        :param force: Force move even if already at current position
        :param kwargs: Additional options for the move
        """

        severity, context, message = self.get_state("health")
        if severity:
            logger.warning("'{}' Move Cancelled! Reason: '{}'.".format(self.name, message))
            return

        # Do not move if requested position is within precision error
        # from current position.
        if self.has_reached(pos) and not force:
            logger.debug("'{}' Move Cancelled! Already at {:g}.".format(self.name, pos))
            return

        self.set_state(starting=True)
        self.target_position = pos
        cur_pos = self.get_position()
        self.move_operation(self.target_position)

        logger.debug("'{}' moving from {:g} to {:g}".format(self.name, cur_pos, self.target_position))

        if wait:
            self.wait()

    def move_by(self, value, wait=False, force=False, **kwargs):
        """
        Similar to :func:`move_to`, except request the motor to move by a
        relative amount.

        :param value: Relative amount to move position by
        :param wait: Whether to block until move is completed or not
        :param force: Force move even if already at current position
        :param kwargs: Additional options for the move
        """
        if value == 0.0:
            return
        cur_pos = self.get_position()
        self.move_to(cur_pos + value, wait, force)

    def move_operation(self, target):
        """
        Raw move operation command. Moves the motor to the absolute position. Warning: this method sends the command
        directy to the device without additional checks. Should not be used directly without additional checks.
        Subclasses must implement this method.

        :param target: Absolute position to move to.
        """
        raise NotImplementedError('Sub-classes must implement this method!')

    def do_busy(self, busy):
        """
        Busy closure

        :param state: busy state
        """
        if self.is_starting() and busy:
            self.target_master = True
            self.set_state(starting=False)
        elif not busy and self.target_master:
            self.set_state("done")
            self.target_master = False

    # general notification callbacks
    def on_change(self, obj, value):
        """
        Callback to Emit "changed" signals when the motor position changes

        :param obj: process variable object
        :param value: value of process variable
        """
        self.position = self.get_position()
        self.set_state(changed=self.position)

    def on_target(self, obj, value):
        """
        Callback to emit "target" signal when the motor target is changed.

        :param obj: process variable object
        :param value: value of process variable
        """
        self.targets = (self.targets + (value,))[-2:]
        self.set_state(target=(self.previous_position, value))
        self.previous_position = value

    def on_motion(self, obj, value):
        """
        Callback to emit "starting" and "busy" signal when the motor starts moving.

        :param obj: process variable object
        :param value: value of process variable
        """
        moving = (value == self.moving_value)
        self.set_state(busy=moving)

        if not moving:
            logger.debug("'{}' stopped at {:g}".format(self.name, self.get_position()))

    def on_calibration(self, obj, state):
        """
        Callback to emit "health" signal changes when the motor calibration changes.

        :param obj: process variable object
        :param value: value of process variable
        """

        if state == self.calibrated_value:
            self.set_state(health=(0, 'calib', ''))
        else:
            self.set_state(health=(4, 'calib', 'Not Calibrated!'))

    def on_enable(self, obj, val):
        """
        Callback to emit "enabled" signal when the motor-enabled state is changed.

        :param obj: process variable object
        :param value: value of process variable
        """
        self.set_state(enabled=(val != self.disabled_value))

    # main motor utility interface methods
    def has_reached(self, value):
        """
        Check if the motor has reached a given position.

        :param value: query position
        :return: (boolean)
        """
        current = self.get_position()
        if self.units == 'deg':
            value = value % 360.0
            current = current % 360.0
        return abs(round(current - value, self.precision)) <= 10 ** - self.precision

    def wait_start(self, timeout=2, poll=0.05):
        """
        Wait for motor to start moving
        :param timeout: Maximum time to wait before failing
        :param poll: Time step between checking motor state
        :return: (boolean), True if motor started successfully
        """
        if self.is_starting() and not self.is_busy():
            logger.debug('Waiting for {} to start '.format(self.name))
            elapsed = 0
            while self.is_starting() and not self.is_busy() and elapsed < timeout:
                elapsed += poll
                time.sleep(poll)
                if self.has_reached(self.target_position):
                    logger.debug('{} already at {:g}'.format(self.name, self.target_position))
            if elapsed >= timeout:
                logger.warning('"{}" Timed out. Did not move after {:g} sec.'.format(self.name, elapsed))
                return False
        return True

    def wait_stop(self, target=None, timeout=120, poll=0.05):
        """
        Wait for motor to stop moving.

        :param target: Optional target to check
        :param timeout: Maximum time to wait before failing
        :param poll: Time step between checking motor state
        :return: (boolean), True if motor stopped successfully or if it is not moving.
        """
        elapsed = 0
        if target is not None:
            logger.debug('Waiting for {} to reach {:g}.'.format(self.name, target))
            while (self.is_busy() or not self.has_reached(target)) and elapsed < timeout:
                elapsed += poll
                time.sleep(poll)

            if elapsed >= timeout:
                logger.warning(
                    '"{}" Timed-out. Did not reach {:g} after {:g} sec.'.format(
                        self.name, self.target_position, elapsed)
                )
                return False
        else:
            logger.debug('Waiting for {} to stop '.format(self.name))
            while self.is_busy() and elapsed < timeout:
                elapsed += poll
                time.sleep(poll)
            if elapsed >= timeout:
                logger.warning(
                    '"{}" Timed-out. Did not stop moving after {:d} sec.'.format(self.name, elapsed)
                )
                return False
        return True

    def wait(self, start=True, stop=True):
        """
        Wait for the motor busy state to change.

        :param start: (bool) Wait for the motor to start moving.
        :param stop: (bool): Wait for the motor to stop moving.
        :return: (bool), True if successful
        """
        success = True
        if start:
            success &= self.wait_start()
        if stop:
            success &= self.wait_stop()
        return success


@implementer(IMotor)
class SimMotor(MotorBase):

    def __init__(self, name, pos=0, units='mm', speed=5.0, active=True, precision=3, health=(0, '', '')):
        super().__init__(name, precision=precision, units=units)
        self.default_speed = speed

        self._status = 0
        self._step_time = .01  # 100 steps per second
        self._stopped = False
        self._lock = Lock()
        self._active = active
        self._health = health
        self._position = pos
        self._target = pos

        self.configure(speed=speed)
        self.initialize()

    def setup(self):
        pass

    def initialize(self):
        self.set_state(health=self._health, active=self._active, enabled=True)
        self.on_target(self, self._position)
        self.on_change(self, self._position)

    def get_position(self):
        return self._position

    def get_speed(self):
        return self._speed

    def configure(self, *args, **kwargs):
        with self._lock:
            if 'speed' in kwargs:
                self._speed = kwargs['speed']  # speed
                self._step_size = self._speed * self._step_time

    @async_call
    def move_operation(self, target):
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
                self.set_state(changed=self._position)
                if self._stopped:
                    break
                time.sleep(self._step_time)
        self.set_state(busy=False)

    def stop(self):
        self._stopped = True


@implementer(IMotor)
class Motor(MotorBase):
    """Base Motor object for EPICS based motor records."""

    def __init__(self, name, *args, **kwargs):
        name_parts = name.split(':')
        units = name_parts[-1]
        self.name_root = ':'.join(name_parts[:-1])
        super().__init__(name, *args, **kwargs)
        self.connect_monitors()

    def connect_monitors(self):
        """
        Connect all pv monitors. Must be implemented in all subclasses
        """
        raise NotImplementedError

    def on_desc(self, obj, descr):
        self.description = descr

    def on_log(self, obj, message):
        msg = "'{}' {}".format(self.name, message)
        logger.debug(msg)

    def on_precision(self, obj, prec):
        self.precision = prec

    def get_position(self):
        val = self.RBV.get()
        val = 0.0001 if val is None else val
        return val

    def move_operation(self, target):
        self.VAL.put(target)

    def stop(self):
        """
        Stop the motor from moving.
        """
        self.STOP.put(1)

    def setup(self):
        pass


class VMEMotor(Motor):
    """CLS "vme" type motors."""

    def __init__(self, name, encoded=False, *args, **kwargs):
        self.use_encoder = encoded
        super().__init__(name, *args, **kwargs)

    def setup(self):
        self.moving_value = 1

        self.VAL = self.add_pv(self.name)
        self.DESC = self.add_pv("{}:desc".format(self.name_root))
        if self.use_encoder:
            self.RBV = self.add_pv("{}:fbk".format(self.name))
            self.PREC = self.add_pv("{}:fbk.PREC".format(self.name))
        else:
            self.RBV = self.add_pv("{}:sp".format(self.name))
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
        self.VAL.connect('changed', self.on_target)
        self.MOVN.connect('changed', self.on_motion)
        self.CALIB.connect('changed', self.on_calibration)
        self.ENAB.connect('changed', self.on_enable)
        self.DESC.connect('changed', self.on_desc)
        self.PREC.connect('changed', self.on_precision)


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


class CLSMotor(VMEMotor):
    """Ancient CLS type motor records."""

    def setup(self):
        self.moving_value = 4
        self.calibrated_value = 1
        self.disabled_value = 0

        self.DESC = self.add_pv("{}:desc".format(self.name_root))
        self.VAL = self.add_pv("{}".format(self.name))
        self.PREC = self.add_pv("{}.PREC".format(self.name))
        self.EGU = self.add_pv("{}.EGU".format(self.name))
        self.RBV = self.add_pv("{}:fbk".format(self.name))
        self.MOVN = self.add_pv("{}:state".format(self.name_root))
        self.STOP = self.add_pv("{}:emergStop".format(self.name_root))
        self.CALIB = self.add_pv("{}:isCalib".format(self.name_root))
        self.STAT = self.add_pv("{}:state".format(self.name_root))
        self.ENAB = self.CALIB


class PseudoMotor(VMEMotor):
    """CLS Pseudo Motor."""

    def __init__(self, name, version=2, *args, **kwargs):
        self.version = version
        super().__init__(name, *args, **kwargs)

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
            self.RBV = self.add_pv("%s:fbk" % (self.name))
            self.MOVN = self.add_pv("%s:moving" % self.name_root)

        else:
            self.moving_value = 0
            self.PREC = self.add_pv("%s:sp.PREC" % (self.name))
            self.RBV = self.add_pv("%s:sp" % (self.name))
            self.MOVN = self.add_pv("%s:stopped" % self.name_root)

    def connect_monitors(self):
        super().connect_monitors()
        self.LOG.connect('changed', self.on_log)


@implementer(IMotor)
class JunkEnergyMotor(Motor):

    def __init__(self, name1, name2, encoder=None, mono_unit_cell=5.4310209, **kwargs):
        self.name1 = name1
        self.name2 = name2
        self.name2_root = ':'.join(name2.split(':')[:-1])
        self.encoder = encoder
        self.mono_unit_cell = mono_unit_cell
        kwargs['units'] = 'keV'
        super().__init__(self.name1, **kwargs)
        self.description = 'Energy'

    def setup(self):
        self.VAL = self.add_pv(self.name1)
        if self.encoder is not None:
            self.RBV = self.add_pv(self.encoder)
            self.PREC = self.add_pv("{}.PREC".format(self.encoder))
        else:
            self.RBV = self.add_pv("{}:sp".format(self.name2))
            self.PREC = self.add_pv("{}:sp.PREC".format(self.name2))
        self.MOVN = self.add_pv("{}:moving:fbk".format(self.name1))
        self.STOP = self.add_pv("{}:stop".format(self.name1))
        self.CALIB = self.add_pv("{}:calibDone".format(self.name2_root))
        self.STAT = self.add_pv("{}:status".format(self.name2_root))
        self.LOG = self.add_pv("{}:stsLog".format(self.name1))
        self.ENAB = self.add_pv('{}:enBraggChg'.format(self.name1))  # self.CALIB

    def connect_monitors(self):
        self.RBV.connect('changed', self.on_change)
        self.VAL.connect('changed', self.on_target)
        self.MOVN.connect('changed', self.on_motion)
        self.CALIB.connect('changed', self.on_calibration)
        self.ENAB.connect('changed', self.on_enable)
        self.LOG.connect('changed', self.on_log)

    def get_position(self):
        return converter.bragg_to_energy(self.RBV.get(), unit_cell=self.mono_unit_cell)


class BraggEnergyMotor(VMEMotor):

    def __init__(self, name, encoder=None, mono_unit_cell=5.4310209, fixed_lo=2.0, fixed_hi=2.1, fixed_value=8.157,
                 **kwargs):
        """
        VME Motor for Bragg based Energy

        :param name: PV name
        :param encoder: external encoder if not using internal encoder
        :param mono_unit_cell: Si-111 unit cell parameter
        """
        self.encoder = encoder
        self.mono_unit_cell = mono_unit_cell
        self.fixed_lo, self.fixed_hi = fixed_lo, fixed_hi
        self.fixed_value = fixed_value
        kwargs['units'] = 'keV'
        super().__init__(name, **kwargs)
        self.description = 'Bragg Energy'

    def convert(self, value):
        if self.fixed_hi > value > self.fixed_lo:
            return self.fixed_value
        else:
            return converter.bragg_to_energy(value, unit_cell=self.mono_unit_cell)

    def get_position(self):
        return self.convert(self.RBV.get())

    def on_target(self, obj, value):
        pass  # not needed for bragg

    def on_desc(self, pv, val):
        pass  # do not change description

    def move_operation(self, target):
        bragg_target = converter.energy_to_bragg(target, unit_cell=self.mono_unit_cell)
        self.VAL.put(bragg_target)


class ResolutionMotor(MotorBase):
    def __init__(self, energy, distance, detector_size):
        super().__init__('Resolution')
        self.description = 'Max Detector Resolution'
        self.energy = energy
        self.detector_size = detector_size
        self.distance = distance

        self.energy.connect('changed', self.on_change)
        self.distance.connect('changed', self.on_change)
        self.distance.connect('busy', self.on_motion)
        self.distance.connect('starting', self.on_starting)

    def get_position(self):
        return converter.dist_to_resol(self.distance.get_position(), self.detector_size, self.energy.get_position())

    def move_operation(self, target):
        dist_target = converter.resol_to_dist(target, self.detector_size, self.energy.get_position())
        self.distance.move_operation(dist_target)

    def stop(self):
        self.distance.stop()

    def on_starting(self, obj, value):
        starting = self.distance.is_starting() or self.energy.is_starting()
        self.set_state(starting=starting)

    def on_motion(self, obj, value):
        moving = self.distance.is_moving() or self.energy.is_moving()
        self.set_state(busy=moving)
