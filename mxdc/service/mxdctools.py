from twisted.internet import reactor, defer
from twisted.application import internet, service
from twisted.spread import pb
from twisted.python import components
from zope.interface import Interface, implements
from mxdc.utils.log import get_module_logger

_logger = get_module_logger(__name__)

 
class IMXDCService(Interface):    
    def sendMessage(self, msg):
        """Send a Message"""

    def shutdown(self):
        """Shutdown MxDC"""

class IPerspectiveMXDC(Interface):    
    def remote_sendMessage(self, msg):
        """Send a Message"""
        
    def remote_shutdown(self):
        """Shutdown MxDC"""

class PerspectiveMXDCFromService(pb.Root):
    implements(IPerspectiveMXDC)
    def __init__(self, service):
        self.service = service
        
    def remote_sendMessage(self, msg):
        """Send a message"""
        return self.service.sendMessage(msg)
        
    def remote_shutdown(self):
        """Shutdown MxDC"""
        return self.service.shutdown()
    

components.registerAdapter(PerspectiveMXDCFromService,
    IMXDCService,
    IPerspectiveMXDC)
    
class MXDCService(service.Service):
    implements(IMXDCService)

    def __init__(self, messenger=None):
        self.messenger = messenger
        
    def sendMessage(self, msg):
        if self.messenger is not None:
                self.messenger.emit(msg)
        return defer.succeed([])

    def shutdown(self):
        _logger.warning('Remote Shutdown ...')
        reactor.stop()
           