import math
import time
import gobject
from zope.interface import implements
from bcm import registry
from bcm.protocol.ca import PV
from bcm.protocol import ca
from bcm.device.base import BaseDevice, BaseDeviceGroup
from bcm.utils.log import get_module_logger
from bcm.utils import converter, misc
from bcm.device.interfaces import *
from bcm.device.motor import MotorBase
from bcm.utils.decorators import async

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class PositionerBase(BaseDevice):
    implements(IPositioner)
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_PYOBJECT,)),
        }  

    def __init__(self):
        BaseDevice.__init__(self)
        self.units = ''
               
    def _signal_change(self, obj, value):
        self.set_state(changed=self.get())
    
    def set(self, pos):
        raise exceptions.NotImplementedError
    
    def get(self):
        raise exceptions.NotImplementedError


class SimPositioner(PositionerBase):
    def __init__(self, name, pos=0, units=""):
        PositionerBase.__init__(self)
        self.name = name
        self._pos = float(pos)
        self.units = units
        self.set_state(changed=self._pos)
        
    def set(self, pos):
        self._pos = pos
        self.set_state(changed=self._pos)

    def get(self):
        return self._pos

 
class Positioner(PositionerBase):
    def __init__(self, name, fbk_name=None, scale=None, units=""):
        PositionerBase.__init__(self)
        self.set_pv = self.add_pv(name)
        try:
            self.scale = float(scale)
        except:
            self.scale = None
        if fbk_name is None:
            self.fbk_pv = self.set_pv
        else:
            self.fbk_pv = self.add_pv(fbk_name)
        self.DESC = PV('%s.DESC' % name) # device should work without desc pv so not using add_pv
        self.name = name
        if scale is None:
            self.units = units
        else:
            self.units = '%'
        self.fbk_pv.connect('changed', self._signal_change)
        self.DESC.connect('changed', self._on_name_change)

    def _on_name_change(self, pv, val):
        if val != '':
            self.name = val
            
    def __repr__(self):
        return '<%s:%s, target:%s, feedback:%s>' %( self.__class__.__name__,
                                                    self.name,
                                                    self.set_pv.name,
                                                    self.fbk_pv.name )
    def set(self, pos):
        if self.scale is None:
            self.set_pv.set(pos)
        else:
            val = self.scale * pos/100.0
            self.set_pv.set(val)
          
    def get(self):
        if self.scale is None:
            return self.fbk_pv.get()
        else:
            val = 100.0 * (self.fbk_pv.get()/self.scale)
            return  val
    
         
class PositionerMotor(MotorBase):
    implements(IMotor)
    __used_for__ = IPositioner
    
    def __init__(self, positioner):
        MotorBase.__init__(self, 'Positioner Motor')
        self.positioner = positioner
        self.name = positioner.name
        self.units = positioner.units
        self.positioner.connect('changed', self._signal_change)
    
    def configure(self, props):
        pass
    
    def move_to(self, pos, wait=False):
        self.positioner.set(pos)
    
    def move_by(self, val, wait=False):
        self.positioner.set( self.positioner.get() + val )
    
    def stop(self):
        pass
        
    def get_position(self):
        return self.positioner.get()
    
    def wait(self):
        ca.flush()

registry.register([IPositioner], IMotor, '', PositionerMotor)
    
class Attenuator(BaseDevice):

    implements(IPositioner)
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_PYOBJECT,)),
        }  
    
    def __init__(self, bitname, energy):
        BaseDevice.__init__(self)
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
        if self._energy.connected():
            e = self._energy.get()
        else:
            return 999.0
        bitmap = ''
        for f in self._filters:
            if f.connected():
                bitmap += '%d' % f.get()
            else:
                return 999.0
        thickness = int(bitmap, 2) / 10.0
        if e < .1:
            e = 0.1
        if e > 100:
            e = 100.0
        attenuation = 1.0 - math.exp( -4.4189e12 * thickness / 
                                        (e*1000+1e-6)**2.9554 )
        if attenuation < 0:
            attenuation = 0
        elif attenuation > 1.0:
            attenuation = 1.0
        return attenuation*100.0
    
    def _set_bits(self, bitmap):
        for i in range(4):
            self._filters[i].put( int(bitmap[i]) )
        
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
        self._set_bits(bitmap)
        _logger.info('Attenuation of %f %s requested' % (target, self.units))
        _logger.debug('Filters [8421] set to [%s] (0=off,1=on)' % bitmap)
    
    def _signal_change(self, obj, value):
        self.set_state(changed=self.get())


