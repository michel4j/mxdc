from twisted.application import service
from twisted.internet import reactor, defer
from twisted.python import components
from twisted.spread import pb
from zope.interface import Interface, implements

from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class IMXDCService(Interface):
    def send_message(msg):
        """Send a Message"""

    def shutdown():
        """Shutdown MxDC"""


class IPerspectiveMXDC(Interface):
    def remote_send_message(*args, **kwargs):
        """Send a Message"""

    def remote_shutdown(*args, **kwargs):
        """Shutdown MxDC"""


class PerspectiveMXDCFromService(pb.Root):
    implements(IPerspectiveMXDC)

    def __init__(self, service):
        self.service = service

    def remote_send_message(self, *args, **kwargs):
        """Send a message"""
        return self.service.send_message(*args, **kwargs)

    def remote_shutdown(self, *args, **kwargs):
        """Shutdown MxDC"""
        return self.service.shutdown(*args, **kwargs)


components.registerAdapter(PerspectiveMXDCFromService, IMXDCService, IPerspectiveMXDC)


class MXDCService(service.Service):
    implements(IMXDCService)

    def __init__(self, messenger=None):
        self.messenger = messenger

    def send_message(self, msg):
        if self.messenger is not None:
            self.messenger.emit(msg)
        return defer.succeed([])

    def shutdown(self):
        logger.warning('Remote Shutdown ...')
        reactor.stop()
