from twisted.application import service
from twisted.internet import reactor
from twisted.spread import pb
from zope.interface import Interface, implementer

from mxdc import Registry
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class IMXDCService(Interface):

    def shutdown():
        """Shutdown MxDC"""


class IPerspectiveMXDC(Interface):

    def remote_shutdown(*args, **kwargs):
        """Shutdown MxDC"""


@implementer(IPerspectiveMXDC)
class PerspectiveMXDCFromService(pb.Root):

    def __init__(self, service):
        self.service = service

    def remote_shutdown(self, *args, **kwargs):
        """Shutdown MxDC"""
        return self.service.shutdown(*args, **kwargs)


Registry.add_adapter([IMXDCService], IPerspectiveMXDC, '', PerspectiveMXDCFromService)


@implementer(IMXDCService)
class MXDCService(service.Service):

    def shutdown(self):
        logger.warning('Remote Shutdown ...')
        reactor.stop()
