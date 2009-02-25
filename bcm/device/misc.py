import time
import math
import gobject
from zope.interface import implements
from bcm import registry
from bcm.protocol.ca import PV
from bcm.protocol import ca
from bcm.utils.log import get_module_logger
from bcm.utils import converter
from bcm.device.interfaces import *


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class MiscDeviceError(Exception):

    """Base class for errors in the misc module."""


class Positioner(gobject.GObject):

    implements(IPositioner)
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_PYOBJECT,)),
        }  

    def __init__(self, name, fbk_name=None, units=""):
        gobject.GObject.__init__(self)
        self.set_pv = PV(name)
        if fbk_name is None:
            self.fbk_pv = self.set_pv
        else:
            self.fbk_pv = PV(fbk_name)
        self.name = name
        self.units = units
        self.fbk_pv.connect('changed', self._signal_change)
    
    def __repr__(self):
        return '<%s:%s, target:%s, feedback:%s>' %( self.__class__.__name__,
                                                    self.name,
                                                    self.set_pv.name,
                                                    self.fbk_pv.name )
   
    def set(self, pos):
        self.set_pv.set(pos)
    
    def get(self):
        return self.fbk_pv.get()
    
    def _signal_change(self, obj, value):
        gobject.idle_add(self.emit,'changed', self.get())

           
class PositionerMotor(object):
    implements(IMotor)
    __used_for__ = IPositioner
    
    def __init__(self, positioner):
        self.positioner = positioner
        self.name = positioner.name
        self.units = positioner.units
    
    def configure(self, props):
        pass
    
    def move_to(self, pos, wait=False):
        self.positioner.set(pos)
    
    def move_by(self, val, wait=False):
        self.positioner.set( self.positioner.get() + val )
    
    def stop(self):
        pass
    
    def get_state(self):
        return 0
    
    def get_position(self):
        return self.positioner.get()
    
    def wait(self):
        ca.flush()

registry.register([IPositioner], IMotor, '', PositionerMotor)
    
class Attenuator(gobject.GObject):

    implements(IPositioner)
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_PYOBJECT,)),
        }  
    
    def __init__(self, bitname, energy):
        gobject.GObject.__init__(self)
        fname = bitname[:-1]
        self._filters = [
            PV('%s4:bit' % fname),
            PV('%s3:bit' % fname),
            PV('%s2:bit' % fname),
            PV('%s1:bit' % fname),
            ]
        self._energy = PV(energy)
        self.units = '%'
        self.name = 'Attenuator'
        for f in self._filters:
            f.connect('changed', self._signal_change)
        self._energy.connect('changed', self._signal_change)
        
    def get(self):
        e = self._energy.get()
        bitmap = ''
        for f in self._filters:
            bitmap += '%d' % f.get()
        thickness = int(bitmap, 2) / 10.0
        attenuation = 1.0 - math.exp( -4.4189e12 * thickness / 
                                        (e*1000+1e-6)**2.9554 )
        if attenuation < 0:
            attenuation = 0
        elif attenuation > 1.0:
            attenuation = 1.0
        return attenuation*100.0
    
    def set(self, target):
        e = self._energy.get()
        if target > 99.9:
            target = 99.9
        elif target < 0.0:
            target = 0.0
        frac = target/100.0
        
        # calculate required aluminum thickness
        thickness = math.log(1.0-frac) * (e*1000+1e-6)**2.9554 / -4.4189e12
        thk = int(round(thickness * 10.0))
        if thk > 15: thk = 15
        
        # bitmap of thickness is fillter pattern
        bitmap = '%04d' % int(converter.dec_to_bin(thk))
        for i in range(4):
            self._filters[i].put( int(bitmap[i]) )
        _logger.info('Attenuation of %f %s requested' % (target, self.units))
        _logger.debug('Filters [8421] set to [%s] (0=off,1=on)' % bitmap)
    
    def _signal_change(self, obj, value):
        gobject.idle_add(self.emit,'changed', self.get())
    

