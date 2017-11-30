import time
from threading import Lock

import numpy
from gi.repository import GObject
from zope.interface import implements

from interfaces import IMotor
from mxdc.com import ca
from mxdc.devices.base import BaseDevice
from mxdc.utils import converter, misc
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

    def __init__(self, name):
        super(MotorBase, self).__init__()
        self.name = name
        self._moving = False
        self._command_sent = False
        self._starting_flag = False
        self._target_pos = 0
        self._prev_target = None
        self._motor_type = 'basic'
        self.units = ''
        self._move_active_value = 1
        self._disabled_value = 0
        self._calib_good_value = 1
        self.default_precision = 2

    def do_starting(self):
        self._starting_flag = True

    def do_done(self):
        self._starting_flag = False

    def do_busy(self, state):
        if self._starting_flag and not state:
            self.set_state(done=None)

    def _signal_change(self, obj, value):
        t = obj.time_state or time.time()
        self.set_state(time=t)
        self.set_state(changed=self.get_position())

    def _signal_target(self, obj, value):
        self.set_state(target=(self._prev_target, value))
        self._prev_target = value

    def _signal_move(self, obj, state):
        if state == self._move_active_value:
            self._moving = True
            if self._command_sent:
                self.set_state(starting=None)
                self._command_sent = False
        else:
            self._moving = False

        self.set_state(busy=self._moving)
        if not self._moving:
            logger.debug("(%s) stopped at %f" % (self.name, self.get_position()))

    def _on_calib_changed(self, obj, cal):
        if cal == self._calib_good_value:
            self.set_state(health=(0, 'calib'))
        else:
            self.set_state(health=(4, 'calib', 'Device Not Calibrated!'))

    def _signal_enable(self, obj, val):
        self.set_state(enabled=(val != self._disabled_value))

    def configure(self, **kwargs):
        pass


class SimMotor(MotorBase):
    implements(IMotor)

    def __init__(self, name, pos=0, units='mm', speed=10.0, active=True, precision=3, health=(0, '')):
        super(SimMotor, self).__init__(name)
        pos = pos

        self.units = units
        self._status = 0
        self._step_time = .001  # 1000 steps per second
        self._stopped = False
        self._enabled = True
        self._command_sent = False
        self._lock = Lock()
        self._active = active
        self._health = health

        self._position = pos
        self._target = None
        self.default_precision = precision
        self.default_speed = speed
        self.configure(speed=speed)
        self.initialize()

    def initialize(self):
        self.set_state(health=self._health, active=self._active)
        self._signal_target(self, self._position)
        self._signal_change(self, self._position)

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
        self._command_sent = True
        with self._lock:
            self.set_state(busy=True)
            self.set_state(target=(self._target, target))
            self._target = target
            _num_steps = int(abs(self._position - target) / self._step_size)
            targets = numpy.linspace(self._position, target, _num_steps)

            self._command_sent = False
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

    def wait(self, start=True, stop=True):
        poll = 0.005
        timeout = 5.0
        _orig_to = timeout
        if start and self._command_sent and not self.busy_state:
            while self._command_sent and not self.busy_state and timeout > 0:
                timeout -= poll
                time.sleep(poll)
            if timeout <= 0:
                logger.warning('(%s) Timed out. Did not move after %d sec.' % (self.name, _orig_to))
                return False
        if (stop and self.busy_state):
            while self.busy_state:
                time.sleep(poll)

    def stop(self):
        self._stopped = True


ENC_SETTINGS = {
    'VEL': '%root:vel:%unitps:sp',
    'VBASE': '%root:vBase:%unitps:sp',
    'ACC': '%root:acc:%unitpss:sp',
    'OFFSET': '%root:%unit:offset',
    'STEP_SLO': '%root:step:slope',
    'STEP_OFF': '%root:step:offset',
    'ENC_SLO': '%root:enc:slope',
    'ENC_OFF': '%root:enc:offset',
}
SAVE_VALS = {
    'UNIT_ENC': '%root:%unit:fbk',
    'STEP_ENC': '%root:enc:fbk',
    'UNIT_VAL': '%root:%unit:sp',
    'STEP_VAL': '%root:step:sp',
}


