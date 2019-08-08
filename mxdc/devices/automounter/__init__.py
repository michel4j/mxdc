import time

from enum import Enum
from zope.interface import implementer
from gi.repository import GObject

from mxdc.devices.base import BaseDevice
from mxdc.devices.interfaces import IAutomounter
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class State(Enum):
    IDLE, PREPARING, BUSY, STANDBY, DISABLED, WARNING, FAILURE, ERROR = list(range(8))


def set_object_properties(obj, kwargs):
    for k,v in list(kwargs.items()):
        obj.set_property(k,v)

@implementer(IAutomounter)
class AutoMounter(BaseDevice):


    layout = GObject.Property(type=object)
    sample = GObject.Property(type=object)
    next_port = GObject.Property(type=str)
    ports = GObject.Property(type=object)
    containers = GObject.Property(type=object)
    status = GObject.Property(type=object)
    failure = GObject.Property(type=object)

    def __init__(self):
        super(AutoMounter, self).__init__()
        self.name = 'Automounter'
        self.state_history = set()
        self.props.layout = {}
        self.props.sample = {}
        self.props.ports = {}
        self.props.containers = set()
        self.props.status = State.IDLE
        self.state_link = self.connect('notify::status', self._record_state)
        self.connect('notify::status', self._emit_state)

    def configure(self,**kwargs):
        GObject.idle_add(set_object_properties, self, kwargs)

    def _emit_state(self, *args, **kwargs):
        self.set_state(busy=(self.props.status == State.BUSY))

    def _watch_states(self):
        """
        Enable automounter state monitoring
        """
        self.handler_unblock(self.state_link)

    def _unwatch_states(self):
        """
        disable automounter state monitoring
        """
        self.handler_block(self.state_link)
        self.state_history = set()

    def _record_state(self, *args, **kwargs):
        """
        Record all state changes into a set
        """
        self.state_history.add(self.props.status)

    def recover(self, failure):
        """
        Recover from a specific failure type

        @param failure:
        @return:
        """
        logger.error('Recovery procedure {} not implemented'.format(failure))

    def prefetch(self, port, wait=False):
        """
        For automounters which support pre-fetching. Prefetch the next sample for mounting
        @param port: next port to mount
        @param wait: boolean, wait for prefetch to complete
        @return:
        """
        pass

    def prepare(self):
        """
        Get ready to start
        @return:
        """
        if self.is_ready() or self.is_preparing():
            self.configure(status=State.PREPARING)
            return True
        else:
            return False

    def cancel(self):
        """
        Cancel Standby state
        @return:
        """
        if self.is_preparing():
            self.configure(status=State.IDLE)
            return True
        else:
            return False

    def mount(self, port, wait=False):
        """
        Mount the sample at the given port. Must take care of preparing the end station
        and dismounting any mounted samples before mounting
        @param port: str, the port to mount
        @param wait: bool, whether to block until operation is completed
        @return: bool, True if successful
        """
        raise NotImplementedError('Sub-classes must implement mount method')

    def dismount(self, wait=False):
        """
        Dismount the currently mounted sample.
        Must take care of preparing the end station
        and dismounting any mounted samples before mounting
        @return: bool, True if successful
        """
        raise NotImplementedError('Sub-classes must implement dismount method')

    def abort(self):
        """
        Abort current operation
        @return:
        """
        raise NotImplementedError('Sub-classes must implement dismount method')

    def wait(self, states=(State.IDLE,), timeout=60):
        """
        Wait for the given state to be attained
        @param states: requested state to wait for or a list of states
        @param timeout: maximum time to wait
        @return: bool, True if state was attained or False if timeout was exhausted
        """

        if self.status not in states:
            logger.debug('Waiting for {}:{}'.format(self.name, states))
            time_remaining = timeout
            poll = 0.05
            while time_remaining > 0 and not self.status in states:
                time_remaining -= poll
                time.sleep(poll)
                if self.status == State.FAILURE:
                    break

            if time_remaining <= 0:
                logger.warning('Timed out waiting for {}:{}'.format(self.name, states))
                return False
            elif self.status == State.FAILURE:
                logger.warning('{} operation failed.'.format(self.name))
                return False
        return True

    def is_mountable(self, port):
        """
        Check if the specified port can be mounted successfully
        @param port: str representation of the port
        @return: bool, True if it is mounted
        """
        raise NotImplementedError('Sub-classes must implement is_mountable method')

    def is_valid(self, port):
        """
        Check if the specified port is a valid port designation for this automounter
        @param port: str representation of the port
        @return: bool, True if it is valid
        """
        raise NotImplementedError('Sub-classes must implement is_valid method')

    def is_mounted(self, port=None):
        """
        Check if the specified port is mounted
        @param port: str representation of the port or None if checking for any
        @return: bool, True if it is mounted
        """
        return bool(
                (port is None and bool(self.sample)) or
                ((port is not None) and self.sample and self.sample.get('port') == port)
        )

    def is_ready(self):
        """
        Check if the automounter is ready for an operation
        @return:
        """
        return (self.status in [State.IDLE] and self.is_active() and not self.is_busy())

    def is_preparing(self):
        """
        Check if the automounter is preparing to start
        @return:
        """
        return (self.status == State.PREPARING)