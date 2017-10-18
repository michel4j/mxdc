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

    def join(user):
        """Join the chat"""

    def leave(user):
        """Leave the chat"""

    def shutdown():
        """Shutdown MxDC"""


class IPerspectiveMXDC(Interface):
    def remote_join(*args, **kwargs):
        """Join Chat"""

    def remote_leave(*args, **kwargs):
        """Leave Chat"""

    def remote_send_message(*args, **kwargs):
        """Send a Message"""

    def remote_shutdown(*args, **kwargs):
        """Shutdown MxDC"""


class PerspectiveMXDCFromService(pb.Root):
    implements(IPerspectiveMXDC)

    def __init__(self, service):
        self.service = service

    def remote_join(self, *args, **kwargs):
        """Join Chat"""
        return self.service.join(*args, **kwargs)

    def remote_leave(self, *args, **kwargs):
        """Leave Chat"""
        return self.service.leave(*args, **kwargs)

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
        self.messenger.set_root(self)
        self.clients = set()

    def join(self, user):
        self.clients.add(user)

    def leave(self, user):
        self.clients.discard(user)

    def send_message(self, user, msg):
        self.messenger.show(user, msg)
        missing = set()
        for client in self.clients:
            try:
                client.callRemote('show', user, msg)
            except pb.DeadReferenceError as e:
                missing.add(client)
        self.clients -= missing
        return defer.succeed([])

    def shutdown(self):
        logger.warning('Remote Shutdown ...')
        reactor.stop()
