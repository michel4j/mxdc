""" Remote Device servers and Client Adaptors"""

from twisted.spread import interfaces
from twisted.internet import defer
from bcm.service.utils import MasterDevice, SlaveDevice, IDeviceClient, IDeviceServer

from bcm.settings import *

class MotorServer(MasterDevice):
    __used_for__ = IMotor
    def setup(self):
        # Setup the device for all clients
        MasterDevice.setup(self)
        self.device.connect('changed', lambda x,y: self.notify_clients(changed=y))

    
    def getStateForClient(self):
        return {'units': self.device.units, 'name': self.device.name}
    
    def setup_client(self, client):
        # Setup a given client
        MasterDevice.setup_client(self, client)
        self.notify_client(client, changed=self.device.changed_state)
                          
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
            
    #implement methods here for clients to be able to control server
    #do not implement methods you don't want to expose to clients
    def move_to(self, pos, wait=False, force=False):
        return self.device.callRemote('move_to', pos, wait=False, force=False)
    
    def move_by(self, pos, wait=False, force=False):
        return self.device.callRemote('move_by', pos, wait=False, force=False)
    
    def stop(self):
        return self.device.stop()
    
    def get_position(self):
        return self.changed_state
        
    def get_state(self):
        return self.device.callRemote('get_state')
      
    @defer.deferredGenerator
    def wait(self, *args, **kwargs):
        # wait for all deferreds to fire @defer.deferredGenerator
        dlist = [self.device.callRemote('wait', *args, **kwargs)]
        waitress = defer.waitForDeferred(dlist)
        yield waitress
        _ = waitress.getResult()
        return 

class PositionerServer(MasterDevice):
    __used_for__ = IPositioner
    
    def setup(self):
        MasterDevice.setup(self)
        self.device.connect('changed', lambda x,y: self.notify_clients(changed=y))
    
    def setup_client(self, client):
        # Setup a given client
        MasterDevice.setup_client(self, client)
        self.notify_client(client, changed=self.device.changed_state)

    def getStateForClient(self):
        return {'units': getattr(self.device, 'units', '')}
                          
    def remote_set(self, *args, **kwargs):
        self.device.set(*args, **kwargs)
    
    def remote_get(self):
        return self.device.get()
            
            
class PositionerClient(SlaveDevice, PositionerBase):
    __used_for__ = interfaces.IJellyable
    
    def setup(self):
        PositionerBase.__init__(self)
        self.value = 0
            
    def set(self, pos, wait=False):
        return self.device.callRemote('set', pos)
    
    def get(self):
        return self.changed_state
    

class CounterServer(MasterDevice):
    __used_for__ = ICounter
        
    def getStateForClient(self):
        return {'name': self.device.name}
                    
    def remote_count(self, *args, **kwargs):
        self.device.count(*args, **kwargs)
    
            
            
class CounterClient(SlaveDevice):
    implements(ICounter)
    __used_for__ = interfaces.IJellyable
               
    def count(self, t):
        return self.device.callRemote('count', t)
        

class ShutterServer(MasterDevice):
    __used_for__ = IShutter
    
    def setup(self):
        MasterDevice.setup(self)
        self.device.connect('changed', lambda x,y: self.notify_clients(changed=y))
    
    def setup_client(self, client):
        MasterDevice.setup_client(self, client)
        self.notify_client(client, changed=self.device.changed_state)
    
    def getStateForClient(self):
        return {'name': self.device.name}
                          
    def remote_open(self, *args, **kwargs):
        self.device.open(*args, **kwargs)

    def remote_close(self, *args, **kwargs):
        self.device.close(*args, **kwargs)
    
                   
class ShutterClient(SlaveDevice):
    implements(IShutter)
    __used_for__ = interfaces.IJellyable
    __gsignals__ =  { 
        "changed": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_BOOLEAN,) ),
        }
                
    def is_open(self):
        """Convenience function for open state"""
        return self.changed_state
    
    def open(self):
        if not self.changed_state:
            self.device.callRemote('open')
             
    def close(self):
        if self.changed_state:
            self.device.callRemote('close')

class StorageRingServer(MasterDevice):
    __used_for__ = IStorageRing
    
    def setup(self):
        MasterDevice.setup(self)
        self.device.connect('beam', lambda x,y: self.notify_clients(beam=y))
    
    def setup_client(self, client):
        MasterDevice.setup_client(self, client)
        self.notify_client(client, beam=self.device.beam_state)
    
    def getStateForClient(self):
        return {'name': self.device.name,
                'mode': self.device.mode,
                'current': self.device.current,
                'message': self.device.message,
                'control': self.device.control,
                }
                          
    def remote_beam_available(self):
        return self.device.beam_available()

    def remote_close(self, *args, **kwargs):
        self.device.close(*args, **kwargs)
    
                   