class Attenuator2(Attenuator):  
    def __init__(self, bitname, energy):
        BaseDevice.__init__(self)
        fname = bitname[:-1]
        self._filters = [
            PV('%s4:ctl' % fname),
            PV('%s3:ctl' % fname),
            PV('%s2:ctl' % fname),
            PV('%s1:ctl' % fname),
            ]
        self._open = [
            PV('%s4:opr:open' % fname),
            PV('%s3:opr:open' % fname),
            PV('%s2:opr:open' % fname),
            PV('%s1:opr:open' % fname),
            ]
        self._close = [
            PV('%s4:opr:close' % fname),
            PV('%s3:opr:close' % fname),
            PV('%s2:opr:close' % fname),
            PV('%s1:opr:close' % fname),
            ]
        self._energy = PV(energy)
        self.units = '%'
        self.name = 'Attenuator'
        for f in self._filters:
            f.connect('changed', self._signal_change)
        self._energy.connect('changed', self._signal_change)

    def _set_bits(self, bitmap):
        for i in range(4):
            val = int(bitmap[i])
            if self._filters[i].get() == val:
                continue
            if val == 1:
                self._close[i].put(1)
            else:
                self._open[i].put(1)
                   

class BasicShutter(BaseDevice):

    implements(IShutter)
    
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_BOOLEAN,)  ),
        }
          
    def __init__(self, open_name, close_name, state_name):
        BaseDevice.__init__(self)
        # initialize variables
        self._open_cmd = self.add_pv(open_name)
        self._close_cmd = self.add_pv(close_name)
        self._state = self.add_pv(state_name)
        self._state.connect('changed', self._signal_change)
        self._messages = ['Opening', 'Closing']
        self.name  = open_name.split(':')[0]
    
    def is_open(self):
        """Convenience function for open state"""
        return self.changed_state
    
    def open(self):
        if self.changed_state:
            return 
        _logger.debug(' '.join([self._messages[0], self.name]))
        self._open_cmd.set(1)
        ca.flush()
        self._open_cmd.set(0)
    
    def close(self):
        if not self.changed_state:
            return 
        _logger.debug(' '.join([self._messages[1], self.name]))
        self._close_cmd.set(1)
        ca.flush()
        self._close_cmd.set(0)

    def _signal_change(self, obj, value):
        if value == 1:
            self.set_state(changed=True)
        else:
            self.set_state(changed=False)


class ShutterGroup(BaseDevice):
    implements(IShutter)
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_BOOLEAN,)  ),
        }
    
    def __init__(self, *args, **kwargs):
        BaseDevice.__init__(self)
        self._dev_list = args 
        self.add_devices(*self._dev_list)
        self.name  = 'Beamline Shutters'
        for dev in self._dev_list:
            dev.connect('changed', self._on_change)
            
    def is_open(self):
        """Convenience function for open state"""
        return self.changed_state
    
    def _on_change(self, obj, val):
        if val:
            if misc.all([dev.changed_state for dev in self._dev_list]):
                self.set_state(changed=True)
        else:
            self.set_state(changed=False)
    @async
    def open(self):
        for dev in self._dev_list:
            if dev.changed_state == False:
                dev.open()
                while not dev.changed_state:
                    time.sleep(0.1)
    @async
    def close(self):
        newlist = self._dev_list[:]
        newlist.reverse()
        for dev in newlist:
            dev.close()
            while dev.changed_state:
                time.sleep(0.1)
        

        
class SimShutter(BaseDevice):
    
    implements(IShutter)
    
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_PYOBJECT,)),
        }

    def __init__(self,name):
        BaseDevice.__init__(self)
        self.name = name
        self._state = False
        self.set_state(active=True, changed=self._state)

    def open(self):
        self._state = True
        self.set_state(changed=True )

    def close(self):
        self._state = False
        self.set_state(changed=False )

   
class Shutter(BasicShutter):
    def __init__(self, name):
        open_name = "%s:opr:open" % name
        close_name = "%s:opr:close" % name
        state_name = "%s:state" % name
        BasicShutter.__init__(self, open_name, close_name, state_name)


   
class XYZStage(BaseDeviceGroup):

    implements(IStage)
    
    def __init__(self, x, y, z, name='XYZ Stage'):
        BaseDeviceGroup.__init__(self)
        self.name = name
        self.x  = x
        self.y  = y
        self.z  = z
        self.add_devices(x, y, z)
                                
    def wait(self):
        self.x.wait()
        self.y.wait()
        self.z.wait()

    def stop(self):
        self.x.stop()
        self.y.stop()
        self.z.stop()

class SampleStage(BaseDeviceGroup):

    implements(IStage)
    
    def __init__(self, x, y1, y2, omega, name='Sample Stage'):
        BaseDeviceGroup.__init__(self)
        from bcm.device.motor import RelVerticalMotor
        self.name = name
        self.x  = x
        self.y  = RelVerticalMotor(y1, y2, omega)
        self.add_devices(x, y1, y2)
                                            
    def wait(self):
        self.x.wait()
        self.y.wait()

    def stop(self):
        self.x.stop()
        self.y.stop()
 