class Motor(MotorBase):
    """Motor object for EPICS based motor records."""
    implements(IMotor)

    def __init__(self, pv_name, motor_type, precision=4):
        """  
        Args:
            - `pv_name` (str): Root PV name for the EPICS record.
            - `motor_type` (str): Type of EPICS motor record. Accepted values are::
            
               "vme" - CLS VME58 and MaxV motor record without encoder support.
               "vmeenc" - CLS VME58 and MaxV motor record with encoder support.
               "cls" - OLD CLS motor record.
               "pseudo" - CLS PseutoMotor record.
            - `precision` (int): Default value to use for precision if not properly
                set in EPICS
        """
        MotorBase.__init__(self, pv_name)
        pv_parts = pv_name.split(':')
        self.default_precision = precision
        if len(pv_parts) < 2:
            logger.error("Unable to create motor '%s' of dialog_type '%s'." %
                         (pv_name, motor_type))
            raise MotorError("Motor name must be of the format 'name:unit'.")

        if motor_type not in ['vme', 'cls', 'pseudo', 'oldpseudo', 'vmeenc', 'maxv', 'aps']:
            logger.error("Unable to create motor '%s' of dialog_type '%s'." %
                         (pv_name, motor_type))
            raise MotorError("Motor dialog_type must be one of 'vmeenc', \
                'vme', 'cls', 'pseudo', 'maxv'")

        self.units = pv_parts[-1]
        pv_root = ':'.join(pv_parts[:-1])
        self.pv_root = pv_root
        self._motor_type = motor_type

        # initialize process variables based on motor dialog_type
        if self._motor_type in ['vme', 'vmeenc']:
            self.VAL = self.add_pv("%s" % (pv_name))
            self.DESC = self.add_pv("%s:desc" % (pv_root))
            if self._motor_type == 'vme':
                self.RBV = self.add_pv("%s:sp" % (pv_name), timed=True)
                self.PREC = self.add_pv("%s:sp.PREC" % (pv_name))
            else:
                self.RBV = self.add_pv("%s:fbk" % (pv_name), timed=True)
                self.PREC = self.add_pv("%s:fbk.PREC" % (pv_name))
            self.STAT = self.add_pv("%s:status" % pv_root)
            self._move_active_value = 1
            self.MOVN = self.STAT  # self.add_pv("%s:moving" % pv_root)
            self.STOP = self.add_pv("%s:stop" % pv_root)
            self.SET = self.add_pv("%s:setPosn" % (pv_name))
            self.CALIB = self.add_pv("%s:calibDone" % (pv_root))
            self.ENAB = self.CALIB
            self.CCW_LIM = self.add_pv("%s:ccw" % (pv_root))
            self.CW_LIM = self.add_pv("%s:cw" % (pv_root))
        elif self._motor_type == 'cls':
            self.VAL = self.add_pv("%s" % (pv_name))
            self.DESC = self.add_pv("%s:desc" % (pv_root))
            self.PREC = self.add_pv("%s:fbk.PREC" % (pv_name))
            self.RBV = self.add_pv("%s:fbk" % (pv_name), timed=True)
            self.MOVN = self.add_pv("%s:state" % pv_root)
            self.STAT = self.MOVN
            self.STOP = self.add_pv("%s:emergStop" % pv_root)
            self.CALIB = self.add_pv("%s:isCalib" % (pv_root))
            self.ENAB = self.CALIB
        elif self._motor_type == 'pseudo':
            self.VAL = self.add_pv("%s" % (pv_name))
            self.DESC = self.add_pv("%s:desc" % (pv_root))
            self._move_active_value = 1
            self.PREC = self.add_pv("%s:fbk.PREC" % (pv_name))
            self.RBV = self.add_pv("%s:fbk" % (pv_name), timed=True)
            self.STAT = self.add_pv("%s:status" % pv_root)
            self.MOVN = self.add_pv("%s:moving" % pv_root)
            self.STOP = self.add_pv("%s:stop" % pv_root)
            self.CALIB = self.add_pv("%s:calibDone" % pv_root)
            self.LOG = self.add_pv("%s:log" % pv_root)
            self.LOG.connect('changed', self._on_log)
            self.ENAB = self.add_pv("%s:enabled" % (pv_root))
        elif self._motor_type == 'oldpseudo':
            self.VAL = self.add_pv("%s" % (pv_name))
            self.DESC = self.add_pv("%s:desc" % (pv_root))
            self._move_active_value = 0
            self.PREC = self.add_pv("%s:sp.PREC" % (pv_name))
            self.RBV = self.add_pv("%s:sp" % (pv_name), timed=True)
            self.STAT = self.add_pv("%s:status" % pv_root)
            self.MOVN = self.add_pv("%s:stopped" % pv_root)
            self.STOP = self.add_pv("%s:stop" % pv_root)
            self.CALIB = self.add_pv("%s:calibDone" % pv_root)
            self.LOG = self.add_pv("%s:log" % pv_root)
            self.LOG.connect('changed', self._on_log)
            self.ENAB = self.add_pv("%s:enabled" % (pv_root))
        elif self._motor_type == 'aps':
            self.DESC = self.add_pv("%s.DESC" % pv_name)
            self.VAL = self.add_pv('%s.VAL' % pv_name)
            self.PREC = self.add_pv("%s.PREC" % pv_name)
            self.EGU = self.add_pv("%s.EGU" % pv_name)
            self.RBV = self.add_pv("%s.RBV" % pv_name)
            self.MOVN = self.add_pv("%s.DMOV" % pv_name)
            self.STOP = self.add_pv("%s.STOP" % pv_name)
            self.CALIB = self.add_pv("%s.SET" % pv_name)
            self.STAT = self.add_pv("%s.STAT" % pv_name)
            self.ENAB = self.CALIB
            self._move_active_value = 0
            self._calib_good_value = 0
            self._disabled_value = 1

        # connect monitors
        self._rbid = self.RBV.connect('time', self._signal_change)
        self._vid = self.VAL.connect('changed', self._signal_target)

        self.MOVN.connect('changed', self._signal_move)
        self.CALIB.connect('changed', self._on_calib_changed)
        self.ENAB.connect('changed', self._signal_enable)
        self.DESC.connect('changed', self._on_desc_change)

    def _on_desc_change(self, pv, val):
        self.name = val

    def _on_log(self, obj, message):
        msg = "(%s) %s" % (self.name, message)
        logger.debug(msg)

    def get_position(self):
        """Obtain the current position of the motor in devices units.
        
        Returns:
            float.
        """
        try:
            val = self.RBV.get()
        except ca.ChannelAccessError:
            val = 0.0001
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
            logger.warning("(%s) not sane. Reason: '%s'. Move canceled!" % (self.name, msg))
            return

        # Do not move if requested position is within precision error
        # from current position.
        prec = self.PREC.get()
        if prec == 0: prec = self.default_precision
        _pos_format = "%%0.%df" % prec
        _pos_to = _pos_format % pos
        if misc.same_value(pos, self.get_position(), prec, self.units == 'deg') and not force:
            logger.debug("(%s) is already at %s" % (self.name, _pos_to))
            return

        self._command_sent = True
        self._target_pos = pos
        self.VAL.set(pos)
        _pos_from = _pos_format % self.get_position()
        logger.debug("(%s) moving from %s to %s" % (self.name, _pos_from, _pos_to))

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
        self.STOP.set(1)

    def wait(self, start=True, stop=True):
        """Wait for the motor busy state to change. 
        
        Kwargs:
            - `start` (bool): Wait for the motor to start moving.
            - `stop` (bool): Wait for the motor to stop moving.       
        """
        poll = 0.05
        timeout = 5.0

        # initialize precision
        prec = self.PREC.get()
        if prec == 0: prec = self.default_precision
        _pos_format = "%%0.%df" % prec

        if (start and self._command_sent and not self._moving):
            while self._command_sent and not self._moving and timeout > 0:
                timeout -= poll
                time.sleep(poll)
                if misc.same_value(self.get_position(), self._target_pos, prec, self.units == 'deg'):
                    self._command_sent = False
                    logger.debug('%s already at %g' % (self.name, self._target_pos))
            if timeout <= 0:
                tgt = _pos_format % self._target_pos
                cur = _pos_format % self.get_position()
                logger.warning('%s timed out moving to %s [currently %s].' % (self.name, tgt, cur))
                return False
        if (stop and self._moving):
            while self._moving:
                time.sleep(poll)

    # Added for Save/Restore                             
    def get_settings(self):
        """Obtain the motor settings for saving/restore purposes.
        
        Returns:
            A dict.
        """
        self.settings = {}
        PV_DICT = dict(ENC_SETTINGS.items() + SAVE_VALS.items())
        for i in PV_DICT:
            self.settings[i] = self.add_pv(PV_DICT[i].replace('%root', self.pv_root).replace('%unit', self.units))
        return


