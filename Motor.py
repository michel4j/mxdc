#!/usr/bin/env python

import sys, time
import gtk, gobject
#from pylab import load
from EPICS import *
import numpy
from Utils import dec2bin
from LogServer import LogServer
    
class Positioner(gobject.GObject):
    UnimplementedException = "Function Not implemented"
    __gsignals__ =  { 
                    "changed": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                                 (gobject.TYPE_FLOAT,)  ),
                    "moving": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                                 (gobject.TYPE_BOOLEAN,)   ),
                    "valid": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                                 (gobject.TYPE_BOOLEAN,)   )
                    }  

    def __init__(self, name="Dummy Positioner"):
        gobject.GObject.__init__(self)
        self.value = 0.0
        self.name = name
    
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

    def is_valid(self):
        return True     
        
    def get_name(self):
        """
        Return the name of the object.       
        @type:  string
        """
        return self.name
        
    def get_id(self):
        return self.name
    
    def do_changed(self, value):
        return False

class EpicsPositioner(Positioner):
    PositionerException = "Positioner Exception"
    def __init__(self, name=None, units=''):
        Positioner.__init__(self,name)
        if (not name):
            raise self.PositionerException, "name must be specified"
        self.name = name
        self.pv = PV(name)
        self.DESC = PV("%s.DESC" % self.name)
        self.units = units
        self.pv.connect('changed', self._signal_change )
        self.name = name
        self.last_position = self.pv.get()

    def _signal_change(self, obj=None, arg=None):
        gobject.idle_add(self.emit,'changed', self.get_position())
    
    def get_position(self):
        return self.pv.get()

    def set_position(self, val):
        self.pv.put(val)
        
    def move_to(self, val, wait=False):
        LogServer.log( "%s set to %f" % (self.get_name(), val) )
        self.pv.put(val)

    def move_by(self,val, wait=False):
        val = self.value + val
        self.pv.put(val)

    def get_name(self):
        return self.DESC.get()        
    
        
        
class Attenuator(Positioner):
    PositionerException = "Positioner Exception"
    def __init__(self, bits, energy):
        Positioner.__init__(self,'Attenuator')
        if len(bits) != 4:
            raise PositionerException, 'needs 4 Filters 0.8, 0.4, 0.2, 0.1'
        self.filters = bits
        self.energy = energy
        self.bits = '0000'
        self.value = 0.0
        self.units = '%'
        self.energy.connect('changed', self._signal_change )
        for fil in self.filters:
            fil.connect('changed', self._signal_change )   

    def _signal_change(self, obj=None, arg=None):
        gobject.idle_add(self.emit,'changed', self.get_position() )
    
        
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
        self.bits = ''
        for flt in self.filters:
            self.bits += '%d' % flt.get_position()
        thickness = int(self.bits,2) / 10.0
        self.value = self._attenuation(thickness)
        return self.value

    def set_position(self, val):
        pass
                
    def move_to(self, val, wait=False):
        self.thickness = self._get_thickness(val)
        self.bits = "%04d" % int(dec2bin(int(10 * self.thickness)))
        self._set_bits(self.bits)
        
            
    def move_by(self,val, wait=False):
        val= (val + self.value)
        self.move_to(val)
        