class StorageRingClient(SlaveDevice):
    implements(IStorageRing)
    __used_for__ = interfaces.IJellyable
    __gsignals__ =  { 
        "beam": ( gobject.SIGNAL_RUN_FIRST, 
                     gobject.TYPE_NONE, 
                     (gobject.TYPE_BOOLEAN,) ),
        }
    
    @defer.deferredGenerator
    def beam_available(self):
        # wait for all deferreds to fire @defer.deferredGenerator
        dlist = [self.device.callRemote('beam_available')]
        waitress = defer.waitForDeferred(dlist)
        yield waitress
        res = waitress.getResult()
        yield res[0]
    
    @defer.deferredGenerator
    def wait_for_beam(self, *args, **kwargs):
        # wait for all deferreds to fire @defer.deferredGenerator
        d = self.device.callRemote('wait_for_beam', *args, **kwargs)
        waitress = defer.waitForDeferred(d)
        yield waitress
        _ = waitress.getResult()
        return 
        
class CryojetServer(MasterDevice):
    __used_for__ = ICryojet
        
    def getStateForClient(self):
        return {'name': self.device.name,
                'temperature': self.device.temperature,
                'sample_flow': self.device.sample_flow,
                'shield_flow': self.device.shield_flow,
                'level': self.device.level,
                'fill_status': self.device.fill_status,
                'nozzle': self.device.nozzle
                }
                    
    def remote_stop_flow(self):
        self.device.stop_flow()

    def remote_resume_flow(self):
        self.device.resume_flow()
    
                   
class CryojetClient(SlaveDevice):
    implements(ICryojet)
    __used_for__ = interfaces.IJellyable
    
    def stop_flow(self):
        self.device.callRemote('stop_flow')

    def resume_flow(self):
        self.device.callRemote('resume_flow')

class CameraServer(MasterDevice):
    __used_for__ = ICamera
        
    def getStateForClient(self):
        return {'name': self.device.name,
                'url': self.device.url,
                }
                        
                   
class CameraClient(SlaveDevice, AxisCamera):
    implements(ICamera)
    __used_for__ = interfaces.IJellyable
    
    def setup(self):
        #AxisCamera.__init__(self.hostname, self.id, self.name)
        pass

class OptimizerServer(MasterDevice):
    __used_for__ = IOptimizer
        
    def getStateForClient(self):
        return {'name': self.device.name,
                }
                        
    # convey commands to device
    def remote_start(self):
        self.device.start()
    
    def remote_stop(self):
        self.device.stop()
    
    def remote_wait(self):
        self.device.wait()
        
                   
class OptimizerClient(SlaveDevice):
    implements(IOptimizer)
    __used_for__ = interfaces.IJellyable
    
    def start(self):
        self.device.callRemote('start')
    
    def stop(self, *args, **kwargs):
        self.device.callRemote('stop')
    
    @defer.deferredGenerator
    def wait(self):
        # wait for all deferreds to fire @defer.deferredGenerator
        d = self.device.callRemote('wait')
        waitress = defer.waitForDeferred(d)
        yield waitress
        _ = waitress.getResult()
        return 


class PVServer(MasterDevice):
    __used_for__ = IProcessVariable
    
    def setup(self):
        # deliberately not calling base class setup here
        self.device.connect('active', lambda x,y: self.notify_clients(active=y))
        self.device.connect('changed', lambda x,y: self.notify_clients(changed=y))
        
    def setup_client(self, client):
        # deliberately not calling base class setup_client here
        self.notify_client(client, changed=self.device.changed_state)
        self.notify_client(client, active=self.device.active_state)
    
    def getStateForClient(self):
        return {'units': '', 'name': self.device.name}
                    
    def remote_set(self, *args, **kwargs):
        self.device.set(*args, **kwargs)
    
    def remote_get(self):
        return self.device.get()
              
