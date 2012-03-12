import time
import math
import gobject
from zope.interface import implements
from bcm.device.interfaces import IMotor
from bcm.utils.log import get_module_logger
from bcm.utils.decorators import async
from bcm.utils import converter
from bcm import registry
from bcm.device.base import BaseDevice

# setup module logger with a default do-nothing handler
_logger = get_module_logger('devices')


class MotorError(Exception):

    """Base class for errors in the motor module."""


class MotorBase(BaseDevice):

    """Base class for motors."""
    implements(IMotor)

    # Motor signals
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "timed-change": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        }  

    def __init__(self, name):
        BaseDevice.__init__(self)
        #self.set_state(changed=0.0)
        self.name = name
        self._moving = False
        self._command_sent = False
        self._target_pos = 0
        self._motor_type = 'basic'
        self.units = ''
        self._move_active_value = 1
    
    def _signal_change(self, obj, value):
        self.set_state(changed=self.get_position())

    def _signal_timed_change(self, obj, data):
        self.set_state(timed_change=data, changed=data[0])
    
    def _signal_move(self, obj, state):
        if state == self._move_active_value:
            self._moving = True           
            self._command_sent = False
        else:
            self._moving = False

        self.set_state(busy=self._moving)
        if not self._moving:
            _logger.debug( "(%s) stopped at %f" % (self.name, self.get_position()) )
                       
    def _on_calib_changed(self, obj, cal):
        if cal == 0:
            self.set_state(health=(1, 'calib', 'Device Not Calibrated!'))
        else:
            self.set_state(health=(0, 'calib'))

    def _signal_enable(self, obj, val):
        if val == 0:
            if not self.is_busy():
                self.set_state(health=(16, 'disabled', 'Device disabled!'))
        else:
            self.set_state(health=(0, 'disabled'))

