from bcm.device.base import BaseDevice
from bcm.device.interfaces import IMotor
from bcm.utils import converter, misc
from bcm.utils.decorators import async
from bcm.utils.log import get_module_logger
from zope.interface import implements
from bcm.protocol import ca
import gobject
import numpy
import time

# setup module logger with a default do-nothing handler
_logger = get_module_logger('devices')


class MotorError(Exception):
    """Base class for errors in the motor module."""


class MotorBase(BaseDevice):
    """Base class for motors.
    
    Signals:
        - `changed` (float): Emitted everytime the position of the motor changes.
          Data contains the current position of the motor.
        - `target-changed` (float): Emitted everytime the requested position of the motor changes.
          Data is a tuple containing the previous set point and the current one.
        - `timed-change` (tuple(float, float)): Emitted everytime the motor changes.
          Data is a 2-tuple with the current position and the timestamp of the last change.
        - `starting` (None): Emitted when this a command to move has been accepted by this instance of the motor.
        - `done` (None): Emitted within the instance when a commanded move has completed.
    """
    implements(IMotor)

    # Motor signals
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "starting": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, []),
        "done": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, []),
        "target-changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),        
        "timed-change": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        }  

    def __init__(self, name):
        BaseDevice.__init__(self)
        #self.set_state(changed=0.0)
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
        
    def do_changed(self, st):
        pass
    
    def do_timed_change(self, st):
        pass
    
    def do_starting(self):
        self._starting_flag = True
    
    def do_done(self):
        self._starting_flag = False

    def do_busy(self, st):
        if self._starting_flag and not st:
            self.set_state(done=None)

    def _signal_change(self, obj, value):
        self.set_state(changed=self.get_position())

    def _signal_target(self, obj, value):
        self.set_state(target_changed=(self._prev_target, value))
        self._prev_target = value

    def _signal_timed_change(self, obj, data):
        self.set_state(timed_change=data, changed=data[0])
    
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
            _logger.debug( "(%s) stopped at %f" % (self.name, self.get_position()) )
                       
    def _on_calib_changed(self, obj, cal):
        if cal == self._calib_good_value:
            self.set_state(health=(0, 'calib'))
        else:
            self.set_state(health=(2, 'calib', 'Device Not Calibrated!'))

    def _signal_enable(self, obj, val):
        if val == self._disabled_value:
            if not self.is_busy():
                self.set_state(health=(16, 'disabled', 'Device disabled!'))
        else:
            self.set_state(health=(0, 'disabled'))

    def configure(self, **kwargs):
        pass
                                            

