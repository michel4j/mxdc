#!/usr/bin/env python

import sys, time
import gtk, gobject
from pylab import load
import EpicsCA, numpy
from Utils import dec2bin
    
class Positioner(gobject.GObject):
    UnimplementedException = "Function Not implemented"
    __gsignals__ =  { 
                    "changed": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                                 (gobject.TYPE_FLOAT,)  ),
                    "moving": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                                 []   ),
                    "stopped": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                                 []   )
                    }  

    def __init__(self, name="Dummy Positioner"):
        gobject.GObject.__init__(self)
        self.value = 0.0
    
    def move_to(self, target, wait=False):
        """
        Moves to a new absolute position specified as the target.        
        @param target:  float
        """
        self.value = target
                
    def move_by(self, value, wait=False):
        """
        Moves a specified value relative to the current position.         
        @param value:  float
        """
        self.value += value 
                    
    def get_position(self):
        """
        Return the current position.       
        @type:  float
        """
        return self.value
        
    def set_position(self,value):
        """
        Set the position.        
        @param value:  float
        """
        self.value = value
        
    def get_name(self):
        """
        Return the name of the object.       
        @type:  string
        """
        return ''
        
    def get_id(self):
        return ''
    
    def do_changed(self, value):
        return False

class EpicsPV(Positioner):
    PositionerException = "Positioner Exception"
    def __init__(self, name=None, units=''):
        Positioner.__init__(self,name)
        if (not name):
            raise self.PositionerException, "name must be specified"
        self.name = name
        self.pv = EpicsCA.PV(name, use_monitor=False)
        self.DESC = EpicsCA.PV("%s.DESC" % self.name)
        self.units = units
        self.pv.set_monitor(callback=self._signal_change)
        self.name = name
        self.value = self.pv.value
        gobject.timeout_add(250, self._queue_check)

    def _signal_change(self, pv=None):
        gobject.idle_add(self.emit,'changed', self.pv.value)
    
    def _queue_check(self):
        gobject.idle_add(self._check_change)
        return True
                    
    def _check_change(self):
        self.changed = self.pv.check_monitor()
        return False

    def get_position(self):
        return self.pv.value

    def set_position(self, val):
        self.pv.value = val
        
    def move_to(self, val, wait=False):
        print "%s set to %f" % (self.get_name(), val)
        self.pv.value = val

    def move_by(self,val, wait=False):
        val = self.value + val
        self.pv.value = val

    def get_name(self):
        return self.DESC.value        
    
    def get_id(self):
        return self.name
        
        
class Attenuator(Positioner):
    PositionerException = "Positioner Exception"
    def __init__(self, bits, energy):
        Positioner.__init__(self,'Attenuator')
        if len(bits) != 4:
            raise PositionerException, 'needs 4 Filters 0.8, 0.4, 0.2, 0.1'
        self.filters = bits
        self.energy = energy
        self.bits = ''
        self.value = 0.0
        self._check_change()
        self.units = '%'
        gobject.timeout_add(500, self._queue_check)

    def _signal_change(self, pv=None):
        gobject.idle_add(self.emit,'changed', self.value)
    
    def _queue_check(self):
        gobject.idle_add(self._check_change)
        return True
                    
    def _check_change(self):
        self.bits = ''
        for flt in self.filters:
            self.bits += '%d' % flt.get_position()
        thickness = int(self.bits,2) / 10.0
        last_value = self.value
        self.value = self._attenuation(thickness)
        if last_value != self.value:
            self._signal_change()
        return False
        
    def _set_bits(self, bitstr):
        for i in range(4):
            self.filters[i].move_to( int(bitstr[i]) )
            
    def _attenuation(self, thck):
        energy = self.energy.get_position()
        #att = 1.0 - numpy.exp(thickness * -1e5 * numpy.exp( -0.355 * (energy*1000)**0.359))
        att = 1.0 - numpy.exp( -4.4189e12 * thck / (energy*1000)**2.9554 )
        return int( 100 * att)
    
    def _get_thickness(self, att):
        energy = self.energy.get_position()
        att_frac = att/100.0
        #thck =  numpy.log(1.0-att_frac) / ( -1e5 * numpy.exp( -0.355 * (energy*1000)**0.359))
        thck = numpy.log(1.0-att_frac) * (energy*1000)**2.9554 / -4.4189e12
        real_thck = round(thck * 10.0)/10
        if real_thck > 1.5:
            real_thck = 1.5
        return real_thck

    def get_position(self):
        return self.value

    def set_position(self, val):
        pass
                
    def move_to(self, val, wait=False):
        self.thickness = self._get_thickness(val)
        self.bits = "%04d" % int(dec2bin(int(10 * self.thickness)))
        self.value = self._attenuation(self.thickness)
        self._signal_change()
        self._set_bits(self.bits)
            
    def move_by(self,val, wait=False):
        val= (val + self.value)
        self.move_to(val)
        
    def get_name(self):
        return self.name                