class VMEMotor(Motor):
    """Convenience class for "vme" type motors."""

    def __init__(self, *args, **kwargs):
        kwargs['motor_type'] = 'vme'
        Motor.__init__(self, *args, **kwargs)


class APSMotor(Motor):
    """Convenience class for "vme" type motors."""

    def __init__(self, *args, **kwargs):
        kwargs['motor_type'] = 'aps'
        Motor.__init__(self, *args, **kwargs)


class ENCMotor(Motor):
    """Convenience class for "vmeenc" type motors."""

    def __init__(self, *args, **kwargs):
        kwargs['motor_type'] = 'vmeenc'
        Motor.__init__(self, *args, **kwargs)


class CLSMotor(Motor):
    """Convenience class for "cls" type motors."""

    def __init__(self, *args, **kwargs):
        kwargs['motor_type'] = 'cls'
        Motor.__init__(self, *args, **kwargs)


class PseudoMotor(Motor):
    """Convenience class for "pseudo" type motors."""

    def __init__(self, *args, **kwargs):
        kwargs['motor_type'] = 'pseudo'
        Motor.__init__(self, *args, **kwargs)


class PseudoMotor2(Motor):
    def __init__(self, *args, **kwargs):
        kwargs['motor_type'] = 'oldpseudo'
        Motor.__init__(self, *args, **kwargs)


