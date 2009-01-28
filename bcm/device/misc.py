import time
import math
import gobject
from zope.interface import implements
from bcm.protocol.ca import PV
from bcm.utils.log import get_module_logger
from bcm.utils import converter
from bcm.device.interfaces import IPositioner, IShutter, ICryojet

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class MiscDeviceError(Exception):

    """Base class for errors in the misc module."""


class Positioner(gobject.GObject):
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_PYOBJECT,)),
        }  

    def __init__(self, name, fbk_name, units=""):
        gobject.GObject.__init__(self)
        self.set_pv = PV(name)
        self.fbk_pv = PV(fbk_name)
        self.units = units
        self.fbk_pv.connect('changed', self._signal_change)
    
    def set(self, pos):
        self.set_pv.set(pos)
    
    def get(self):
        return self.fbk_pv.get()
    
    def _signal_change(self, obj, value):
        gobject.idle_add(self.emit,'changed', self.get())
            
        
        
class Attenuator(gobject.GObject):

    implements(IPositioner)
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_PYOBJECT,)),
        }  
    
    def __init__(self, bit1, bit2, bit3, bit4, energy):
        gobject.GObject.__init__(self)
        self._filters = [
            PV(bit1),
            PV(bit2),
            PV(bit3),
            PV(bit4) ]
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
        bitmap = '%04d' % int(utils.dec_to_bin(thk))
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
    
    def __init__(self, cname, lname):
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
        self._level_status = PV('%s:status:ch1:N.SVAL' % lname)
        self._previous_flow = 6.0
            
    def get_state(self):
        return self._level_status.get()
    
    def resume_flow(self):
        self.sample_flow.set(self._previous_flow)
    
    def stop_flow(self):
        self._previous_flow = self.sample_flow.get()
        self.sample_flow.set(0.0)
    
        
# Register objects with signals
gobject.type_register(Shutter)
gobject.type_register(Positioner)
gobject.type_register(Attenuator)
