from enum import Enum

from zope.interface import implementer

from mxdc import Registry, Property, Object
from mxdc.utils.log import get_module_logger
from .interfaces import IDiagnostic

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


@implementer(IDiagnostic)
class Diagnostic(Object):
    """
    Base class for diagnostics.
    """

    class State(Enum):
        GOOD, WARN, BAD, UNKNOWN, DISABLED = list(range(5))

    state = Property(type=object)
    message = Property(type=str, default='')

    def __init__(self, descr):
        super(Diagnostic, self).__init__()
        self.description = descr
        self.props.state = self.State.UNKNOWN
        Registry.subscribe(IDiagnostic, self)

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
    """
    A diagnostic object for generic devices which emits a warning when the
    devices health is not good and an error when it is disconnected or disabled.

    :param device: the device to  monitor
    :param descr:  Short description of the diagnostic.
    """

    def __init__(self, device, descr=None):
        descr = descr if descr else device.name
        super(DeviceDiag, self).__init__(descr)
        self.device = device
        self.device.connect('health', self.on_health_change)

    def on_health_change(self, obj, severity, context, message):
        if severity < 2:
            state = self.State.GOOD
            message = 'OK!' if not message else message
        elif severity < 4:
            state = self.State.WARN
        elif severity < 16:
            state = self.State.BAD
        else:
            state = self.State.DISABLED
        self.props.state = state
        self.props.message = message


class ServiceDiag(Diagnostic):
    """
    A diagnostic object for generic services which emits an error when it is
    disconnected or disabled.

    :param device: the device to  monitor
    """

    def __init__(self, service):
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
