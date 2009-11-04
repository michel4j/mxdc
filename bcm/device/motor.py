import time
import math
import logging
import gobject
from zope.interface import implements
from bcm.device.interfaces import IMotor, IShutter
from bcm.protocol.ca import PV
from bcm.utils.log import get_module_logger
from bcm.utils import converter
from bcm import registry

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class MotorError(Exception):

    """Base class for errors in the motor module."""


class MotorBase(gobject.GObject):

    """Base class for motors."""
    
    # Motor signals
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "moving": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "health": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        }  

    def __init__(self, name):
        gobject.GObject.__init__(self)
        self.name = name
        self._moving = False
        self._command_sent = False
        self._motor_type = 'basic'
    
    def __repr__(self):
        s = "<%s:'%s', type:%s, state:%s>" % (self.__class__.__name__,
                                               self.name,
                                               self._motor_type,
                                               self.get_state())
        return s
    
    def get_state(self):
        return self.STAT.get()
        
    def _signal_change(self, obj, value):
        gobject.idle_add(self.emit,'changed', self.get_position() )
    
    def _on_log(self, obj, message):
        msg = "(%s) %s" % (self.name, message)
        _logger.info(msg)

    def _signal_move(self, obj, state):
        if state == 1:
            self._moving = True           
            self._command_sent = False
        else:
            self._moving = False
        gobject.idle_add(self.emit, 'moving', self._moving)
        if not self._moving:
            _logger.info( "(%s) stopped at %f" % (self.name, self.get_position()) )
            
           
    def _signal_health(self, obj, state):
        if state == 0:
            is_healthy = False
        else:
            is_healthy = True
        gobject.idle_add(self.emit, 'health', is_healthy)

class DummyMotor(MotorBase):
    implements(IMotor)
     
    def __init__(self, name):
        self._position = 0.0
     
    def get_state(self):
        return 0
     
    def get_position(self):
        return self._position
   
    def move_to(self, pos, wait=False, force=False):
        self._position = pos
    
    def move_by(self, pos, wait=False):
        self.move_to(self._position+pos, wait)
    
    def is_moving(self):
        return False
    
    def is_healthy(self):
        return True
    
    def wait(self, start=True, stop=True):
        pass
    
    def stop(self):
        pass
    
    
         