class Shutter(gobject.GObject):

    implements(IShutter)
    
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_BOOLEAN,)  ),
        }
          
    def __init__(self, name):
        gobject.GObject.__init__(self)
        # initialize variables
        self._open_cmd = PV("%s:opr:open" % name, monitor=False)
        self._close_cmd = PV("%s:opr:close" % name, monitor=False)
        self._state = PV("%s:state" % name)
        self._state.connect('changed', self._signal_change)

    def get_state(self):
        return self._state.get() == 1
    
    def open(self):
        self._open_cmd.set(1)
    
    def close(self):
        self._close_cmd.set(1)

    def _signal_change(self, obj, value):
        if value == 1:
            gobject.idle_add(self.emit,'changed', True)
        else:
            gobject.idle_add(self.emit,'changed', False)
        
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)




class Cryojet(object):
    
    implements(ICryojet)
    
    def __init__(self, cname, lname, nozzle_motor):
        self.temperature = Positioner('%s:sensorTemp:get' % cname,
                                      '%s:sensorTemp:get' % cname,
                                      'K')
        self.sample_flow = Positioner('%s:sampleFlow:set' % cname,
                                      '%s:SampleFlow:get' % cname,
                                      'L/min')
        self.shield_flow = Positioner('%s:shieldFlow:set' % cname,
                                      '%s:ShieldFlow:get' % cname,
                                      'L/min')
        self.level = PV('%s:ch1LVL:get' % lname)
        self.nozzle = IMotor(nozzle_motor)
        self.fill_status = PV('%s:status:ch1:N.SVAL' % lname)
        self._previous_flow = 6.0
            
    def get_state(self):
        return self.fill_status.get()
    
    def resume_flow(self):
        self.sample_flow.set(self._previous_flow)
    
    def stop_flow(self):
        self._previous_flow = self.sample_flow.get()
        self.sample_flow.set(0.0)

   
class Stage(object):

    implements(IStage)
    
    def __init__(self, x, y, z, name='XYZ Stage'):
        self.name = name
        self.x  = x
        self.y  = y
        self.z  = z
                    
    def get_state(self):
        return self.x.get_state() | self.y.get_state() | self.z.get_state() 
                        
    def wait(self):
        self.x.wait()
        self.y.wait()
        self.z.wait()

    def stop(self):
        self.x.stop()
        self.y.stop()
        self.z.stop()


class Collimator(object):

    implements(ICollimator)
    
    def __init__(self, x, y, width, height, name='Collimator'):
        self.name = name
        self.x  = x
        self.y = y
        self.width  = width
        self.height = height
                    
    def get_state(self):
        return (self.width.get_state() | 
                self.height.get_state() | 
                self.x.get_state() |
                self.y.get_state()) 
                        
    def wait(self):
        self.width.wait()
        self.height.wait()
        self.x.wait()
        self.y.wait()

    def stop(self):
        self.width.stop()
        self.height.stop()
        self.x.stop()
        self.y.stop()


class MostabOptimizer(object):
    
    implements(IOptimizer)
    
    def __init__(self, name):
        self._start = ca.PV('%s:Mostab:opt:cmd' % name)
        self._stop = ca.PV('%s:abortFlag' % name)
        self._state1 = ca.PV('%s:optRun'% name)
        self._state2 = ca.PV('%s:optDone'% name)
        self._status = 0
        self._command_active = False
        self._state1.connect('changed', self._state_change)
        self._state2.connect('changed', self._state_change)
        
        
    def _state_change(self, obj, val):
        if self._state1.get() > 0:
            self._status =  1
            self._command_active = False
        elif self._state2.get() >0:
            self._status = 0
        
    def start(self):
        self._command_active = True
        self._start.put(1)
        
    
    def stop(self):
        self._stop.put(1)
    
    def get_state(self):
        return self._status

    def wait(self):
        poll=0.05
        while self._status == 1 or self._command_active:
            time.sleep(poll)
       
# Register objects with signals
gobject.type_register(Shutter)
gobject.type_register(Positioner)
gobject.type_register(Attenuator)
