from twisted.internet import glib2reactor
glib2reactor.install()

from twisted.internet import protocol, reactor, threads, defer
from twisted.application import internet, service
from twisted.spread import pb
from twisted.python import components
#from twisted.manhole import telnet
from twisted.conch import manhole, manhole_ssh
from twisted.cred import portal, checkers
from twisted.python import log
from zope.interface import Interface, implements

import os, sys, time
from bcm.beamline.mx import MXBeamline
from bcm.beamline.interfaces import IBeamline
from bcm.device.remote import *
from bcm.engine import diffraction
from bcm.engine import spectroscopy

if sys.version_info[:2] == (2,5):
    import uuid
else:
    from bcm.utils import uuid # for 2.3, 2.4

def log_call(f):
    def new_f(*args, **kwargs):
        params = ['%s' % repr(a) for a in args[1:] ]
        params.extend(['%s=%s' % (p[0], repr(p[1])) for p in kwargs.items()])
        params = ', '.join(params)
        log.msg('<%s(%s)>' % (f.__name__, params))
        return f(*args,**kwargs)
    new_f.__name__ = f.__name__
    return new_f
 
class IBCMService(Interface):    
    def getConfig():
        """Get a Configuration of all beamline devices"""
        
    def getDevice(id):
        """Get a beamline device"""

    def getEngine(id):
        """Get a beamline engine"""

class IPerspectiveBCM(Interface):    
    def remote_getConfig():
        """Get a Configuration of all beamline devices"""
        
    def remote_getDevice():
        """Get a beamline device"""

    def remote_getEngine():
        """Get a beamline engine"""

class PerspectiveBCMFromService(pb.Root):
    implements(IPerspectiveBCM)
    def __init__(self, service):
        self.device_cache = {}
        self.service = service
        
    def remote_getConfig(self):
        """Get a Configuration of all beamline devices"""
        return self.service.getConfig()
        
    def remote_getDevice(self, id):
        """Get a beamline device"""
        return self.service.getDevice(id)
    
    def remote_getEngine(self, id):
        """Get a beamline device"""
        return self.service.getEngine(id)


components.registerAdapter(PerspectiveBCMFromService,
    IBCMService,
    IPerspectiveBCM)
    
class BCMService(service.Service):
    implements(IBCMService)
    
    def __init__(self):
        self.settings = {}
        self.device_server_cache = {}
        try:
            config_file = os.path.join(os.environ['BCM_CONFIG_PATH'],
                              os.environ['BCM_CONFIG_FILE'])
            self.settings['config_file'] = config_file
        except:
            log.err('Could not find Beamline Configuration')
            self.shutdown()
        d = threads.deferToThread(self._init_beamline)
        d.addCallbacks(self._service_ready, self._service_failed)
    
    def _init_beamline(self):
        self.beamline = MXBeamline(self.settings['config_file'])
        
    def _service_ready(self, result):
        self.data_collector = diffraction.DataCollector()
        log.msg('Beamline Ready')
        self.ready = True
    
    def _service_failed(self, result):
        log.msg('Could not initialize beamline. Shutting down!')
        self.shutdown()
    
    @log_call
    def getConfig(self):
        return self.beamline.device_config

    @log_call
    def getDevice(self, id):
        if self.device_server_cache.get(id, None) is not None:
            print 'Returning cached device server', id
            return self.device_server_cache[id]
        else:
            print 'Returning new device server', id
            dev = IDeviceServer(self.beamline[id])
            self.device_server_cache[id] = (dev.__class__.__name__, dev)
            return self.device_server_cache[id]
    
    @log_call
    def getEngine(self, id):
        return deffer.succeed([])
    
    @log_call
    def shutdown(self):
        reactor.stop()
           
class BCMError(pb.Error):
    """An expected Exception in BCM"""
    pass

# generate ssh factory which points to a given service
def getShellFactory(service, **passwords):
    realm = manhole_ssh.TerminalRealm()
    def getManhole(_):
        namespace = {'service': service, '_': None }
        fac = manhole.Manhole(namespace)
        fac.namespace['factory'] = fac
        return fac
    realm.chainedProtocolFactory.protocolFactory = getManhole
    p = portal.Portal(realm)
    p.registerChecker(
        checkers.InMemoryUsernamePasswordDatabaseDontUse(**passwords))
    f = manhole_ssh.ConchFactory(p)
    return f

application = service.Application('BCM')
f = BCMService()
#tf = telnet.ShellFactory()
sf = getShellFactory(f, admin='motor2bil')
#tf.setService(f)
serviceCollection = service.IServiceCollection(application)
internet.TCPServer(8880, pb.PBServerFactory(IPerspectiveBCM(f))).setServiceParent(serviceCollection)
#internet.TCPServer(4440, tf).setServiceParent(serviceCollection)        
internet.TCPServer(2220, sf).setServiceParent(serviceCollection)