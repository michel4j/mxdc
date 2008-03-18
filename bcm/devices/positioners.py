from zope.interface import implements
from bcm.interfaces.positioners import IMotor, IPositioner
from bcm.protocols.ca import PV
from bcm import utils
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
        "log": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
        }  

    def __init__(self):
        gobject.GObject.__init__(self)

    def _signal_change(self, obj, value):
        gobject.idle_add(self.emit,'changed', value)
    
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)
        

class MotorBase(PositionerBase):
    __gsignals__ =  { 
        "moving": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "health": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        }  

    def __init__(self):
        PositionerBase.__init__(self)
    
    def _signal_move(self, obj, state):
        if state == 0:
            is_moving = False
        else:
            is_moving = True
        gobject.idle_add(self.emit, 'moving', is_moving)
    
    def _signal_health(self, obj, state):
        if state == 0:
            is_healthy = False
        else:
            is_healthy = True
        gobject.idle_add(self.emit, 'health', is_healthy)    

    
class Motor(MotorBase):
    implements(IMotor)    
    def __init__(self, name, motor_type):
        MotorBase.__init__(self)
        name_parts = name.split(':')
        if len(name_parts)<2:
            raise MotorException("motor name must be of the format 'name:unit'")
        
        if motor_type not in ['vme', 'cls']:
            raise MotorException("motor_type must be one of 'vme', 'cls'")
          
        self.units = name_parts[1]
        self.motor_type = motor_type
        
        # initialize process variables
        self.DESC = PV("%s:desc" % (name_parts[0]))               
        self.VAL  = PV("%s:%s" % (name_parts[0],name_parts[1]))        
        if self.motor_type == 'vme':
            self.RBV  = PV("%s:%s:sp" % (name_parts[0],name_parts[1]))
            self.STAT = PV("%s:status" % name_parts[0])
            self.MOVN = PV("%s:moving" % name_parts[0])
            self.STOP = PV("%s:stop" % name_parts[0])
            self.SET  = PV("%s:%s:setPosn" % (name_parts[0],name_parts[1]))
            self.CALIB = PV("%s:calibDone" % (name_parts[0]))
        elif self.motor_type == 'cls':
            self.RBV  = PV("%s:%s:fbk" % (name_parts[0],name_parts[1]))
            self.MOVN = PV("%s:state" % name_parts[0])
            self.STAT = self.MOVN
            self.STOP = PV("%s:emergStop" % name_parts[0])
            self.CALIB = PV("%s:isCalib" % (name_parts[0]))            
        
        self.name = self.DESC.get()
        
        # connect monitors
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
            self._log( "%s is not calibrated. Move canceled!" % self.name )
            return

        self._log( "%s moving to %f %s" % (self.name, target, self.units) )
        self.VAL.put(target)
        if wait:
            self.wait(start=True,stop=True)

    def move_by(self,val, wait=False):
        if val == 0.0:
            return
        if not self.is_healthy():
            self._log("%s is not calibrated. Move canceled!" % self.name)
            return False
        self._log( "%s relative move by %f %s requested" % (self.name, val, self.units) )
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
        return (self.CALIB.get() == 1) and (self.STAT.get() != 3)
                                 
    def stop(self):
        self.STOP.put(1)
    
class vmeMotor(Motor):
    def __init__(self, name):
        Motor.__init__(self, name, motor_type = 'vme')

class clsMotor(Motor):
    def __init__(self, name):
        Motor.__init__(self, name, motor_type = 'cls')

class Positioner(PositionerBase):
    implements(IPositioner)
    
    def __init__(self, name):
        self.PV = PV(name)
        self.DESC = PV('%s.DESC' % name)
        self.name = self.DESC.get()
        self.PV.connect('changed', self._signal_change)
        
    def move_to(self, target):
        self._log('%s moving to %s' % (self.name, target))
        self.PV.put(target)

    def move_by(self, value):
        cur_position = self.get_position()
        self._log('%s relative move of %s requested' % (self.name, value))
        self.move_to(cur_position + value)
        
    def get_position(self):
        return self.PV.get()
    

class energyMotor(MotorBase):
    """Temporary class until energy motor is standardized"""
    implements(IMotor)    
    def __init__(self):
        MotorBase.__init__(self)
        self.units = 'keV'
        self.name = 'Beamline Energy'
        
        # initialize process variables
        self.VAL  = PV("BL08ID1:energy")        
        self.RBV  = PV("SMTR16082I1005:deg:sp")
        self.MOVN = PV("BL08ID1:energy:moving" )
        self.STOP = PV("BL08ID1:energy:stop")
        self.CALIB =  PV("SMTR16082I1005:calibDone")     
        
        # connect monitors
        self.RBV.connect('changed', self._signal_change)
        self.MOVN.connect('changed', self._signal_move)
        self.CALIB.connect('changed', self._signal_health)
                            
    def get_position(self):
        return utils.braggToKeV(self.RBV.get())

    def set_position(self, value):
        pass
    
    def set_calibrated(self, status):
        if status:
            self.CALIB.put(1)
        else:
            self.CALIB.put(0)
            
    def move_to(self, target, wait=False):
        if self.get_position() == target:
            return
        if not self.is_healthy():
            self._log( "%s is not calibrated. Move canceled!" % self.name )
            return

        self._log( "%s moving to %f %s" % (self.name, target, self.units) )
        self.VAL.put(target)
        if wait:
            self.wait(start=True,stop=True)

    def move_by(self,val, wait=False):
        if val == 0.0:
            return
        if not self.is_healthy():
            self._log("%s is not calibrated. Move canceled!" % self.name)
            return False
        self._log( "%s relative move by %f %s requested" % (self.name, val, self.units) )
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
        return (self.CALIB.get() == 1) and (self.STAT.get() != 3)
                                 
    def stop(self):
        self.STOP.put(1)
        
class Attenuator(PositionerBase):
    def __init__(self, bit1, bit2, bit3, bit4, energy):
        PositionerBase.__init__(self)
        self.filters = [
            PV(bit1),
            PV(bit2),
            PV(bit3),
            PV(bit4) ]
        self.energy = PV(energy)
        
        
    def get_position(self):
        e = self.energy.get()
        bitmap = ''
        for f in self.filters:
            bitmap += '%d' % f.get()
        thickness = int(bitmap, 2) / 10.0
        attenuation = 1.0 - math.exp( -4.4189e12 * thickness / (e*1000)**2.9554 )
        return attenuation
    
    def move_to(self, target):
        e = self.energy.get()
        if target > 99.9:
            target = 99.9
        elif target < 0.0:
            target = 0.0
        frac = target/100.0
        thickness = math.log(1.0-frac) * (e*1000)**2.9554 / -4.4189e12
        thk = int(round(thickness * 10.0))
        if thk > 15: thk = 15
        bitmap = '%04d' % utils.decToBin(thk)
        for i in range(4):
            self.filters[i].put( int(bitmap[i]) )
        self._log('Attenuator, moving to %s' % target)
        self._log('Attenuator, requested bit-map is"%s"' % bitmap)
    
    def move_by(self, value):
        target = value + self.get_position()
        self.move_to(target)
        
gobject.type_register(MotorBase)
gobject.type_register(PositionerBase)
        