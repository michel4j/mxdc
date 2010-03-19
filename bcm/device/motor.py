import time
import math
import logging
import gobject
from zope.interface import implements
from twisted.spread import pb, interfaces
from bcm.device.interfaces import IMotor, IShutter
from bcm.protocol.ca import PV
from bcm.utils.log import get_module_logger
from bcm.utils.decorators import async
from bcm.utils import converter
from bcm import registry

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class MotorError(Exception):

    """Base class for errors in the motor module."""


class MotorBase(gobject.GObject):

    """Base class for motors."""
    implements(IMotor)

    # Motor signals
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "moving": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "health": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "enable": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        }  

    def __init__(self, name):
        gobject.GObject.__init__(self)
        self.name = name
        self._moving = False
        self._command_sent = False
        self._motor_type = 'basic'
        self.units = ''
        self._move_active_value = 1
        self._signal_health(None, False)
        self._signal_enable(None, False)
    
    def __repr__(self):
        s = "<%s:'%s', type:%s>" % (self.__class__.__name__,
                                               self.name,
                                               self._motor_type)
        return s
    
    def _signal_change(self, obj, value):
        gobject.idle_add(self.emit,'changed', self.get_position() )
    
    def _signal_move(self, obj, state):
        if state == self._move_active_value:
            self._moving = True           
            self._command_sent = False
        else:
            self._moving = False
        gobject.idle_add(self.emit, 'moving', self._moving)
        if not self._moving:
            _logger.debug( "(%s) stopped at %f" % (self.name, self.get_position()) )
            
           
    def _signal_health(self, obj, state):
        if state == 0:
            is_healthy = False
        else:
            is_healthy = True
        gobject.idle_add(self.emit, 'health', is_healthy)

    def _signal_enable(self, obj, state):
        if state == 0:
            is_enabled = False
        else:
            is_enabled = True
        gobject.idle_add(self.emit, 'enable', is_enabled)

