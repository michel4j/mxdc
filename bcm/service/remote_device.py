'''
Created on Nov 10, 2009

@author: michel
'''
from twisted.spread import pb, interfaces

import gobject
import random
from twisted.python.components import getRegistry
from zope.interface import Interface, implements
from twisted.python import log

class IDeviceClient(Interface):
    pass

class IDeviceServer(Interface):
    pass

class Notifier(object):
    '''Function Object for when zero argument callbacks are required'''
    
    def __init__(self, func, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.func = func
    
    def __call__(self):
        return self.func(*self.args,**self.kwargs)
    
class MasterDevice(pb.Referenceable):
    implements(IDeviceServer)
    def __init__(self, device):
        self.observers = []
        self.device = device
        self.setup(self.device) 
        
    def remote_subscribe(self, client):
        self.observers.append(client)
        notifier = Notifier(self.remote_unsubscribe, client)
        client.broker.notifyOnDisconnect(notifier)
        #log.msg('New client connected. Total : %d' % (len(self.observers)))
    
    def remote_unsubscribe(self, client):
        self.observers.remove(client)
        #log.msg('Client disconnected. Total : %d' % (len(self.observers)))

    def setup(self, device):
        #implement how to setup server here, eg connect signals
        pass
                            
    # implement extra methods for wrapping control of local server device

class SlaveDevice(pb.Referenceable):
    implements(IDeviceClient)
    def __init__(self, device):
        self.device = device
        self.device.callRemote('subscribe', self).addCallbacks(self._setupcb, log.err)
    
    def _setupcb(self, _):
        self.setup()
        
    def setup(self):
        # implement how to setup client here
        pass
    
    #implement methods here for clients to be able to control server
    
remote_registry = getRegistry()
# Add one entry for each remote device type
# eg:  registry.register([interfaces.IJellyable], IDeviceClient, 'MasterDevice', SlaveDevice)