class AbstractMotor(Positioner):
    MotorException = "Motor Exception"
    def __init__(self, name="Dummy Motor"):
        Positioner.__init__(self,name)
        self.name = name
            
    def stop(self):
        pass
            
    def wait(self, start=False, stop=True, poll=0.01):
        pass

    def is_moving(self):
        return False        

    def get_position(self):
        return self.value


class FakeMotor(AbstractMotor):
    def __init__(self, name="Fake Motor"):
        AbstractMotor.__init__(self,name)
        self.value = 0.0
        self.step = 0
        self.count = 0
        self.moving = False
        self.velocity = 5.0
        self.units = ''
        self.precision = 6
        self.name = name
    
    def move_to(self, val, wait=False):
        print "%s moving to %f" % (self.get_name(), val)
        time_taken = abs(val - self.value)/self.velocity
        self.count = 1 + int(time_taken/0.15)
        self.step = (val-self.value)/self.count
        self._sim()
        gobject.timeout_add(150, self._sim)
        if wait:
            self.wait(start=True,stop=True)
        return

    def copy(self):
        tmp = FakeMotor(self.name)
        return tmp
        
    def _sim(self):
        if self.count > 0:
            self.moving = True
            self.value = self.value + self.step
            self.count -= 1
            gobject.idle_add(self.emit,'moving')
            gobject.idle_add(self.emit, 'changed', self.value)
            return True
        else:
            self.moving = False
            gobject.idle_add(self.emit,'stopped')
            gobject.idle_add(self.emit, 'changed', self.value)
            print "%s stopped at %f" % (self.get_name(), self.value)
            return False
            
    def wait(self, start=False, stop=True, poll=0.01):
        #if (start):
        #    while not self.moving:
        #        time.sleep(poll)                               
        if (stop):
            while self.moving:
                time.sleep(poll)
            
    def move_by(self, value, wait=False):
        self.move_to(value,wait)
        return

    def is_moving(self):
        return self.moving
    
    def stop(self):
        self.count = 0

                                
        
class CLSMotor(AbstractMotor):
    def __init__(self, name=None,timeout=1.):
        AbstractMotor.__init__(self)
        if (not name):
            raise self.MotorException, "motor name must be specified"
        name_parts = name.split(':')
        if len(name_parts)<2:
            raise self.MotorException, "motor name must be of the format 'name:unit'"
        self.name = name
        self.units = name_parts[1]
        self.DESC = EpicsCA.PV("%s:desc" % (name_parts[0]))               
        self.VAL  = EpicsCA.PV("%s:%s" % (name_parts[0],name_parts[1]))        
        self.RBV  = EpicsCA.PV("%s:%s:sp" % (name_parts[0],name_parts[1]), use_monitor=False)
        self.ERBV = EpicsCA.PV("%s:%s:fbk" % (name_parts[0],name_parts[1]))
        self.RLV  = EpicsCA.PV("%s:%s:rel" % (name_parts[0],name_parts[1]))
        self.MOVN = EpicsCA.PV("%s:moving" % name_parts[0], use_monitor=False)
        self.ACCL = EpicsCA.PV("%s:acc:%spss:sp" % (name_parts[0],name_parts[1]))
        self.VEL  = EpicsCA.PV("%s:vel:%sps:sp" % (name_parts[0],name_parts[1]))
        self.STOP = EpicsCA.PV("%s:stop" % name_parts[0])
        self.DMOV = EpicsCA.PV("%s:stop" % name_parts[0])
        self.SET  = EpicsCA.PV("%s:%s:setPosn" % (name_parts[0],name_parts[1]))
        self.PREC = EpicsCA.PV("%s:%s.PREC" % (name_parts[0],name_parts[1]))        
        self.HLM = None
        self.LLM = None
        self.last_moving = self.is_moving()
        self.last_value = self.RBV.get()
        gobject.timeout_add(250, self._queue_check)
        self._signal_change()

    def _signal_change(self, pv=None):
        gobject.idle_add(self.emit,'changed', self.RBV.value)
    
    def _queue_check(self):
        gobject.idle_add(self._check_change)
        return True

    def copy(self):
        tmp = CLSMotor(self.get_id())
        return tmp
                    
    def _check_change(self):
        val = self.RBV.get()
        if val != self.last_value:
            gobject.idle_add(self.emit,'changed', val)
        self.last_value = val
        self.moving = self.is_moving()
        if self.moving:
            if self.last_moving != self.moving:
                gobject.idle_add(self.emit,'moving')
        elif self.last_moving != self.moving:
            gobject.idle_add(self.emit,'stopped')
            print "%s stopped at %f" % (self.get_name(), val)
        self.last_moving = self.moving
        return False
                    
    def get_position(self):
        return self.RBV.value

    def set_position(self, val):
        val = float(val)
        self.SET.value = val
                
    def move_to(self, val, wait=False):
        print "%s moving to %f" % (self.get_name(), val)
        val = float(val)
        self.VAL.value = val
        if wait:
            try:
                self.wait(start=True,stop=True)
            except  KeyboardInterrupt:
                self.stop()

    def move_by(self,val, wait=False):
        val = float(val)
        if val == None: return
        self.RLV.value = val
        if wait:
            try:
                self.wait(start=True,stop=True)
            except  KeyboardInterrupt:
                self.stop()

    def wait(self, start=False,stop=True,poll=0.01):
        if (start):
            while self.MOVN.value == 0:
                time.sleep(poll)                
        if (stop):
            while self.MOVN.value != 0:
                time.sleep(poll)
                
    def is_moving(self):
        if self.MOVN.value == 0:
            return False
        else:
            return True
                           
    def stop(self):
        self.STOP.value = 1
        
    def get_name(self):
        return self.DESC.value
    
    def get_id(self):
        return self.name
        
    def print_all(self):
        print "Motor Name: \t%s" % self.DESC.value
        print "Target position: \t%s %s" % (self.VAL.value, self.units)
        print "Current position: \t%s %s" % (self.RBV.value, self.units)
        print "Encoder position: \t%s %s" % (self.ERBV.value, self.units)
        print "Is the motor Moving?: \t%s" % self.MOVN.value
        print "Motor Acceleration: \t%s %s/s^2" % (self.ACCL.value, self.units)
        print "Motor Velocity: \t%s %s/s" % (self.VEL.value, self.units)

