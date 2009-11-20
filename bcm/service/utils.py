'''
Created on Nov 10, 2009

@author: michel
'''
import exceptions
from twisted.spread import pb, interfaces

import gobject
import random
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
        self.setup(device) 
    
    def getStateForClient(self):
        return {}
    
    def notify_clients(self, *args):
        for o in self.observers: o.callRemote('notify', *args)
    
    def remote_subscribe(self, client):
        self.observers.append(client)
        notifier = Notifier(self.remote_unsubscribe, client)
        client.broker.notifyOnDisconnect(notifier)
        client.callRemote('setState', self.getStateForClient())
        self.setup_client(client)
        
    def setup_client(self, client):
        # Override this method to perform certain actions when a client connects
       pass
        
    def remote_unsubscribe(self, client):
        self.observers.remove(client)
        #log.msg('Client disconnected. Total : %d' % (len(self.observers)))

    def setup(self, device):
        #implement how to setup server here, eg connect signals
        raise exceptions.NotImplementedError
                            
    # implement extra methods for wrapping control of local server device

class SlaveDevice(pb.Referenceable):
    implements(IDeviceClient)
    def __init__(self, device):
        self.setup()
        self.device = device
        self.device.callRemote('subscribe', self).addErrback(log.err)
    
    def remote_notify(self, *args):
        gobject.idle_add(self.emit, *args)
        
    def remote_setState(self, state):
        for k,v in state.items():
            setattr(self, k, v)
            
    def setup(self):
        # implement how to setup client here
        raise exceptions.NotImplementedError
    
    #implement methods here for clients to be able to control server
    
# Add one entry for each remote device type
# eg:  registry.register([interfaces.IJellyable], IDeviceClient, 'MasterDevice', SlaveDevice)