class EnergyMotor(Motor):
    implements(IMotor)

    def __init__(self, pv1, pv2, enc=None, mono_unit_cell=5.4310209):
        MotorBase.__init__(self, 'Beamline Energy')
        self.units = 'keV'
        self.mono_unit_cell = mono_unit_cell
        pv2_root = ':'.join(pv2.split(':')[:-1])
        # initialize process variables
        self.VAL = self.add_pv(pv1)
        self.PREC = self.add_pv("%s.PREC" % pv2)
        if enc is not None:
            self.RBV = self.add_pv(enc, timed=True)
            self.PREC = self.add_pv("%s.PREC" % enc)
        else:
            self.RBV = self.add_pv("%s:sp" % pv2, timed=True)
            self.PREC = self.add_pv("%s:sp.PREC" % pv2)
        self.MOVN = self.add_pv("%s:moving:fbk" % pv1)
        self.STOP = self.add_pv("%s:stop" % pv1)
        self.CALIB = self.add_pv("%s:calibDone" % pv2_root)
        self.STAT = self.add_pv("%s:status" % pv2_root)
        self.LOG = self.add_pv("%s:stsLog" % pv1)
        self.ENAB = self.add_pv('{}:enBraggChg'.format(pv1)) #self.CALIB


        # connect monitors
        self._rbid = self.RBV.connect('changed', self._signal_change)
        self._vid = self.VAL.connect('changed', self._signal_target)
        self.MOVN.connect('changed', self._signal_move)
        self.CALIB.connect('changed', self._on_calib_changed)
        self.ENAB.connect('changed', self._signal_enable)
        self.LOG.connect('changed', self._send_log)

    def _send_log(self, obj, msg):
        logger.info("(%s) %s" % (self.name, msg))

    def get_position(self):
        return converter.bragg_to_energy(self.RBV.get(), unit_cell=self.mono_unit_cell)