class SimMotor(MotorBase):
    implements(IMotor)
     
    def __init__(self, name, pos=0, units='mm', active=True):
        MotorBase.__init__(self,name)
        pos = pos
        self._time = 2.0 # duration of each move
        self._steps = 10
        self.units = units
        self._state = 0
        self._stopped = False
        self._enabled = True
        self._command_sent = False
        self.set_state(health=(0,''), active=active, changed=pos)
        self._position = pos

    def get_position(self):
        return self._position
    
    @async
    def _move_action(self, target):
        self._stopped = False
        self._command_sent = True
        import numpy
        targets = numpy.linspace(self._position, target, self._steps)
        self.set_state(busy=True)
        self._command_sent = False
        for pos in targets:
            self._position = pos
            data = (pos, time.time())
            self._signal_timed_change(self, data)
            if self._stopped:
                break
            time.sleep(self._time/self._steps)
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
                _logger.warning('(%s) Timed out. Did move after %d sec.' % (self.name, _orig_to))
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

    implements(IMotor) 
       
    def __init__(self, pv_name, motor_type):
        MotorBase.__init__(self, pv_name)
        pv_parts = pv_name.split(':')
        if len(pv_parts)<2:
            _logger.error("Unable to create motor '%s' of type '%s'." %
                             (pv_name, motor_type) )
            raise MotorError("Motor name must be of the format 'name:unit'.")
        
        if motor_type not in ['vme', 'cls', 'pseudo', 'oldpseudo', 'vmeenc', 'maxv']:
            _logger.error("Unable to create motor '%s' of type '%s'." %
                             (pv_name, motor_type) )
            raise MotorError("Motor type must be one of 'vmeenc', \
                'vme', 'cls', 'pseudo', 'maxv'")
          
        self.units = pv_parts[-1]
        pv_root = ':'.join(pv_parts[:-1])
        self.pv_root = pv_root
        self._motor_type = motor_type
        
        # initialize process variables based on motor type
        self.DESC = self.add_pv("%s:desc" % (pv_root))               
        self.VAL  = self.add_pv("%s" % (pv_name))
        #self.ENAB = self.add_pv("%s:enabled" % (pv_root))
        if self._motor_type in ['vme','vmeenc']:
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
            self.PREC =    self.add_pv("%s:fbk.PREC" % (pv_name))
            self.RBV  = self.add_pv("%s:fbk" % (pv_name), timed=True)
            self.MOVN = self.add_pv("%s:state" % pv_root)
            self.STAT = self.MOVN
            self.STOP = self.add_pv("%s:emergStop" % pv_root)
            self.CALIB = self.add_pv("%s:isCalib" % (pv_root))
            self.ENAB = self.CALIB
        elif self._motor_type == 'pseudo':
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
                     
        # connect monitors
        self._rbid = self.RBV.connect('timed-change', self._signal_timed_change)
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
        return self.RBV.get()

    def configure(self, **kwargs):
        for key, val in kwargs.items():
            # Set Calibration
            if key == 'calib':
                if val:
                    self.CALIB.set(1)
                else:
                    self.CALIB.set(0)
            if key == 'reset':
                if self._motor_type in ['vme','vmeenc'] :
                    self.SET.set(val)
                    _logger.info( "(%s) reset to %f." % (self.name, val) )
                else:
                    _logger.error( "(%s) can not reset %s Motors." %
                        (self._motor_type) )
   
    # Added for Save/Restore                             
    def get_settings(self):
        self.settings = {}
        PV_DICT = dict(ENC_SETTINGS.items() + SAVE_VALS.items())
        for i in PV_DICT:
            self.settings[i] = self.add_pv(PV_DICT[i].replace('%root', self.pv_root).replace('%unit', self.units))
        return
           
    def move_to(self, pos, wait=False, force=False):

        # Do not move if motor state is not sane.
        st = self.get_state()
        sanity, msg = st['health']
        if sanity != 0:
            _logger.warning( "(%s) not sane. Reason: '%s'. Move canceled!" % (self.name,msg) )
            return
        
        # Do not move if requested position is within precision error
        # from current position.
        prec = self.PREC.get()
        if prec == 0:
            prec = 3
        _pos_format = "%%0.%df" % prec
        _pos_to = _pos_format % pos
        if abs(self.get_position() - pos) <  10**-prec and not force:
            _logger.debug( "(%s) is already at %s" % (self.name, _pos_to) )
            return
        
                
        self._command_sent = True
        self._target_pos = pos
        self.VAL.set(pos)
        _pos_from = _pos_format % self.get_position()
        _logger.debug( "(%s) moving from %s to %s" % (self.name, _pos_from, _pos_to) )
        
        if wait:
            self.wait()

    def move_by(self,val, wait=False, force=False):
        if val == 0.0:
            return
        cur_pos = self.get_position()
        self.move_to(cur_pos + val, wait, force)
                                                     
    def stop(self):
        self.STOP.set(1)
    
    def wait(self, start=True, stop=True):
        poll=0.05
        timeout = 5.0
        
        #initialize precision
        prec = self.PREC.get()
        if prec == 0 or prec is None:
            prec = 3

        if (start and self._command_sent and not self._moving):
            _logger.debug('(%s) Waiting to start moving' % (self.name,))
            while self._command_sent and not self._moving and timeout > 0:
                timeout -= poll
                time.sleep(poll)
                if abs(self._target_pos - self.get_position()) < 10**-prec:
                    self._command_sent = False
                    _logger.warning('(%s) already moved to target.' % (self.name,))
            if timeout <= 0:
                _logger.warning('Timed out waiting for (%s) to start moving.' % (self.name,))
                return False                
        if (stop and self._moving):
            _logger.debug('(%s) Waiting to stop moving' % (self.name,))
            while self._moving:
                time.sleep(poll)
        
class VMEMotor(Motor):
    def __init__(self, name):
        Motor.__init__(self, name, motor_type = 'vme')

class ENCMotor(Motor):
    def __init__(self, name):
        Motor.__init__(self, name, motor_type = 'vmeenc')

class CLSMotor(Motor):
    def __init__(self, name):
        Motor.__init__(self, name, motor_type = 'cls')