class XYStage(BaseDeviceGroup):
    implements(IStage)
    def __init__(self, x, y, name='XY Stage'):
        BaseDeviceGroup.__init__(self)
        self.name = name
        self.x  = x
        self.y  = y
        self.add_devices(x, y)
                                            
    def wait(self):
        self.x.wait()
        self.y.wait()

    def stop(self):
        self.x.stop()
        self.y.stop()


class Collimator(BaseDeviceGroup):

    implements(ICollimator)
    
    def __init__(self, x, y, width, height, name='Collimator'):
        BaseDeviceGroup.__init__(self)
        self.name = name
        self.x  = x
        self.y = y
        self.width  = width
        self.height = height
        self.add_devices(x, y, width, height)
                                            
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



        
        
class HumidityController(BaseDevice):
    implements(IHumidityController)
    
    def __init__(self, root_name):
        BaseDevice.__init__(self)
        self.name = 'Humidity Controller'
        self.relative_humidity = Positioner('%s:SetpointRH' % root_name,'%s:RH' % root_name)
        self.sample_temperature = self.add_pv('%s:SampleTemp' % root_name)
        self.drop_size = self.add_pv('%s:DropSize' % root_name)
        self.ROI = Positioner('%s:ROI' % root_name)
        self.status = self.add_pv('%s:State' % root_name)
        self.add_devices(self.relative_humidity, self.ROI)
        
    
    def set_humidity(self, val):
        self.relative_humitidy.set(val)
    


class StorageRing(BaseDevice):
    implements(IStorageRing)
    __gsignals__ =  { 
        "beam": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_BOOLEAN,)),
        }  
    
    def __init__(self, pv1, pv2, pv3):
        BaseDevice.__init__(self)
        self.name = "Storage Ring"
        self.mode = self.add_pv(pv1)
        self.current = self.add_pv(pv2)
        self.control = self.add_pv('%s:shutters' % pv3)
        self.message = self.add_pv('%s:msg:L1' % pv3)
        
        self.mode.connect('changed', self._on_mode_change)
        self.current.connect('changed', self._on_current_change)
        self.control.connect('changed', self._on_control_change)
        self._last_current = 0.0
        
    def beam_available(self):
        return ( self.current.get() > 5.0 and self.mode.get() ==4 and self.control.get() == 1)
    
    def wait_for_beam(self, timeout=60):
        while not self.beam_available() and timeout > 0:
            time.sleep(0.05)
            timeout -= 0.05
        _logger.warn('Timed out waiting for beam!')
    
    def _on_mode_change(self, obj, val):
        if val != 4:
            self.set_state(health=(1,'mode', self.message.get()))
        else:
            self.set_state(health=(0,'mode'))
            
        if self.beam_available():
            self.set_state(beam=True)
        else:
            self.set_state(beam=False)

    def _on_control_change(self, obj, val):
        if val != 1:
            self.set_state(health=(4, 'control','Shutters disabled'))
        else:
            self.set_state(health=(0,'control'))
            
        if self.beam_available():
            self.set_state(beam=True)
        else:
            self.set_state(beam=False)

    def _on_current_change(self, obj, val):
        if val <= 5:
            self.set_state(health=(4,'beam','No beam'))
        else:
            self.set_state(health=(0,'beam'))
            
        if self.beam_available():
            self.set_state(beam=True)
        else:
            self.set_state(beam=False)
        
      
from twisted.spread import interfaces
from bcm.service.utils import MasterDevice, SlaveDevice, IDeviceClient, IDeviceServer

class PositionerServer(MasterDevice):
    __used_for__ = IPositioner
    
    def setup(self, device):
        device.connect('changed', self.on_change)
    
    def getStateForClient(self):
        return {'units': self.device.units}                   
    # route signals to remote
    def on_change(self, obj, pos):
        for o in self.observers: o.callRemote('changed', pos)
      
    def remote_set(self, *args, **kwargs):
        self.device.set(*args, **kwargs)
    
    def remote_get(self):
        return self.device.get()
            
            
class PositionerClient(SlaveDevice, PositionerBase):
    __used_for__ = interfaces.IJellyable
    
    def setup(self):
        PositionerBase.__init__(self)
        self.value = 0
            
    def set(self, pos):
        return self.device.callRemote('set', pos)
    
    def get(self):
        return self.value
        #return self.device.callRemote('get')
    
    def remote_changed(self, value):
        self.value = value
        gobject.idle_add(self.emit,'changed', value)    
    
# Positioners
registry.register([IPositioner], IDeviceServer, '', PositionerServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'PositionerServer', PositionerClient)
       