class BraggEnergyMotor(Motor):
    """A specialized energy motor for using just the monochromator bragg angle."""

    implements(IMotor)

    def __init__(self, name, enc=None, motor_type="vme", precision=3, mono_unit_cell=5.4310209):
        """  
        Args:
            - `name` (str): Root PV name of motor record.
        
        Kwargs:
            - `enc` (str): PV name for an optional encoder feedback value from
              which to read the energy value.
            - `motor_type` (str): Type of EPICS motor record. Accepted values are::
        
               "vme" - CLS VME58 and MaxV motor record without encoder support.
               "vmeenc" - CLS VME58 and MaxV motor record with encoder support.
               "cls" - OLD CLS motor record.
               "pseudo" - CLS PseutoMotor record.
            - `precision` (int)
        """
        Motor.__init__(self, name, motor_type=motor_type, precision=precision)
        del self.DESC
        if enc is not None:
            del self.RBV
            self.RBV = self.add_pv(enc, timed=True)
            GObject.source_remove(self._rbid)
            self.RBV.connect('changed', self._signal_change)
        GObject.source_remove(self._vid)  # Not needed for Bragg
        self.name = 'Bragg Energy'
        self._motor_type = 'vmeenc'
        self.mono_unit_cell = mono_unit_cell

    def _on_desc_change(self, pv, val):
        pass

    def get_position(self):
        return converter.bragg_to_energy(self.RBV.get(), unit_cell=self.mono_unit_cell)

    def _signal_change(self, obj, value):
        val = converter.bragg_to_energy(value, unit_cell=self.mono_unit_cell)
        self.set_state(time=obj.time_state)  # make sure time is set before changed value
        self.set_state(changed=val)

    def move_to(self, pos, wait=False, force=False, **kwargs):
        # Do not move if motor state is not sane.
        sanity, msg = self.health_state
        if sanity != 0:
            logger.warning("(%s) not sane. Reason: '%s'. Move canceled!" % (self.name, msg))
            return

        # Do not move if requested position is within precision error
        # from current position.
        prec = self.PREC.get()
        if prec == 0: prec = self.default_precision
        _pos_format = "%%0.%df" % prec
        _pos_to = _pos_format % pos
        if misc.same_value(pos, self.get_position(), prec, self.units == 'deg') and not force:
            logger.debug("(%s) is already at %s" % (self.name, _pos_to))
            return

        deg_target = converter.energy_to_bragg(pos, unit_cell=self.mono_unit_cell)
        self._command_sent = True
        self._target_pos = pos
        self.VAL.put(deg_target)
        self._signal_target(None, pos)
        logger.info("(%s) moving to %f" % (self.name, pos))

        if wait:
            self.wait()


class FixedLine2Motor(MotorBase):
    """A specialized fixed offset pseudo-motor for moving two motors along a 
    straight line."""

    def __init__(self, x, y, slope, intercept, linked=False):
        """  
        Args:
            - `x` (:class:`MotorBase`): x-axis motor.
            - `y` (:class:`MotorBase`): y-axis motor.
            - `slope` (float): slope of the line.
            - `intercept` (float): y-intercept of the line.
        
        Kwargs:
            - `linked` (bool): Whether the two motors are linked. Two motors are 
              linked if they can not be moved at the same time.
        
        """
        MotorBase.__init__(self, 'FixedOffset')
        self.y = y
        self.x = x
        self.add_devices(self.x, self.y)
        self.linked = linked
        self.slope = slope
        self.intercept = intercept
        self.y.connect('changed', self._signal_change)

    def __repr__(self):
        return '<FixedLine2Motor: \n\t%s,\n\t%s,\n\tslope=%0.2f, intercept=%0.2f\n>' % (
        self.x, self.y, self.slope, self.intercept)

    def get_position(self):
        """Obtain the position of the `x` motor only."""
        return self.x.get_position()

    def move_to(self, pos, wait=False, force=False, **kwargs):
        px = pos
        self.x.move_to(px, force=force)
        if self.linked:
            self.x.wait(start=True, stop=True)
        py = self.intercept + self.slope * px
        self.y.move_to(py, force=force)
        if wait:
            self.wait()

    def move_by(self, val, wait=False, force=False, **kwargs):
        if val == 0.0:
            return
        cur_pos = self.get_position()
        self.move_to(cur_pos + val, wait, force)

    def is_enabled(self):
        return self.x.is_enabled() and self.y.is_enabled()

    def stop(self):
        self.x.stop()
        self.y.stop()

    def wait(self, start=True, stop=True):
        self.x.wait(start=start, stop=False)
        self.y.wait(start=start, stop=False)
        self.x.wait(start=False, stop=stop)
        self.y.wait(start=False, stop=stop)


