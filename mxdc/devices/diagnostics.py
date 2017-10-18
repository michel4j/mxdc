from enum import Enum
from gi.repository import GObject
from interfaces import IDiagnostic
from mxdc.devices.base import HealthManager
from mxdc.utils.log import get_module_logger
from twisted.python.components import globalRegistry
from zope.interface import implements

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class Diagnostic(GObject.GObject):
    """
    Base class for diagnostics.
    """
    implements(IDiagnostic)

    class State(Enum):
        GOOD, WARN, BAD, UNKNOWN, DISABLED = range(5)

    state = GObject.property(type=object)
    message = GObject.property(type=str, default='')

    def __init__(self, descr):
        super(Diagnostic, self).__init__()
        self.description = descr
        self._manager = HealthManager()
        self.props.state = self.State.UNKNOWN
        globalRegistry.subscribe([], IDiagnostic, self)

    def __repr__(self):
        return "<{}:'{}', status:{}>".format(
            self.__class__.__name__, self.description, self.state[0].name
        )

    def update_status(self, status, msg):
        if status != self.state or msg != self.message:
            self.props.state = status
            self.props.message = msg
            if status != self.State.GOOD:
                logger.warning("{}: {}".format(self.description, msg))


class DeviceDiag(Diagnostic):
    """A diagnostic object for generic devices which emits a warning when the
    devices health is not good and an error when it is disconnected or disabled.
    """

    def __init__(self, device, descr=None):
        """
        Args:
            `devices` (a class::`devices.base.BaseDevice` object) the devices to
            monitor.
            
        Kwargs:
            `descr` (str): Short description of the diagnostic.
        """
        descr = descr if descr else device.name
        super(DeviceDiag, self).__init__(descr)
        self.device = device
        self.device.connect('health', self.on_health_change)

    def on_health_change(self, obj, hlth):
        state, descr = hlth
        if state < 2:
            descr = 'OK!' if not descr else descr
            params = (self.State.GOOD, descr)
        elif state < 4:
            params = (self.State.WARN, descr)
        elif state < 16:
            params = (self.State.BAD, descr)
        else:
            params = (self.State.DISABLED, descr)
        self.update_status(*params)


class ServiceDiag(Diagnostic):
    """A diagnostic object for generic services which emits an error when it is
    disconnected or disabled.
    """

    def __init__(self, service):
        """
        Args:
            `services` (a class::`services.base.BaseService` object) the services to
            monitor.

        """
        super(ServiceDiag, self).__init__(service.name)
        self.service = service
        self.service.connect('active', self.on_active)
        self.name = service.name

    def on_active(self, obj, val):
        if val:
            params = (self.State.GOOD, 'OK!')
        else:
            params = (self.State.BAD, 'Not available!')
        self.update_status(*params)


__all__ = ['DeviceDiag', 'ServiceDiag']
