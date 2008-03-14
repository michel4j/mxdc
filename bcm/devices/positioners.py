from zope.interface import implements
from bcm.interfaces.positioners import IMotor
from bcm.protocols.ca import PV
from bcm import utils
    
class PositionerException(Exception):
    def __init__(self,message):
        self.message = message

class MotorException(PositionerException):
    pass

class PositonerBase(gobject.GObject):
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)),
        "log": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
        }  

    def __init__(self):
        gobject.GObject.__init__(self)

class MotorBase(gobject.GObject):
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)),
        "moving": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "health": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "log": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
        }  

    def __init__(self):
        gobject.GObject.__init__(self)
    
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
                            
    def getPosition(self):
        return self.RBV.get()

    def setPosition(self, value):
        if self.motor_type == 'vme':
            self.SET.put(value)

    def setCalibrated(self, status):
        if status:
            self.CALIB.put(1)
        else:
            self.CALIB.put(0)
            
    def moveTo(self, target, wait=False):
        if self.getPosition() == target:
            return
        if not self.isHealthy():
            self._log( "%s is not calibrated. Move canceled!" % self.name )
            return

        self._log( "%s moving to %f %s" % (self.name, target, self.units) )
        self.VAL.put(target)
        if wait:
            self.wait(start=True,stop=True)

    def moveBy(self,val, wait=False):
        if val == 0.0:
            return
        if not self.isHealthy():
            self._log("%s is not calibrated. Move canceled!" % self.name)
            return False
        self._log( "%s relative move by %f %s requested" % (self.name, val, self.units) )
        cur_pos = self.getPosition()
        self.moveTo(cur_pos + val, wait)
                
    def isMoving(self):
        if self.STAT.get() == 1:
            return True
        else:
            if self.MOVN.get() == 1:
                return True
            else:
                return False
    
    def isHealthy(self):
        return (self.CALIB.get() == 1) and (self.STAT.get() != 3)
                                 
    def stop(self):
        self.STOP.put(1)
    
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)
    
    def _signal_change(self, object, position):
        gobject.idle_add(self.emit, 'changed', position)
    
    def _signal_move(self, object, state):
        if state == 0:
            is_moving = False
        else:
            is_moving = True
        gobject.idle_add(self.emit, 'moving', is_moving)
    
    def _signal_health(self, object, state):
        if state == 0:
            is_healthy = False
        else:
            is_healthy = True
        gobject.idle_add(self.emit, 'health', is_healthy)    

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
        
    def moveTo(self, target):
        self._log('%s moving to %s' % (self.name, target))
        self.PV.put(target)

    def moveBy(self, value):
        cur_position = self.getPosition()
        self._log('%s relative move of %s requested' % (self.name, value))
        self.moveTo(cur_position + value)
        
    def getPosition(self):
        return self.PV.get()
    
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)
        
    def _signal_change(self, object, position):
        gobject.idle_add(self.emit, 'changed', position)


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
                            
    def getPosition(self):
        return utils.braggToKeV(self.RBV.get())

    def setPosition(self, value):
        pass
    
    def setCalibrated(self, status):
        if status:
            self.CALIB.put(1)
        else:
            self.CALIB.put(0)
            
    def moveTo(self, target, wait=False):
        if self.getPosition() == target:
            return
        if not self.isHealthy():
            self._log( "%s is not calibrated. Move canceled!" % self.name )
            return

        self._log( "%s moving to %f %s" % (self.name, target, self.units) )
        self.VAL.put(target)
        if wait:
            self.wait(start=True,stop=True)

    def moveBy(self,val, wait=False):
        if val == 0.0:
            return
        if not self.isHealthy():
            self._log("%s is not calibrated. Move canceled!" % self.name)
            return False
        self._log( "%s relative move by %f %s requested" % (self.name, val, self.units) )
        cur_pos = self.getPosition()
        self.moveTo(cur_pos + val, wait)
                
    def isMoving(self):
        if self.STAT.get() == 1:
            return True
        else:
            if self.MOVN.get() == 1:
                return True
            else:
                return False
    
    def isHealthy(self):
        return (self.CALIB.get() == 1) and (self.STAT.get() != 3)
                                 
    def stop(self):
        self.STOP.put(1)
    
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)
    
    def _signal_change(self, object, position):
        gobject.idle_add(self.emit, 'changed', position)
    
    def _signal_move(self, object, state):
        if state == 0:
            is_moving = False
        else:
            is_moving = True
        gobject.idle_add(self.emit, 'moving', is_moving)
    
    def _signal_health(self, object, state):
        if state == 0:
            is_healthy = False
        else:
            is_healthy = True
        gobject.idle_add(self.emit, 'health', is_healthy)    
    

gobject.type_register(MotorBase)
gobject.type_register(PositionerBase)
        