class AutomounterServer(MasterDevice):
    __used_for__ = IAutomounter
    def setup(self):
        MasterDevice.setup(self)
        self.device.connect('state', lambda x,y: self.notify_clients(state=y))
        self.device.connect('message', lambda x,y: self.notify_clients(message=y))
        self.device.connect('mounted', lambda x,y: self.notify_clients(mounted=y))
        self.device.connect('progress', lambda x,y: self.notify_clients(progress=y))
        self.device.port_states.connect('changed', lambda x,y: self.notify_clients(state=y))
    
    def setup_client(self, client):
        MasterDevice.setup_client(self, client)
        self.notify_client(client, state=self.device.status_state)
        self.notify_client(client, message=self.device.message_state)
        self.notify_client(client, mounted=self.device.mounted_state)
        self.notify_client(client, progress=self.device.progress_state)
        
        
    # convey commands to device
    def remote_mount(self, *args, **kwargs):
        self.device.mount(*args, **kwargs)
    
    def remote_dismount(self, *args, **kwargs):
        self.device.dismount(*args, **kwargs)
    
    def remote_probe(self):
        return self.device.probe()
        
    def remote_wait(self, **kwargs):
        self.device.wait(**kwargs)
        

class AutomounterClient(SlaveDevice, BasicAutomounter):
    __used_for__ = interfaces.IJellyable
    implements(IAutomounter)
    def setup(self):
        BasicAutomounter.__init__(self)
        self.containers = {'L': AutomounterContainer('L'),
                          'M': AutomounterContainer('M'),
                          'R': AutomounterContainer('R') }
            
    #implement methods here for clients to be able to control server
    def mount(self, port, wash=False):
        return self.device.callRemote('mount', port, wash=False)
    
    def dismount(self, port=None):
        return self.device.callRemote('dismount', port=port)
   
    def probe(self):
        return self.device.callRemote('probe')
        
    def wait(self, state='idle'):
        return self.device.callRemote('wait', state=state)
        
    def remote_update(self, state):
        self._parse_states(state)

class DetectorServer(MasterDevice):
    __used_for__ = IImagingDetector
    
        
    def getStateForClient(self):
        return {'name': self.device.name,
                'size': self.device.size,
                'resolution': self.device.resolution,
                'detector_type': self.device.detector_type,
                }
        
    # convey commands to device
    def remote_initialize(self, wait=True):
        self.device.initialize(wait)
                        
    def remote_start(self, first=False):
        self.device.start(first)
        
    def remote_stop(self):
        self.device.stop()

    def remote_get_origin(self):
        return self.device.get_origin()
        
    def remote_save(self, wait=False):
        self.device.save()
        
    def remote_get_state(self):
        return self.device.get_state()
    
    def remote_wait(self, state='idle'):
        self.device.wait(state)
                                      
    def remote_set_parameters(self, data):
        self.device.set_parameters(data)
        

class DetectorClient(SlaveDevice):
    __used_for__ = interfaces.IJellyable
    implements(IImagingDetector)
       
    def initialize(self, wait=True):
        self.device.callRemote('initialize', wait)
                        
    def start(self, first=False):
        self.device.callRemote('start', first)
        
    def stop(self):
        self.device.callRemote('stop')

    def get_origin(self):
        return self.device.callRemote('get_origin')  
        
    def save(self, wait=False):
        self.device.callRemote('save', wait)
        
    def get_state(self):
        return self.device.callRemote('get_state')
    
    def wait(self, state='idle'):
        self.device.callRemote('wait')
                                      
    def set_parameters(self, data):
        self.device.callRemote('set_parameters', data)


# Optimizer
registry.register([IOptimizer], IDeviceServer, '', OptimizerServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'OptimizerServer', OptimizerClient)

# Detector
registry.register([IImagingDetector], IDeviceServer, '', DetectorServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'DetectorServer', DetectorClient)
   
# Automounter
registry.register([IAutomounter], IDeviceServer, '', AutomounterServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'AutomounterServer', AutomounterClient)

# Counters
registry.register([ICounter], IDeviceServer, '', CounterServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'CounterServer', CounterClient)

# StorageRing
registry.register([IStorageRing], IDeviceServer, '', StorageRingServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'StorageRingServer', StorageRingClient)

# Video
registry.register([ICamera], IDeviceServer, '', CameraServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'CameraServer', CameraClient)

# Cryojet
registry.register([ICryojet], IDeviceServer, '', CryojetServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'CryojetServer', CryojetClient)

# Shutters
registry.register([IShutter], IDeviceServer, '', ShutterServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'ShutterServer', ShutterClient)
  
# Positioners and PVs
registry.register([IPositioner], IDeviceServer, '', PositionerServer)
registry.register([IProcessVariable], IDeviceServer, '', PVServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'PositionerServer', PositionerClient)
registry.register([interfaces.IJellyable], IDeviceClient, 'PVServer', PositionerClient)

# Motors
registry.register([IMotor], IDeviceServer, '', MotorServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'MotorServer', MotorClient)