class PseudoMotor(Motor):
    def __init__(self, name):
        Motor.__init__(self, name, motor_type = 'pseudo')

class PseudoMotor2(Motor):
    def __init__(self, name):
        Motor.__init__(self, name, motor_type = 'oldpseudo')
   
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
        self.ENAB = self.CALIB
        
        # connect monitors
        self._rbid = self.RBV.connect('timed-change', self._signal_timed_change)
        self.MOVN.connect('changed', self._signal_move)
        self.CALIB.connect('changed', self._on_calib_changed)
        self.ENAB.connect('changed', self._signal_enable)
    
    def _signal_timed_change(self, obj, data):
        val = converter.bragg_to_energy(data[0])
        self.set_state(timed_change=(val, data[1]), changed=val)
                            
    def get_position(self):
        return converter.bragg_to_energy(self.RBV.get())           

                

class BraggEnergyMotor(Motor):

    implements(IMotor)
    
    def __init__(self, name, enc=None):
        Motor.__init__(self, name, motor_type='vme' )
        del self.DESC
        if enc is not None:
            del self.RBV          
            self.RBV = self.add_pv(enc, timed=True)
            gobject.source_remove(self._rbid)
            self.RBV.connect('timed-change', self._signal_timed_change)
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
        st = self.get_state()
        sanity, msg = st['health']
        if sanity != 0:
            _logger.warning( "(%s) not sane. Reason: '%s'. Move canceled!" % (self.name,msg) )
            return

        # Do not move if requested position is within precision error
        # from current position.
        prec = self.PREC.get()
        if prec == 0:
            prec = 3
        if abs(self.get_position() - pos) <  10**-prec and not force:
            _logger.info( "(%s) is already at %f" % (self.name, pos) )
            return
        
        deg_target = converter.energy_to_bragg(pos)
        self._command_sent = True
        self._target_pos = pos
        self.VAL.put(deg_target)
        _logger.info( "(%s) moving to %f" % (self.name, pos) )
        
        if wait:
            self.wait()


class FixedLine2Motor(MotorBase):
    
    def __init__(self, x, y, slope, intercept, linked=False):
        MotorBase.__init__(self, 'FixedOffset')        
        self.y = y
        self.x = x
        self.linked = bool(linked)
        self.slope = float(slope)
        self.intercept = float(intercept)
        self.y.connect('changed', self._signal_change)
                
    def __repr__(self):
        return '<FixedLine2Motor: \n\t%s,\n\t%s,\n\tslope=%0.2f, intercept=%0.2f\n>' % (self.x, self.y, self.slope, self.intercept)
        
    def get_position(self):
        return self.x.get_position()
        
    def configure(self, **kwargs):
        pass
                                            
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

    def __init__(self, y1, y2, omega):
        MotorBase.__init__(self, 'Relative Vertical')        
        self.y1 = y1
        self.y2 = y2
        self.omega = omega
                
    def __repr__(self):
        return '<RelVerticalMotor: %s, %s >' % (self.y1, self.y2)
        
    def get_position(self):
        # make sure all moves are relative by fixing current position at 0 always
        return 0
        
    def configure(self, **kwargs):
        pass
                                                    
    def move_to(self, val, wait=False, force=False):
        if val == 0.0:
            return
        tmp_omega = int(self.omega.get_position() ) - 90
        sin_w = math.sin(tmp_omega * math.pi / 180)
        cos_w = math.cos(tmp_omega * math.pi / 180)
        self.y1.move_by(-val * sin_w)
        self.y2.move_by(val * cos_w)
        if wait:
            self.wait()
    move_by = move_to
                
    def stop(self):
        self.y2.stop()
        self.y1.stop()
    
    def wait(self, start=True, stop=True):
        self.y2.wait(start=start, stop=False)
        self.y1.wait(start=start, stop=False)
        self.y2.wait(start=False, stop=stop)
        self.y1.wait(start=False, stop=stop)
        