class AbstractMotor(Positioner):
    MotorException = "Motor Exception"
    def __init__(self, name="Dummy Motor"):
        Positioner.__init__(self,name)
        self.last_moving = False
        self.last_validity = False
        self.last_position = 0.0
        self.name = name
        self.interval = 0.25
        self.tick = time.time()
            
    def _signal_change(self, obj=None, arg=None):
        if (time.time() - self.tick) > self.interval:
            gobject.idle_add(self.emit,'changed', self.get_position())
            self.tick = time.time()
    
    def _signal_move(self, obj=None, arg=None):
        gobject.idle_add(self.emit,'moving', self.is_moving())
        
    def _signal_validity(self, obj=None, arg=None):
        gobject.idle_add(self.emit,'valid', self.is_valid())

    def set_calibrated(status):
        pass
    
    def stop(self):
        pass

    def is_moving(self):
        return False
    
    def wait(self, start=False, stop=True, poll=0.01):
        if (start):
            LogServer.log( 'Waiting for %s to start moving' % self.get_name() )
            while not self.is_moving():
                time.sleep(poll)                               
        if (stop):
            LogServer.log( 'Waiting for %s to stop moving' % self.get_name() )
            while self.is_moving():
                time.sleep(poll)
                
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
        LogServer.log( "%s moving to %f" % (self.get_name(), val) )
        time_taken = abs(val - self.value)/self.velocity
        self.count = 1 + int(time_taken/0.15)
        self.step = (val-self.value)/self.count
        self._sim()
        gobject.timeout_add(250, self._sim)
        if wait:
            self.wait(start=True,stop=True)
        return

    def _sim(self):
        if self.count > 0:
            self.moving = True
            self.value = self.value + self.step
            self.count -= 1
            gobject.idle_add(self.emit,'moving', True)
            gobject.idle_add(self.emit, 'changed', self.value)
            return True
        else:
            self.moving = False
            gobject.idle_add(self.emit,'moving', False)
            gobject.idle_add(self.emit, 'changed', self.value)
            LogServer.log( "%s stopped at %f %s" % (self.get_name(), self.value, self.units))
            return False            
            
    def move_by(self, value, wait=False):
        target = self.get_position() + value
        self.move_to(target,wait)
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
        self.DESC = PV("%s:desc" % (name_parts[0]))               
        self.VAL  = PV("%s:%s" % (name_parts[0],name_parts[1]))        
        self.RBV  = PV("%s:%s:sp" % (name_parts[0],name_parts[1]))
        self.ERBV = PV("%s:%s:fbk" % (name_parts[0],name_parts[1]))
        self.RLV  = PV("%s:%s:rel" % (name_parts[0],name_parts[1]))
        self.MOVN = PV("%s:status" % name_parts[0])
        #self.MOVN = PV("%s:moving" % name_parts[0])
        self.ACCL = PV("%s:acc:%spss:sp" % (name_parts[0],name_parts[1]))
        self.VEL  = PV("%s:vel:%sps:sp" % (name_parts[0],name_parts[1]))
        self.STOP = PV("%s:stop" % name_parts[0])
        self.SET  = PV("%s:%s:setPosn" % (name_parts[0],name_parts[1]))
        self.CALIB = PV("%s:calibDone" % (name_parts[0]))   
        self.RBV.connect('changed', self._signal_change )
        self.MOVN.connect('changed', self._signal_move )
        self.CALIB.connect('changed', self._signal_validity )

                    
    def get_position(self):
        return self.RBV.get()

    def set_calibrated(self,status):
        if status:
            self.CALIB.put(1)
        else:
            self.CALIB.put(0)
            
    def move_to(self, val, wait=False):
        if not self.is_valid():
            LogServer.log ( "%s is not calibrated. Move cancelled!" % (self.get_name()) )
            gobject.idle_add(self.emit,"valid", False)
            return False
        LogServer.log ( "%s moving to %f %s" % (self.get_name(), val, self.units) )
        self.VAL.put(val)
        if wait:
            self.wait(start=True,stop=True)

    def move_by(self,val, wait=False):
        if not self.is_valid():
            LogServer.log ( "%s is not calibrated. Move cancelled!" % (self.get_name()) )
            gobject.idle_add(self.emit,"valid", False)
            return False
        LogServer.log ( "%s moving by %f %s" % (self.get_name(), val, self.units) )
        self.RLV.put(val)
        if wait:
            self.wait(start=True,stop=True)
                
    def is_moving(self):
        if self.MOVN.get() == 1:
            return True
        else:
            return False
    
    def is_valid(self):
        if self.CALIB.get() == 0:
            return False
        else:
            return True
        return False
                                 
    def stop(self):
        self.STOP.put(1)
        
    def get_name(self):
        return self.DESC.get()
            

class OldCLSMotor(AbstractMotor):
    def __init__(self, name=None,timeout=1.):
        AbstractMotor.__init__(self)
        if (not name):
            raise self.MotorException, "motor name must be specified"
        name_parts = name.split(':')
        if len(name_parts)<2:
            raise self.MotorException, "motor name must be of the format 'name:unit'"
        self.name = name
        self.units = name_parts[1]
        self.DESC = PV("%s:desc" % (name_parts[0]))                
        self.VAL  = PV("%s:%s" % (name_parts[0],name_parts[1]))        
        self.RBV  = PV("%s:%s:fbk" % (name_parts[0],name_parts[1]))
        self.ERBV = PV("%s:encod:fbk" % (name_parts[0]))
        self.MOVN = PV("%s:state" % name_parts[0])
        self.STOP = PV("%s:emergStop" % name_parts[0])
        self.CALIB =   PV("%s:isCalib" % (name_parts[0]))     
        self.moving = self.is_moving()
        self.last_moving = self.is_moving()
        self.last_validity = self.is_valid()
        self.last_position = self.RBV.get()
        self.RBV.connect('changed', self._signal_change )
        self.MOVN.connect('changed', self._signal_move )
        self.CALIB.connect('changed', self._signal_validity )

    def get_position(self):
        return self.RBV.get()
    
                
    def move_to(self, val, wait=False):
        if not self.is_valid():
            LogServer.log ( "%s is not calibrated. Move cancelled!" % (self.get_name()) )
            gobject.idle_add(self.emit,"valid", False)
            return False
        LogServer.log("%s moving to %f %s" % (self.get_name(), val, self.units))
        self.VAL.put(val)
        if wait:
            self.wait(start=True,stop=True)

    def move_by(self,val, wait=False):
        if not self.is_valid():
            LogServer.log ( "%s is not calibrated. Move cancelled!" % (self.get_name()) )
            gobject.idle_add(self.emit,"valid", False)
            return False
        self.move_to(self.VAL.get() + val, wait)

    def is_moving(self):
        if self.MOVN.get() == 'IDLE':
            return False
        else:
            return True
                
    def is_valid(self):
        if self.CALIB.get() == 0:
            return False
        else:
            return True
        return False
            
    def stop(self):
        self.STOP.put(1)
        
    def get_name(self):
        return self.DESC.get()
                      

# Register objects with signals
gobject.type_register(Positioner)