class SimMotor(MotorBase):
    implements(IMotor)
     
    def __init__(self, name, pos=0, units='mm', speed=10.0, active=True, precision=3):
        MotorBase.__init__(self,name)
        pos = pos
        self._set_speed(speed)
        self.units = units
        self._state = 0
        self._stopped = False
        self._enabled = True
        self._command_sent = False
        self.set_state(health=(0,''), active=active, changed=pos)
        self._position = pos
        self._target = None
        self.default_precision = precision
        
    def get_position(self):
        return self._position
    
    def _set_speed(self, val):
        self._speed = val # speed
        self._steps_per_second = 20
        self._stepsize = self._speed/self._steps_per_second
        
    @async
    def _move_action(self, target):
        self._stopped = False
        self._command_sent = True
        import numpy
        self.set_state(target_changed=(self._target, target))
        self._target = target
        _num_steps = max(5, int(abs(self._position - target)/self._stepsize))
        targets = numpy.linspace(self._position, target, _num_steps)
        self.set_state(busy=True)
        self._command_sent = False
        for pos in targets:
            self._position = pos
            data = (pos, time.time())
            self._signal_timed_change(self, data)
            if self._stopped:
                break
            time.sleep(1.0/self._steps_per_second)
        self.set_state(busy=False)

            
    def move_to(self, pos, wait=False, force=False):
        if pos == self._position:
            _logger.debug( "(%s) is already at %s" % (self.name, pos) )
            return
        self._move_action(pos)
        if wait:
            self.wait()
    
    def move_by(self, pos, wait=False):
        self.move_to(self._position+pos, wait)
    
    def wait(self, start=True, stop=True):
        poll=0.01
        timeout = 5.0
        _orig_to = timeout
        if (start and self._command_sent and not self.busy_state):
            _logger.debug('(%s) Waiting to start moving' % (self.name,))
            while self._command_sent and not self.busy_state and timeout > 0:
                timeout -= poll
                time.sleep(poll)
            if timeout <= 0:
                _logger.warning('(%s) Timed out. Did not move after %d sec.' % (self.name, _orig_to))
                return False                
        if (stop and self.busy_state):
            _logger.debug('(%s) Waiting to stop moving' % (self.name,))
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
        if len(pv_parts)<2:
            _logger.error("Unable to create motor '%s' of dialog_type '%s'." %
                             (pv_name, motor_type) )
            raise MotorError("Motor name must be of the format 'name:unit'.")
        
        if motor_type not in ['vme', 'cls', 'pseudo', 'oldpseudo', 'vmeenc', 'maxv', 'aps']:
            _logger.error("Unable to create motor '%s' of dialog_type '%s'." %
                             (pv_name, motor_type) )
            raise MotorError("Motor dialog_type must be one of 'vmeenc', \
                'vme', 'cls', 'pseudo', 'maxv'")
          
        self.units = pv_parts[-1]
        pv_root = ':'.join(pv_parts[:-1])
        self.pv_root = pv_root
        self._motor_type = motor_type
        
        # initialize process variables based on motor dialog_type
        if self._motor_type in ['vme','vmeenc']:
            self.VAL  = self.add_pv("%s" % (pv_name))
            self.DESC = self.add_pv("%s:desc" % (pv_root))               
            if self._motor_type == 'vme':
                self.RBV  = self.add_pv("%s:sp" % (pv_name), timed=True)
                self.PREC =    self.add_pv("%s:sp.PREC" % (pv_name))
            else:
                self.RBV  = self.add_pv("%s:fbk" % (pv_name), timed=True)
                self.PREC =    self.add_pv("%s:fbk.PREC" % (pv_name))
            self.STAT = self.add_pv("%s:status" % pv_root)
            self._move_active_value = 1
            self.MOVN = self.STAT #self.add_pv("%s:moving" % pv_root)
            self.STOP = self.add_pv("%s:stop" % pv_root)
            self.SET  = self.add_pv("%s:setPosn" % (pv_name))
            self.CALIB = self.add_pv("%s:calibDone" % (pv_root))
            self.ENAB = self.CALIB
            self.CCW_LIM = self.add_pv("%s:ccw" % (pv_root))
            self.CW_LIM = self.add_pv("%s:cw" % (pv_root))
        elif self._motor_type == 'cls':
            self.VAL  = self.add_pv("%s" % (pv_name))
            self.DESC = self.add_pv("%s:desc" % (pv_root))               
            self.PREC =    self.add_pv("%s:fbk.PREC" % (pv_name))
            self.RBV  = self.add_pv("%s:fbk" % (pv_name), timed=True)
            self.MOVN = self.add_pv("%s:state" % pv_root)
            self.STAT = self.MOVN
            self.STOP = self.add_pv("%s:emergStop" % pv_root)
            self.CALIB = self.add_pv("%s:isCalib" % (pv_root))
            self.ENAB = self.CALIB
        elif self._motor_type == 'pseudo':
            self.VAL  = self.add_pv("%s" % (pv_name))
            self.DESC = self.add_pv("%s:desc" % (pv_root))               
            self._move_active_value = 1
            self.PREC =    self.add_pv("%s:fbk.PREC" % (pv_name))
            self.RBV  = self.add_pv("%s:fbk" % (pv_name), timed=True)
            self.STAT = self.add_pv("%s:status" % pv_root)
            self.MOVN = self.add_pv("%s:moving" % pv_root)
            self.STOP = self.add_pv("%s:stop" % pv_root)
            self.CALIB = self.add_pv("%s:calibDone" % pv_root)
            self.LOG = self.add_pv("%s:log" % pv_root)
            self.LOG.connect('changed', self._on_log)
            self.ENAB = self.add_pv("%s:enabled" % (pv_root))
        elif self._motor_type == 'oldpseudo':
            self.VAL  = self.add_pv("%s" % (pv_name))
            self.DESC = self.add_pv("%s:desc" % (pv_root))               
            self._move_active_value = 0
            self.PREC =    self.add_pv("%s:sp.PREC" % (pv_name))
            self.RBV  = self.add_pv("%s:sp" % (pv_name), timed=True)
            self.STAT = self.add_pv("%s:status" % pv_root)
            self.MOVN = self.add_pv("%s:stopped" % pv_root)
            self.STOP = self.add_pv("%s:stop" % pv_root)
            self.CALIB = self.add_pv("%s:calibDone" % pv_root)
            self.LOG = self.add_pv("%s:log" % pv_root)
            self.LOG.connect('changed', self._on_log)
            self.ENAB = self.add_pv("%s:enabled" % (pv_root))
        elif self._motor_type == 'aps':
            self.DESC = self.add_pv("%s.DESC" % pv_name)               
            self.VAL  = self.add_pv('%s.VAL' % pv_name)    
            self.PREC = self.add_pv("%s.PREC" % pv_name)
            self.EGU = self.add_pv("%s.EGU"% pv_name)  
            self.RBV = self.add_pv("%s.RBV"% pv_name)
            self.MOVN = self.add_pv("%s.DMOV" % pv_name)
            self.STOP = self.add_pv("%s.STOP" % pv_name)
            self.CALIB =  self.add_pv("%s.SET" % pv_name)
            self.STAT =  self.add_pv("%s.STAT" % pv_name)
            self.ENAB = self.CALIB
            self._move_active_value = 0
            self._calib_good_value = 0
            self._disabled_value = 1
            
                     
        # connect monitors
        self._rbid = self.RBV.connect('timed-change', self._signal_timed_change)
        self._vid = self.VAL.connect('changed', self._signal_target)

        self.MOVN.connect('changed', self._signal_move)
        self.CALIB.connect('changed', self._on_calib_changed)
        self.ENAB.connect('changed', self._signal_enable)
        self.DESC.connect('changed', self._on_desc_change)
            
    def _on_desc_change(self, pv, val):
        self.name = val

    def _on_log(self, obj, message):
        msg = "(%s) %s" % (self.name, message)
        _logger.debug(msg)
                                            
    def get_position(self):
        """Obtain the current position of the motor in device units.
        
        Returns:
            float.
        """
        try:
            val = self.RBV.get()
        except ca.ChannelAccessError:
            val = 0.0001
        return val
              
    def move_to(self, pos, wait=False, force=False):
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
            _logger.warning( "(%s) not sane. Reason: '%s'. Move canceled!" % (self.name,msg) )
            return
        
        # Do not move if requested position is within precision error
        # from current position.
        prec = self.PREC.get()
        if prec == 0: prec = self.default_precision
        _pos_format = "%%0.%df" % prec
        _pos_to = _pos_format % pos
        if misc.same_value(pos, self.get_position(), prec, self.units=='deg') and not force:
            _logger.debug( "(%s) is already at %s" % (self.name, _pos_to) )
            return
        
                
        self._command_sent = True
        self._target_pos = pos
        self.VAL.set(pos)
        _pos_from = _pos_format % self.get_position()
        _logger.debug( "(%s) moving from %s to %s" % (self.name, _pos_from, _pos_to) )
        
        if wait:
            self.wait()

    def move_by(self, val, wait=False, force=False):
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
        poll=0.05
        timeout = 5.0
        
        #initialize precision
        prec = self.PREC.get()
        if prec == 0: prec = self.default_precision
        _pos_format = "%%0.%df" % prec

        if (start and self._command_sent and not self._moving):
            _logger.debug('%s waiting to start moving' % (self.name,))
            while self._command_sent and not self._moving and timeout > 0:
                timeout -= poll
                time.sleep(poll)
                if misc.same_value(self.get_position(), self._target_pos, prec, self.units=='deg'):
                    self._command_sent = False
                    _logger.debug('%s already at %g' % (self.name,self._target_pos))
            if timeout <= 0:
                tgt = _pos_format % self._target_pos
                cur = _pos_format % self.get_position()
                _logger.warning('%s timed out moving to %s [currently %s].' % (self.name, tgt, cur))
                return False                
        if (stop and self._moving):
            _logger.debug('%s waiting to stop moving' % (self.name,))
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
    def __init__(self, *args, **kwargs ):
        kwargs['motor_type'] = 'vme'
        Motor.__init__(self, *args, **kwargs)