class OldCLSMotor(AbstractMotor):
    def __init__(self, name=None,timeout=1.):
        AbstractMotor.__init__(self)
        if (not name):
            raise self.MotorException, "motor name must be specified"
        name_parts = name.split(':')
        if len(name_parts)<2:
            raise self.MotorException, "motor name must be of the format 'name:unit'"
        import EpicsCA
        self.name = name
        self.units = name_parts[1]
        self.DESC = EpicsCA.PV("%s:desc" % (name_parts[0]))                
        self.VAL  = EpicsCA.PV("%s:%s" % (name_parts[0],name_parts[1]))        
        self.RBV  = EpicsCA.PV("%s:%s:fbk" % (name_parts[0],name_parts[1]), use_monitor=False)
        self.ERBV = EpicsCA.PV("%s:encod:fbk" % (name_parts[0]))
        self.MOVN = EpicsCA.PV("%s:state" % name_parts[0], use_monitor=False)
        self.STOP = EpicsCA.PV("%s:emergStop" % name_parts[0])
        self.PREC = EpicsCA.PV("%s:%s.PREC" % (name_parts[0],name_parts[1]))        
        self.HLM = None
        self.LLM = None
        self.moving = self.is_moving()
        self.last_moving = self.is_moving()
        self.last_value = self.RBV.get()
        gobject.timeout_add(250, self._queue_check)
        self._signal_change()

    def _signal_change(self, pv=None):
        gobject.idle_add(self.emit,'changed', self.RBV.value)
    
    def _queue_check(self):
        gobject.idle_add(self._check_change)
        return True

    def copy(self):
        tmp = OldCLSMotor(self.get_id())
        return tmp
                    
    def _check_change(self):
        val = self.RBV.get()
        if val != self.last_value:
            gobject.idle_add(self.emit,'changed', val)
        self.last_value = val
        self.moving = self.is_moving()
        if self.moving:
            if self.last_moving != self.moving:
                gobject.idle_add(self.emit,'moving')
        elif self.last_moving != self.moving:
            gobject.idle_add(self.emit,'stopped')
            print "%s stopped at %f" % (self.get_name(), val)
        self.last_moving = self.moving
        return False
                       
    def get_position(self):
        return self.RBV.value
    
    def set_position(self, val):
        return
                
    def move_to(self, val, wait=False):
        print "%s moving to %f" % (self.get_name(), val)
        val = float(val)
        if val == None: return 
        self.VAL.value = val
        if wait:
            try:
                self.wait(start=True,stop=True)
            except  KeyboardInterrupt:
                self.stop()

    def move_by(self,val, wait=False):
        val = float(val)
        if val == None: return
        self.move_to(self.VAL.value + val, wait)

    def wait(self, start=False,stop=True,poll=0.01):
        if (start):
            while self.MOVN.value == 'IDLE':
                time.sleep(poll)
                
        if (stop):
            while self.MOVN.value != 'IDLE':
                time.sleep(poll)

    def is_moving(self):
        if self.MOVN.value == 'IDLE':
            return False
        else:
            return True
                
    def stop(self):
        self.STOP.value = 1
        
    def get_name(self):
        return self.DESC.value
        
    def get_id(self):
        return self.name
              
    def print_all(self):
        print "Motor Name: \t%s" % self.DESC.value
        print "Target position: \t%s %s" % (self.VAL.value, self.units)
        print "Current position: \t%s %s" % (self.RBV.value, self.units)
        print "Encoder position: \t%s %s" % (self.ERBV.value, self.units)
        print "Is the motor Moving?: \t%s" % self.MOVN.value

def create_motor_group(motor_map):
    motors = {}
    for key in motor_map.keys():
        motors[key] = Motor( motor_map[key] )
    return motors

# Register objects with signals
gobject.type_register(Positioner)
