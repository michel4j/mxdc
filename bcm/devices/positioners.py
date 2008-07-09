from zope.interface import implements
from bcm.interfaces.positioners import IMotor, IPositioner
from bcm.protocols.ca import PV
from bcm import utils
import time
import gobject
import math
    
class PositionerException(Exception):
    def __init__(self,message):
        self.message = message

class MotorException(PositionerException):
    pass

class PositionerBase(gobject.GObject):
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "log": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        }  

    def __init__(self):
        gobject.GObject.__init__(self)
        self._last_changed = time.time()

    def _signal_change(self, obj, value):
        gobject.idle_add(self.emit,'changed', self.get_position() )
        self._last_changed = time.time()
    
    def _log(self, message):
        if hasattr(self, 'DESC'):
            nm = self.DESC.get()
        else:
            nm = self.name
        msg = "%s: %s" % (nm, message)
        gobject.idle_add(self.emit, 'log', msg)
        
    def get_position(self):
        return 0.0
    
    def get_name(self):
        return self.name

class MotorBase(gobject.GObject):
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "log": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "moving": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "health": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        }  

    def __init__(self):
        gobject.GObject.__init__(self)
        self._move_active = False
        self._last_changed = time.time()
    
    def _signal_change(self, obj, value):
        gobject.idle_add(self.emit,'changed', self.get_position() )
        self._last_changed = time.time()
    
    def _log(self, message):
        if hasattr(self, 'DESC'):
            nm = self.DESC.get()
        else:
            nm = self.name
        msg = "%s: %s" % (nm, message)
        gobject.idle_add(self.emit, 'log', msg)

    def _on_log(self, obj, msg):
        self._log(msg)

    def _signal_move(self, obj, state):
        if state == 1:
            self._move_active = True           
        else:
            self._move_active = False
        gobject.idle_add(self.emit, 'moving', self._move_active)
        if not self._move_active:
            self._log( "stopped at %g %s" % (self.get_position(), self.units) )

    def _signal_request(self, obj, value):
        self._log( "move to %f %s requested" % (value, self.units) )
           
    def _signal_health(self, obj, state):
        if state == 0:
            is_healthy = False
        else:
            is_healthy = True
        gobject.idle_add(self.emit, 'health', is_healthy)

    def get_name(self):
        return self.name

    
class Motor(MotorBase):
    implements(IMotor)    
    def __init__(self, name, motor_type):
        MotorBase.__init__(self)
        name_parts = name.split(':')
        if len(name_parts)<2:
            raise MotorException("motor name must be of the format 'name:unit'")
        
        if motor_type not in ['vme', 'cls', 'pseudo']:
            raise MotorException("motor_type must be one of 'vme', 'cls', 'pseudo'")
          
        self.units = name_parts[-1]
        self.name = ':'.join(name_parts[:-1])
        self.motor_type = motor_type
        
        # initialize process variables
        self.DESC = PV("%s:desc" % (self.name))               
        self.VAL  = PV("%s:%s" % (self.name,self.units))        
        if self.motor_type == 'vme':
            self.RBV  = PV("%s:%s:sp" % (self.name,self.units))
            self.STAT = PV("%s:status" % self.name)
            self.MOVN = PV("%s:moving" % self.name)
            self.STOP = PV("%s:stop" % self.name)
            self.SET  = PV("%s:%s:setPosn" % (self.name,self.units))
            self.CALIB = PV("%s:calibDone" % (self.name))  
        elif self.motor_type == 'cls':
            self.RBV  = PV("%s:%s:fbk" % (self.name,self.units))
            self.MOVN = PV("%s:state" % self.name)
            self.STAT = self.MOVN
            self.STOP = PV("%s:emergStop" % self.name)
            self.CALIB = PV("%s:isCalib" % (self.name))
        elif self.motor_type == 'pseudo':
            self.RBV  = PV("%s:%s:sp" % (self.name,self.units))
            self.STAT = PV("%s:status" % self.name)
            self.MOVN = PV("%s:moving" % self.name)
            self.STOP = PV("%s:stop" % self.name)
            self.CALIB = PV("%s:calibDone" % (self.name))
            self.LOG = PV("%s:log" % (self.name))
            self.LOG.connect('changed', self._on_log)
                
        # connect monitors
        self.VAL.connect('changed', self._signal_request)
        self.RBV.connect('changed', self._signal_change)
        self.STAT.connect('changed', self._signal_move)
        self.CALIB.connect('changed', self._signal_health)
                            
    def get_position(self):
        return self.RBV.get()

    def set_position(self, value):
        if self.motor_type == 'vme':
            self.SET.put(value)

    def set_calibrated(self, status):
        if status:
            self.CALIB.put(1)
        else:
            self.CALIB.put(0)
            
    def move_to(self, target, wait=False):
        if self.get_position() == target:
            return
        if not self.is_healthy():
            self._log( "not sane. Move canceled!" )
            return

        self.VAL.put(target)
        self.wait(start=True, stop=False)
        if wait:
            self.wait(start=False, stop=True)

    def move_by(self,val, wait=False):
        if val == 0.0:
            return
        self._log( "relative move by %g %s requested" % (val, self.units) )
        cur_pos = self.get_position()
        self.move_to(cur_pos + val, wait)
                
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
        self.STOP.put(1)
    
    def wait(self, start=True, stop=True):
        poll=0.05
        timeout = 2.0
        if (start):
            self._log('Waiting to start moving')
            while not self._move_active and timeout > 0:
                time.sleep(poll)
                timeout -= poll                               
        if (stop):
            self._log('Waiting to stop moving')
            while self._move_active:
                time.sleep(poll)
        