class APSMotor(Motor):
    """Convenience class for "vme" type motors."""
    def __init__(self, *args, **kwargs ):
        kwargs['motor_type'] = 'aps'
        Motor.__init__(self, *args, **kwargs)


class ENCMotor(Motor):
    """Convenience class for "vmeenc" type motors."""
    def __init__(self, *args, **kwargs ):
        kwargs['motor_type'] = 'vmeenc'
        Motor.__init__(self, *args, **kwargs)

class CLSMotor(Motor):
    """Convenience class for "cls" type motors."""
    def __init__(self, *args, **kwargs ):
        kwargs['motor_type'] = 'cls'
        Motor.__init__(self, *args, **kwargs)

class PseudoMotor(Motor):
    """Convenience class for "pseudo" type motors."""
    def __init__(self, *args, **kwargs ):
        kwargs['motor_type'] = 'pseudo'
        Motor.__init__(self, *args, **kwargs)

class PseudoMotor2(Motor):
    def __init__(self, *args, **kwargs ):
        kwargs['motor_type'] = 'oldpseudo'
        Motor.__init__(self, *args, **kwargs)
   
class EnergyMotor(Motor):

    implements(IMotor)
    
    def __init__(self, pv1, pv2, enc=None):
        MotorBase.__init__(self, 'Beamline Energy')
        self.units = 'keV'
        
        pv2_root = ':'.join(pv2.split(':')[:-1])
        # initialize process variables
        self.VAL  = self.add_pv(pv1)    
        self.PREC = self.add_pv("%s.PREC" % pv2)  
        if enc is not None:
            self.RBV = self.add_pv(enc, timed=True)
            self.PREC = self.add_pv("%s.PREC" % enc)  
        else:
            self.RBV  = self.add_pv("%s:sp" % pv2, timed=True)
            self.PREC = self.add_pv("%s:sp.PREC" % pv2)
        self.MOVN = self.add_pv("%s:moving:fbk" % pv1)
        self.STOP = self.add_pv("%s:stop" % pv1)
        self.CALIB =  self.add_pv("%s:calibDone" % pv2_root)
        self.STAT =  self.add_pv("%s:status" % pv2_root)
        self.LOG = self.add_pv("%s:stsLog" % pv1)
        self.ENAB = self.CALIB
        
        # connect monitors
        self._rbid = self.RBV.connect('timed-change', self._signal_timed_change)
        self._vid = self.VAL.connect('changed', self._signal_target)
        self.MOVN.connect('changed', self._signal_move)
        self.CALIB.connect('changed', self._on_calib_changed)
        self.ENAB.connect('changed', self._signal_enable)
        self.LOG.connect('changed', self._send_log)
    
    def _signal_timed_change(self, obj, data):
        val = converter.bragg_to_energy(data[0])
        self.set_state(timed_change=(val, data[1]), changed=val)

    def _send_log(self, obj, msg):
        _logger.info("(%s) %s" % (self.name, msg))
                                 
    def get_position(self):
        return converter.bragg_to_energy(self.RBV.get())           

                