class Motor(MotorBase):

    implements(IMotor) 
       
    def __init__(self, pv_name, motor_type):
        MotorBase.__init__(self, pv_name)
        pv_parts = pv_name.split(':')
        if len(pv_parts)<2:
            _logger.error("Unable to create motor '%s' of type '%s'." %
                             (pv_name, motor_type) )
            raise MotorError("Motor name must be of the format 'name:unit'.")
        
        if motor_type not in ['vme', 'cls', 'pseudo', 'oldpseudo', 'vmeenc']:
            _logger.error("Unable to create motor '%s' of type '%s'." %
                             (pv_name, motor_type) )
            raise MotorError("Motor type must be one of 'vmeenc', \
                'vme', 'cls', 'pseudo'")
          
        self.units = pv_parts[-1]
        pv_root = ':'.join(pv_parts[:-1])
        self._motor_type = motor_type
        
        # initialize process variables based on motor type
        self.DESC = PV("%s:desc" % (pv_root))               
        self.VAL  = PV("%s" % (pv_name))
        if self._motor_type in ['vme','vmeenc']:
            if self._motor_type == 'vme':
                self.RBV  = PV("%s:sp" % (pv_name))
                self.PREC =    PV("%s:sp.PREC" % (pv_name))
            else:
                self.RBV  = PV("%s:fbk" % (pv_name))
                self.PREC =    PV("%s:fbk.PREC" % (pv_name))
            self.STAT = PV("%s:status" % pv_root)
            self.MOVN = PV("%s:moving" % pv_root)
            self.STOP = PV("%s:stop" % pv_root)
            self.SET  = PV("%s:setPosn" % (pv_name))
            self.CALIB = PV("%s:calibDone" % (pv_root))
            self.CCW_LIM = PV("%s:ccw" % (pv_root))
            self.CW_LIM = PV("%s:cw" % (pv_root))
        elif self._motor_type == 'cls':
            self.PREC =    PV("%s:fbk.PREC" % (pv_name))
            self.RBV  = PV("%s:fbk" % (pv_name))
            self.MOVN = PV("%s:state" % pv_root)
            self.STAT = self.MOVN
            self.STOP = PV("%s:emergStop" % pv_root)
            self.CALIB = PV("%s:isCalib" % (pv_root))
        elif self._motor_type == 'pseudo':
            self.PREC =    PV("%s:fbk.PREC" % (pv_name))
            self.RBV  = PV("%s:fbk" % (pv_name))
            self.STAT = PV("%s:status" % pv_root)
            self.MOVN = PV("%s:moving" % pv_root)
            self.STOP = PV("%s:stop" % pv_root)
            self.CALIB = PV("%s:calibDone" % pv_root)
            self.LOG = PV("%s:log" % pv_root)
            self.LOG.connect('changed', self._on_log)
        elif self._motor_type == 'oldpseudo':
            self.PREC =    PV("%s:sp.PREC" % (pv_name))
            self.RBV  = PV("%s:sp" % (pv_name))
            self.STAT = PV("%s:status" % pv_root)
            self.MOVN = PV("%s:moving" % pv_root)
            self.STOP = PV("%s:stop" % pv_root)
            self.CALIB = PV("%s:calibDone" % pv_root)
            self.LOG = PV("%s:log" % pv_root)
            self.LOG.connect('changed', self._on_log)
                     
        # connect monitors
        self._rbid = self.RBV.connect('changed', self._signal_change)
        self.STAT.connect('changed', self._signal_move)
        self.CALIB.connect('changed', self._signal_health)
        self.DESC.connect('changed', self._on_desc_change)


    def _on_desc_change(self, pv, val):
        self.name = val
                                        
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
                                    
    def move_to(self, pos, wait=False, force=False):

        # Do not move is requested position is within precision error
        # from current position.
        prec = self.PREC.get()
        if prec == 0:
            prec = 3
        _pos_format = "%%0.%df" % prec
        _pos_to = _pos_format % pos
        if abs(self.get_position() - pos) <  10**-prec and not force:
            _logger.info( "(%s) is already at %s" % (self.name, _pos_to) )
            return
        
        
        # Do not move if motor state is not sane.
        if not self.is_healthy():
            _logger.warning( "(%s) is not in a sane state. Move canceled!" % (self.name,) )
            return
        
        self._command_sent = True
        self.VAL.set(pos)
        _pos_from = _pos_format % self.get_position()
        _logger.info( "(%s) moving from %s to %s" % (self.name, _pos_from, _pos_to) )
        
        if wait:
            self.wait()

    def move_by(self,val, wait=False, force=False):
        if val == 0.0:
            return
        cur_pos = self.get_position()
        self.move_to(cur_pos + val, wait, force)
                
    def is_moving(self):
        if self.STAT.get() == 1:
            return True
        else:
            if self.MOVN.get() == 1:
                return True
            else:
                return False
    
    def is_healthy(self):
        return (self.CALIB.get() == 1) #and (self.STAT.get() != 4)
                                 
    def stop(self):
        self.STOP.set(1)
    
    def wait(self, start=True, stop=True):
        poll=0.05
        timeout = 2.0
        if (start and self._command_sent and not self._moving):
            _logger.debug('(%s) Waiting to start moving' % (self.name,))
            while self._command_sent and not self._moving and timeout > 0:
                timeout -= poll
                time.sleep(poll)
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
        
        pv1_root = ':'.join(pv1.split(':')[:-1])
        pv2_root = ':'.join(pv2.split(':')[:-1])
        # initialize process variables
        self.VAL  = PV(pv1)    
        self.PREC = PV("%s.PREC" % pv2)  
        if enc is not None:
            self.RBV = PV(enc)
            self.PREC = PV("%s.PREC" % enc)  
        else:
            self.RBV  = PV("%s:sp" % pv2)
            self.PREC = PV("%s:sp.PREC" % pv2)
        self.MOVN = PV("%s:moving" % pv1)
        self.MOVN2 = PV("%s:moving" % pv2)
        self.STOP = PV("%s:stop" % pv1)
        self.CALIB =  PV("%s:calibDone" % pv2_root)
        self.STAT =  PV("%s:status" % pv2_root)
        
        # connect monitors
        self._rbid = self.RBV.connect('changed', self._signal_change)
        self.MOVN.connect('changed', self._signal_move)
        #self.MOVN2.connect('changed', self._signal_move)
        self.CALIB.connect('changed', self._signal_health)
                            
    def get_position(self):
        return converter.bragg_to_energy(self.RBV.get())           

                

