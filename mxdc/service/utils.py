'''
Created on Nov 10, 2009

@author: michel
'''
import exceptions
from twisted.spread import pb

from gi.repository import GObject
from mxdc.device.base import BaseDevice
from zope.interface import Interface, implements
from twisted.python import log
from twisted.internet import  threads, defer
import numpy

def log_call(f):
    def new_f(*args, **kwargs):
        params = ['%s' % repr(a) for a in args[1:] ]
        params.extend(['%s=%s' % (p[0], repr(p[1])) for p in kwargs.items()])
        params = ', '.join(params)
        log.msg('<%s(%s)>' % (f.__name__, params))
        return f(*args,**kwargs)
    new_f.__name__ = f.__name__
    return new_f

def defer_to_thread(func):
    def wrap(*args, **kwargs):
        return threads.deferToThread(func, *args, **kwargs)
    return wrap

def send_array(arr):
    if arr is None:
        return None
    return [arr.tostring(), arr.dtype.char, arr.shape]

def recv_array(arr_list):
    if arr_list is None:
        return None
    return numpy.fromstring(arr_list[0], arr_list[1]).reshape(arr_list[2])

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
        self.setup()
    
    def getStateForClient(self):
        return {}
    
    def notify_clients(self, **kw):
        for o in self.observers: 
            self.notify_client(o, **kw)

    def notify_client(self, client, **kw):
        client.callRemote('notify', **kw)
    
    def remote_subscribe(self, client):
        self.observers.append(client)
        notifier = Notifier(self.remote_unsubscribe, client)
        client.broker.notifyOnDisconnect(notifier)
        client.callRemote('setState', self.getStateForClient())
        self.setup_client(client)
        
    def setup_client(self, client):
        # Override this method to perform certain actions when a client connects
        self.notify_client(client, active=self.device.active_state)
        self.notify_client(client, health=self.device.health_state)
        self.notify_client(client, busy=self.device.busy_state)
        self.notify_client(client, message=self.device.message_state)
        
    def remote_unsubscribe(self, client):
        self.observers.remove(client)
        log.msg('Client disconnected. Total : %d' % (len(self.observers)))

    def setup(self):
        # Override this method to setup the device for all clients
        self.device.connect('health', lambda x,y: self.notify_clients(health=y))
        self.device.connect('busy', lambda x,y: self.notify_clients(busy=y))
        self.device.connect('active', lambda x,y: self.notify_clients(active=y))
        self.device.connect('message', lambda x,y: self.notify_clients(message=y))
        
                            
    # implement extra methods for wrapping control of local server device

class SlaveDevice(pb.Referenceable, BaseDevice):
    implements(IDeviceClient)
    def __init__(self, device):
        BaseDevice.__init__(self)
        self.setup()
        self.device = device
        self._prepare_state()
        print self.__dict__
    
    def remote_notify(self, **kw):
        self.set_state(**kw)
        
    def remote_setState(self, state):
        for k,v in state.items():
            setattr(self, k, v)
    
    @defer.deferredGenerator
    def _prepare_state(self):
        d = self.device.callRemote('subscribe', self).addErrback(log.err)
        waitress = defer.waitForDeferred(d)
        yield waitress
        _ = waitress.getResult()
        return
       
    def setup(self):
        # implement how to setup client here
        pass
    
    #implement methods here for clients to be able to control server
    #according to the provided interface
    
# Add one entry for each remote device type
# eg:  registry.register([interfaces.IJellyable], IDeviceClient, 'MasterDevice', SlaveDevice)