class BraggEnergyMotor(Motor):
    """A specialized energy motor for using just the monochromator bragg angle."""

    implements(IMotor)
    
    def __init__(self, name, enc=None, motor_type="vme", precision=3):
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
            gobject.source_remove(self._rbid)
            self.RBV.connect('timed-change', self._signal_timed_change)
        gobject.source_remove(self._vid) # Not needed for Bragg
        self.name = 'Bragg Energy'
        self._motor_type = 'vmeenc'

    def _on_desc_change(self, pv, val):
        pass
                                   
    def get_position(self):
        return converter.bragg_to_energy(self.RBV.get())
    
    def _signal_timed_change(self, obj, data):
        val = converter.bragg_to_energy(data[0])
        self.set_state(timed_change=(val, data[1]), changed=val)
        
    def move_to(self, pos, wait=False, force=False):
        # Do not move if motor state is not sane.
        sanity, msg = self.health_state
        if sanity != 0:
            _logger.warning( "(%s) not sane. Reason: '%s'. Move canceled!" % (self.name,msg) )
            return

        # Do not move if requested position is within precision error
        # from current position.
        prec = self.PREC.get()
        if prec == 0: prec = self.default_precision
        _pos_format = "%%0.%df" % prec
        _pos_to = _pos_format % pos
        if misc.same_value(pos, self.get_position(), prec, self.units=='deg') and not force:
            _logger.debug( "(%s) is already at %s" % (self.name, _pos_to) )
            return
        
        deg_target = converter.energy_to_bragg(pos)
        self._command_sent = True
        self._target_pos = pos
        self.VAL.put(deg_target)
        self._signal_target(None, pos)
        _logger.info( "(%s) moving to %f" % (self.name, pos) )
        
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
        return '<FixedLine2Motor: \n\t%s,\n\t%s,\n\tslope=%0.2f, intercept=%0.2f\n>' % (self.x, self.y, self.slope, self.intercept)
        
    def get_position(self):
        """Obtain the position of the `x` motor only."""
        return self.x.get_position()
        
    def move_to(self, pos, wait=False, force=False):
        px = pos
        self.x.move_to(px, force=force)
        if self.linked:
            self.x.wait(start=True, stop=True)
        py = self.intercept + self.slope * px
        self.y.move_to(py, force=force)
        if wait:
            self.wait()

    def move_by(self, val, wait=False, force=False):
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
        self._position = 0.0
        self.add_devices(self.y1, self.y2, self.omega)
        self.y1.connect('changed', self._calc_position)
        self.y2.connect('changed', self._calc_position)
        self.omega.connect('changed', self._calc_position)
               
    def __repr__(self):
        return '<RelVerticalMotor: %s, %s >' % (self.y1, self.y2)

    def _calc_position(self, obj, val):
        tmp_omega = int(self.omega.get_position() ) - 90.0 - self.offset
        sin_w = numpy.sin(numpy.radians(tmp_omega))
        cos_w = numpy.cos(numpy.radians(tmp_omega))
        self._position = self.y2.get_position()*cos_w - self.y1.get_position()*sin_w
        self.set_state(changed=self._position)    
                
    def get_position(self):
        return self._position
                                                            
    def move_by(self, val, wait=False, force=False):
        if val == 0.0:  return
        tmp_omega = int(self.omega.get_position() ) - 90.0 - self.offset
        sin_w = numpy.sin(numpy.radians(tmp_omega))
        cos_w = numpy.cos(numpy.radians(tmp_omega))
        self.y1.move_by(-val * sin_w)
        self.y2.move_by(val * cos_w)
        if wait:
            self.wait()
    
    def move_to(self, val, wait=False, force=False):        
        if val == 0.0:  return
        tmp_omega = int(self.omega.get_position() ) - 90.0 - self.offset
        sin_w = numpy.sin(numpy.radians(tmp_omega))
        cos_w = numpy.cos(numpy.radians(tmp_omega))
        self.y1.move_to(-val * sin_w)
        self.y2.move_to(val * cos_w)
        if wait:
            self.wait()
                
    def stop(self):
        self.y2.stop()
        self.y1.stop()
    
    def wait(self, start=True, stop=True):
        self.y2.wait(start=start, stop=False)
        self.y1.wait(start=start, stop=False)
        self.y2.wait(start=False, stop=stop)
        self.y1.wait(start=False, stop=stop)
        
