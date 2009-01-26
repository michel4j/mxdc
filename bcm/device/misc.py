import time
import math
import gobject
from zope.interface import implements
from bcm.protocol.ca import PV
from bcm.utils.log import get_module_logger
from bcm.utils import converter
from bcm.device.interfaces import IPositioner, IShutter

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class MiscDeviceError(Exception):

    """Base class for errors in the misc module."""


class PositionerBase(gobject.GObject):
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_PYOBJECT,)),
        }  

    def __init__(self):
        gobject.GObject.__init__(self)

    def _signal_change(self, obj, value):
        gobject.idle_add(self.emit,'changed', self.get_position() )
            
        
        
class Attenuator(PositionerBase):

    implements(IPositioner)
    
    def __init__(self, bit1, bit2, bit3, bit4, energy):
        PositionerBase.__init__(self)
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
        
    def get_position(self):
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
    
    def set_position(self, target):
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
    
    

class Shutter(gobject.GObject):

    implements(misc.IShutter)
    
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
        self._open_cmd.put(1)
    
    def close(self):
        self._close_cmd.put(1)

    def _signal_change(self, obj, value):
        if value == 1:
            gobject.idle_add(self.emit,'changed', True)
        else:
            gobject.idle_add(self.emit,'changed', False)
        
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)




class Cryojet(gobject.GObject):
    __gsignals__ =  { 
        "sample-flow": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)  ),
        "shield-flow": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)  ),
        "level": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)  ),
        "temperature": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)  ),
        "status": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)  ),
        }
    
    def __init__(self, cname, lname):
        gobject.GObject.__init__(self)        
        self.temp_fbk = PV('%s:sensorTemp:get' % cname)
        self.temp = PV('%s:desiredTemp:set' % cname)
        self.smpl_flow_fbk = PV('%s:SampleFlow:get' % cname)
        self.smpl_flow = PV('%s:sampleFlow:set' % cname)
        self.shld_flow_fbk = PV('%s:ShieldFlow:get' % cname)
        self.shld_flow = PV('%s:shieldFlow:set' % cname)
        self.level_fbk = PV('%s:ch1LVL:get' % lname)
        self.level_sts = PV('%s:status:ch1:N.SVAL' % lname)
        
        self.level_fbk.connect('changed', self.on_level_changed)
        self.shld_flow_fbk.connect('changed', self.on_shield_changed)
        self.smpl_flow_fbk.connect('changed', self.on_sample_changed)
        self.temp_fbk.connect('changed', self.on_temperature_changed)
        self.level_sts.connect('changed', self.on_status_changed)
        self.previous_flow = 6.0
        
    def on_level_changed(self, pv, val):
        gobject.idle_add(self.emit, 'level', val*0.1)
        return True
    
    def on_sample_changed(self, pv, val):
        gobject.idle_add(self.emit, 'sample-flow', val)
        return True
    
    def on_temperature_changed(self, pv, val):
        gobject.idle_add(self.emit, 'temperature', val)
        return True
    
    def on_shield_changed(self, pv, val):
        gobject.idle_add(self.emit, 'shield-flow', val)
        return True
    
    def on_status_changed(self, pv, val):
        gobject.idle_add(self.emit, 'status', val)
        
    def set_temperature(self, t=100):
        self.temp.put(t)
    
    def get_temperature(self):
        return self.temp_fbk.get()
    
    def set_sample_flow(self, f=8.0):
        self.smpl_flow.put(f)
    
    def get_sample_flow(self):
        return self.smpl_flow_fbk.get()
    
    def set_shield_flow(self, f=5.0):
        self.shld_flow.put(f)
    
    def get_shield_flow(self):
        return self.shld_flow.get()
    
    def get_level(self):
        return 0.1 * self.level_fbk.get()
    
    def get_status(self):
        return self.level_sts.get()
    
    def resume_flow(self):
        self.smpl_flow.put(self.previous_flow)
    
    def stop_flow(self):
        self.previous_flow = self.smpl_flow_fbk.get()
        self.smpl_flow.put(0.0)
    
    temperature = property(get_temperature, set_temperature)
    sample_flow = property(get_sample_flow, set_sample_flow)
    shield_flow = property(get_shield_flow, set_shield_flow)
    level = property(get_level)
    status = property(get_status)

        
# Register objects with signals
gobject.type_register(Shutter)
gobject.type_register(PositionerBase)
gobject.type_register(Cryojet)