class RelVerticalMotor(MotorBase):
    """A specialized pseudo-motor for moving an x-y stage attached to a 
    rotating axis vertically. Such as a centering table attached to a goniometer.
    The current position is always zero and all moves are relative."""

    def __init__(self, y1, y2, omega, offset=0.0):
        """  
        Args:
            - `y1` (:class:`MotorBase`): The first motor which moves 
              vertically when the angle of the 
                axis is at zero.              
            - `y2` (:class:`MotorBase`): The second motor which moves 
              horizontally when the angle of the axis is at zero.             
            - `omega` (:class:`MotorBase`): The motor for the rotation axis.
        
        Kwargs:
            - `offset` (float): An angle correction to apply to the rotation 
              axis position to make `y1` vertical.
        """
        MotorBase.__init__(self, 'Relative Vertical')
        self.y1 = y1
        self.y2 = y2
        self.omega = omega
        self.offset = offset
        self._status = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.add_devices(self.y1, self.y2, self.omega)
        self.y1.connect('changed', self._calc_position)
        self.y2.connect('changed', self._calc_position)
        self.omega.connect('changed', self._calc_position)

    def __repr__(self):
        return '<RelVerticalMotor: %s, %s >' % (self.y1, self.y2)

    def _calc_position(self, obj, val):
        tmp_omega = numpy.radians(self.omega.get_position() - self.offset)
        sin_w = numpy.sin(tmp_omega)
        cos_w = numpy.cos(tmp_omega)
        y1 = self.y1.get_position() * sin_w
        y2 = self.y2.get_position() * cos_w
        z1 = self.y1.get_position() * cos_w
        z2 = -self.y1.get_position() * sin_w
        self._status = (y1 + y2, z1 + z2, y1, y2, z1, z2)
        self.set_state(changed=self._status[0])
        # logger.debug('SAMPLE STAGE Y: %0.4f, Z: %0.4f' % (self._status[0], self._status[1]))

    def get_position(self):
        return self._status[0]

    def move_by(self, val, wait=False, force=False, **kwargs):
        if val == 0.0: return
        tmp_omega = numpy.radians(self.omega.get_position() - self.offset)
        sin_w = numpy.sin(tmp_omega)
        cos_w = numpy.cos(tmp_omega)
        self.y1.move_by(val * sin_w)
        self.y2.move_by(val * cos_w)
        if wait:
            self.wait()

    def move_to(self, val, wait=False, force=False, **kwargs):
        relval = val - self.get_position()
        self.move_by(relval, wait=wait, force=force)

    def stop(self):
        self.y2.stop()
        self.y1.stop()

    def wait(self, start=True, stop=True):
        self.y2.wait(start=start, stop=False)
        self.y1.wait(start=start, stop=False)
        self.y2.wait(start=False, stop=stop)
        self.y1.wait(start=False, stop=stop)


class ResolutionMotor(MotorBase):
    def __init__(self, energy, distance, detector_size):
        MotorBase.__init__(self, 'Max Detector Resolution')
        self.energy = energy
        self.detector_size = detector_size
        self.distance = distance
        self.energy.connect('changed', self.on_update_pos)
        self.distance.connect('changed', self.on_update_pos)

        self.distance.connect('busy', lambda obj, val: self.set_state(busy=val))
        self.distance.connect('starting', lambda obj, val: self.set_state(starting=val))
        self.distance.connect('done', lambda obj: self.set_state(done=None))

    def on_update_pos(self, obj, val):
        pos = self.get_position()
        self.set_state(changed=self.get_position(), time=obj.time_state)

    def on_busy(self, obj, val):
        self.set_state(busy=val)

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