class SimMotor(MotorBase):
    implements(IMotor)
     
    def __init__(self, name, pos=0, units='mm'):
        MotorBase.__init__(self,name)
        self._position = float(pos)
        self._speed = 100
        self.units = units
        self._state = 0
        self._stopped = False
        self._healthy = True
        self._signal_change(None, self._position)
        self._signal_health(None, self._healthy)
     
    def get_state(self):
        return self._state
     
    def get_position(self):
        return self._position
    
    @async
    def _move_action(self, target):
        self._stopped = False
        self._command_sent = True
        import numpy
        targets = numpy.linspace(self._position, target, 20)
        self._signal_move(self, 1)
        for pos in targets:
            time.sleep(5.0/self._speed)
            self._position = pos
            self._signal_change(self, self._position)
            if self._stopped:
                break
        self._signal_move(self, 0)
            
    def move_to(self, pos, wait=False, force=False):
        self._move_action(pos)
        if wait:
            self.wait()
    
    def move_by(self, pos, wait=False):
        self.move_to(self._position+pos, wait)
    
    def is_moving(self):
        return self._moving
    
    def is_healthy(self):
        return True
    
    def is_enabled(self):
        return True

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
    
    def stop(self):
        self._stopped = True
    
    
         
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
        self.ENAB = PV("%s:enabled" % (pv_root))
        if self._motor_type in ['vme','vmeenc']:
            if self._motor_type == 'vme':
                self.RBV  = PV("%s:sp" % (pv_name))
                self.PREC =    PV("%s:sp.PREC" % (pv_name))
            else:
                self.RBV  = PV("%s:fbk" % (pv_name))
                self.PREC =    PV("%s:fbk.PREC" % (pv_name))
            self.STAT = PV("%s:status" % pv_root)
            self._move_active_value = 1
            self.MOVN = self.STAT #PV("%s:moving" % pv_root)
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
            self._move_active_value = 0
            self.PREC =    PV("%s:fbk.PREC" % (pv_name))
            self.RBV  = PV("%s:fbk" % (pv_name))
            self.STAT = PV("%s:status" % pv_root)
            self.MOVN = PV("%s:stopped" % pv_root)
            self.STOP = PV("%s:stop" % pv_root)
            self.CALIB = PV("%s:calibDone" % pv_root)
            self.LOG = PV("%s:log" % pv_root)
            self.LOG.connect('changed', self._on_log)
        elif self._motor_type == 'oldpseudo':
            self._move_active_value = 0
            self.PREC =    PV("%s:sp.PREC" % (pv_name))
            self.RBV  = PV("%s:sp" % (pv_name))
            self.STAT = PV("%s:status" % pv_root)
            self.MOVN = PV("%s:stopped" % pv_root)
            self.STOP = PV("%s:stop" % pv_root)
            self.CALIB = PV("%s:calibDone" % pv_root)
            self.LOG = PV("%s:log" % pv_root)
            self.LOG.connect('changed', self._on_log)
                     
        # connect monitors
        self._rbid = self.RBV.connect('changed', self._signal_change)
        self.MOVN.connect('changed', self._signal_move)
        self.CALIB.connect('changed', self._signal_health)
        self.ENAB.connect('changed', self._signal_enable)
        self.DESC.connect('changed', self._on_desc_change)


    def _on_desc_change(self, pv, val):
        self.name = val

    def _on_log(self, obj, message):
        msg = "(%s) %s" % (self.name, message)
        _logger.debug(msg)
                                        
    def get_state(self):
        return self.STAT.get()
    
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

        # Do not move if motor state is not sane.
        if not self.is_healthy():
            _logger.warning( "(%s) is not in a sane state. Move canceled!" % (self.name,) )
            return
        
        # Do not move is requested position is within precision error
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
                
    def is_moving(self):
        if self.MOVN.get() == self._move_active_value :
            return True
        else:
            return False
    
    def is_healthy(self):
        return (self.CALIB.get() == 1)

    def is_enabled(self):
        return (self.ENAB.get() == 1) 
                                 
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
    
    def __init__(self, name, offset=0.0, enc=None):
        Motor.__init__(self, name, motor_type='vmeenc' )
        self.offset = float(offset)
        del self.DESC
        if enc is not None:
            del self.RBV          
            self.RBV = PV(enc)
            gobject.source_remove(self._rbid)
            self.RBV.connect('changed', self._signal_change)
        self.name = 'Bragg Energy'
        self._motor_type = 'vmeenc'

    def _on_desc_change(self, pv, val):
        pass
                                   
    def get_position(self):
        return converter.bragg_to_energy(self.RBV.get()-self.offset)
            
    def move_to(self, pos, wait=False, force=False):
        pos += self.offset
        # Do not move if motor state is not sane.
        if not self.is_healthy():
            _logger.warning( "(%s) is not in a sane state. Move canceled!" % (self.name,) )
            return

        # Do not move if requested position is within precision error
        # from current position.
        prec = self.PREC.get()
        prec = prec == 0 and 4 or prec
        if abs(self.get_position() - pos) <  10**-prec and not force:
            _logger.info( "(%s) is already at %f" % (self.name, pos) )
            return
        
        deg_target = converter.energy_to_bragg(pos)
        self._command_sent = True
        self.VAL.put(deg_target)
        _logger.info( "(%s) moving to %f" % (self.name, pos) )
        
        if wait:
            self.wait()

class MotorShutter(gobject.GObject):
    """Used for CMCF1 cryojet Motor"""
    implements(IShutter)
    __used_for__ = IMotor
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_BOOLEAN,)  ),
        }
    
    def __init__(self, motor):
        gobject.GObject.__init__(self)
        self.motor = motor
        self.name = motor.name
        self.out_pos = 5
        self.in_pos = 0
        self.motor.CCW_LIM.connect('changed', self._auto_calib_nozzle)
        self.motor.connect('moving', self._signal_change)

    def _auto_calib_nozzle(self, obj, val):
        if val == 1:
            self.motor.configure(reset=0.0)
            
    def open(self):
        self.motor.move_to(self.out_pos)

    def close(self):
        self.motor.move_to(self.in_pos-0.1)
            
    def get_state(self):
        return abs(self.motor.get_position() - self.in_pos) < 1

    def _signal_change(self, obj, value):
        if value == False:
            gobject.idle_add(self.emit,'changed', self.get_state())