class vmeMotor(Motor):
    def __init__(self, name):
        Motor.__init__(self, name, motor_type = 'vme')

class clsMotor(Motor):
    def __init__(self, name):
        Motor.__init__(self, name, motor_type = 'cls')

class pseudoMotor(Motor):
    def __init__(self, name):
        Motor.__init__(self, name, motor_type = 'pseudo')


class Positioner(PositionerBase):
    implements(IPositioner)
    
    def __init__(self, name):
        PositionerBase.__init__(self)
        self.PV = PV(name)
        self.DESC = PV('%s.DESC' % name)
        self.name = name
        self.units = ""
        self.PV.connect('changed', self._signal_change)
        
    def move_to(self, target, wait=False):
        self._log('moving to %s' % (target))
        self.PV.put(target)

    def move_by(self, value, wait=False):
        cur_position = self.get_position()
        self._log('relative move of %g requested' % (value))
        self.move_to(cur_position + value, wait)
        
    def get_position(self):
        return self.PV.get()
    

class energyMotor(MotorBase):
    """Temporary class until energy motor is standardized"""
    implements(IMotor)    
    def __init__(self, name=None):
        MotorBase.__init__(self)
        self.units = 'keV'
        self.name = 'Beamline Energy'
        
        # initialize process variables
        self.VAL  = PV("BL08ID1:energy")        
        self.RBV  = PV("SMTR16082I1005:deg:sp")
        self.MOVN = PV("BL08ID1:energy:moving" )
        self.STOP = PV("BL08ID1:energy:stop")
        self.CALIB =  PV("SMTR16082I1005:calibDone")
        self.STAT =  PV("SMTR16082I1005:status")
        
        # connect monitors
        self.RBV.connect('changed', self._signal_change)
        self.MOVN.connect('changed', self._signal_move)
        self.CALIB.connect('changed', self._signal_health)
                            
        # settings
        self.MOSTAB = PV('BL08ID1:energy:enMostabChg')
        self.BEND = PV('BL08ID1:C2Bnd:enable')
        self.T1T2 = PV('BL08ID1:energy:enT1T2Chg')
        self.UND = PV('BL08ID1:energy:enGapChg')

    def _restore(self):
        self.MOSTAB.put(1)
        self.BEND.put(1)
        self.T1T2.put(1)
        self.UND.put(1)

    def get_position(self):
        return utils.bragg_to_energy(self.RBV.get())

    def set_position(self, value):
        pass
    
    def set_calibrated(self, status):
        if status:
            self.CALIB.put(1)
        else:
            self.CALIB.put(0)
            
    def move_to(self, target, wait=False):
        self._restore()
        if self.get_position() == target:
            return
        if not self.is_healthy():
            self._log( "not sane. Move canceled!" )
            return

        self._log( "moving to %f %s" % (target, self.units) )
        self.VAL.put(target)
        self.wait(start=True, stop=False)
        if wait:
            self.wait(start=False,stop=True)

    def move_by(self,val, wait=False):
        if val == 0.0:
            return
        self._log( "relative move by %g %s requested" % (val, self.units) )
        cur_pos = self.get_position()
        self.move_to(cur_pos + val, wait)
                
    def is_moving(self):
        if self.STAT.get() == 1:
            return True
        else:
            if self.MOVN.get() == 1:
                return True
            else:
                return False
    
    def is_healthy(self):
        return (self.CALIB.get() == 1) and (self.STAT.get() != 4)
                                 
    def stop(self):
        self.STOP.put(1)

    def wait(self, start=True, stop=True):
        poll = 0.05
        timeout = 2.0
        tstart = time.time()
        if (start):
            self._log('Waiting to start moving')
            while not self.is_moving() and timeout > 0:
                time.sleep(poll)
                timeout -= poll                               
        if (stop):
            self._log( 'Waiting to stop moving' )
            while self.is_moving():
                time.sleep(poll)