class BraggEnergyMotor(Motor):

    implements(IMotor)
    
    def __init__(self, name, enc=None):
        Motor.__init__(self, name, motor_type='vme' )
        del self.DESC
        if enc is not None:
            del self.RBV          
            self.RBV = PV(enc)
            gobject.source_remove(self._rbid)
            self.RBV.connect('changed', self._signal_change)
        self.name = 'Bragg Energy'
        self._motor_type = 'vme'

    def _on_desc_change(self, pv, val):
        pass
                                   
    def get_position(self):
        return converter.bragg_to_energy(self.RBV.get())
            
    def move_to(self, pos, wait=False, force=False):
        # Do not move if requested position is within precision error
        # from current position.
        prec = self.PREC.get()
        prec = prec == 0 and 4 or prec
        if abs(self.get_position() - pos) <  10**-prec and not force:
            _logger.info( "(%s) is already at %f" % (self.name, pos) )
            return
        
        # Do not move if motor state is not sane.
        if not self.is_healthy():
            _logger.warning( "(%s) is not in a sane state. Move canceled!" % (self.name,) )
            return

        deg_target = converter.energy_to_bragg(pos)
        self._command_sent = True
        self.VAL.put(deg_target)
        _logger.info( "(%s) moving to %f" % (self.name, pos) )
        
        if wait:
            self.wait()

class MotorShutter(object):
    implements(IShutter)
    __used_for__ = IShutter
    
    def __init__(self, motor):
        self.motor = motor
        self.name = motor.name
        self.open_pos = 5.0
        self.close_pos = 0.0
    
    def open(self):
        self.motor.move_to(self.open_pos)

    def close(self):
        self.move_to(self.close_pos)
            
    def get_state(self):
        return self.motor.get_state()

class FixedLine2Motor(MotorBase):
    implements(IMotor)
    
    def __init__(self, x, y, slope, intercept, linked=False):
        MotorBase.__init__(self, 'FixedOffset')        
        self.y = y
        self.x = x
        self.linked = bool(linked)
        self.slope = float(slope)
        self.intercept = float(intercept)
        self.y.connect('changed', self._signal_change)
            
    def get_state(self):
        return self.m1.get_state()
    
    def __repr__(self):
        return '<FixedLine2Motor: \n\t%s,\n\t%s,\n\tslope=%0.2f, intercept=%0.2f\n>' % (self.x, self.y, self.slope, self.intercept)
        
    def get_position(self):
        return self.y.get_position()
        
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
                
    def is_moving(self):
        return self.y.is_moving() or self.x.is_moving()
    
    def is_healthy(self):
        return self.x.is_healthy() and self.y.is_healthy()
                                 
    def stop(self):
        self.x.stop()
        self.y.stop()
    
    def wait(self, start=True, stop=True):
        self.x.wait(start=start, stop=False)
        self.y.wait(start=start, stop=False)
        self.x.wait(start=False, stop=stop)
        self.y.wait(start=False, stop=stop)
        
registry.register([IMotor], IShutter, '', MotorShutter)  
gobject.type_register(MotorBase)

        