class FixedLine2Motor(MotorBase):
    
    def __init__(self, x, y, slope, intercept, linked=False):
        MotorBase.__init__(self, 'FixedOffset')        
        self.y = y
        self.x = x
        self.linked = bool(linked)
        self.slope = float(slope)
        self.intercept = float(intercept)
        self.y.connect('changed', self._signal_change)
            
    def get_state(self):
        return self.y.get_state()
    
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
                
    def is_moving(self):
        return self.y.is_moving() or self.x.is_moving()
    
    def is_healthy(self):
        return self.x.is_healthy() and self.y.is_healthy()

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
            
    def get_state(self):
        return self.y1.get_state() | self.y2.get_state()
    
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
        tmp_omega = int(self.omega.get_position() )
        sin_w = math.sin(tmp_omega * math.pi / 180)
        cos_w = math.cos(tmp_omega * math.pi / 180)
        self.y1.move_by(val * sin_w)
        self.y2.move_by(-val * cos_w)
        if wait:
            self.wait()
    move_by = move_to
                
    def is_moving(self):
        return self.y1.is_moving() or self.y2.is_moving()
    
    def is_healthy(self):
        return self.y2.is_healthy() and self.y1.is_healthy()
                                 
    def is_enabled(self):
        return self.y2.is_enabled() and self.y1.is_enabled()

    def stop(self):
        self.y2.stop()
        self.y1.stop()
    
    def wait(self, start=True, stop=True):
        self.y2.wait(start=start, stop=False)
        self.y1.wait(start=start, stop=False)
        self.y2.wait(start=False, stop=stop)
        self.y1.wait(start=False, stop=stop)


registry.register([IMotor], IShutter, '', MotorShutter)

from bcm.service.utils import *
from twisted.internet import defer

class MotorServer(MasterDevice):
    __used_for__ = IMotor
    def setup(self, device):
        device.connect('changed', lambda x,y: self.notify_clients('changed', y))
        device.connect('health', lambda x,y: self.notify_clients('health', y))
        device.connect('moving', lambda x,y: self.notify_clients('moving', y))
        self.device = device
    
    def getStateForClient(self):
        return {'units': self.device.units, 'name': self.device.name}
    
    def setup_client(self, client):
        self.notify_clients('changed', self.device.get_position())
                          
    # convey commands to device
    def remote_move_to(self, *args, **kwargs):
        self.device.move_to(*args, **kwargs)
    
    def remote_move_by(self, *args, **kwargs):
        self.device.move_by(*args, **kwargs)

    def remote_get_state(self):
        return self.device.get_state()
    
    def remote_get_position(self):
        return self.device.get_position()
    
    def remote_stop(self):
        return self.device.stop()
    
    def remote_wait(self, **kwargs):
        self.device.wait(**kwargs)
        
            
class MotorClient(SlaveDevice, MotorBase):
    __used_for__ = interfaces.IJellyable
    def setup(self):
        MotorBase.__init__(self, 'Motor Client')
        self._motor_type = 'remote'
        self.connect('changed', self._set_position)
    
    def _set_position(self, obj, val):
        self.position = val
            
    #implement methods here for clients to be able to control server
    #do not implement methods you don't want to expose to clients
    def move_to(self, pos, wait=False, force=False):
        return self.device.callRemote('move_to', pos, wait=False, force=False)
    
    def move_by(self, pos, wait=False, force=False):
        return self.device.callRemote('move_by', pos, wait=False, force=False)
    
    def stop(self):
        return self.device.stop()
    
    def get_position(self):
        #return self.device.callRemote('get_position')
        return self.position
        
    def get_state(self):
        return self.device.callRemote('get_state')
      
    def wait(self, start=True, stop=True):
        return self.device.callRemote('wait', start=start, stop=stop)
    
       
# Motors
registry.register([IMotor], IDeviceServer, '', MotorServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'MotorServer', MotorClient)

gobject.type_register(MotorBase)

        