class braggEnergyMotor(Motor):
    """Temporary class until energy motor is standardized"""
    def __init__(self, name=None):
        Motor.__init__(self, name, motor_type='vme' )
        self.units = 'keV'
        self.name = 'Bragg Energy'
                                   
    def get_position(self):
        return utils.bragg_to_energy(self.RBV.get())
            
    def move_to(self, target, wait=False):
        if self.get_position() == target:
            return
        if not self.is_healthy():
            self._log( "not sane. Move canceled!" )
            return

        self._log( "moving to %f %s" % (target, self.units) )
        deg_target = utils.energy_to_bragg(target)
        self.VAL.put(deg_target)
        self.wait(start=True, stop=False)
        if wait:
            self.wait(start=False,stop=True)

       
class Attenuator(PositionerBase):
    def __init__(self, bit1, bit2, bit3, bit4, energy):
        PositionerBase.__init__(self)
        self.filters = [
            PV(bit1),
            PV(bit2),
            PV(bit3),
            PV(bit4) ]
        self.energy = PV(energy)
        self.units = '%'
        self.name = 'Attenuator'
        for f in self.filters:
            f.connect('changed', self._signal_change)
        self.energy.connect('changed', self._signal_change)
        
    def get_position(self):
        e = self.energy.get()
        bitmap = ''
        for f in self.filters:
            bitmap += '%d' % f.get()
        thickness = int(bitmap, 2) / 10.0
        attenuation = 1.0 - math.exp( -4.4189e12 * thickness / (e*1000+1e-6)**2.9554 )
        if attenuation < 0:
            attenuation = 0
        elif attenuation > 1.0:
            attenuation = 1.0
        return attenuation*100.0
    
    def move_to(self, target, wait=False):
        e = self.energy.get()
        if target > 99.9:
            target = 99.9
        elif target < 0.0:
            target = 0.0
        frac = target/100.0
        thickness = math.log(1.0-frac) * (e*1000+1e-6)**2.9554 / -4.4189e12
        thk = int(round(thickness * 10.0))
        if thk > 15: thk = 15
        bitmap = '%04d' % int(utils.dec_to_bin(thk))
        for i in range(4):
            self.filters[i].put( int(bitmap[i]) )
        self._log('moving to %g %s' % (target, self.units))
        self._log('requested filter states is"%s"' % bitmap)
    
    def move_by(self, value, wait=False):
        target = value + self.get_position()
        self.move_to(target, wait)
        
gobject.type_register(MotorBase)
gobject.type_register(PositionerBase)
        
