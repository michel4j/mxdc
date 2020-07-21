import time

from enum import Enum
from zope.interface import implementer
from gi.repository import GLib

from mxdc import Device, Property, Signal
from mxdc.devices.interfaces import IAutomounter
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class State(Enum):
    IDLE, PREPARING, BUSY, STANDBY, DISABLED, WARNING, FAILURE, ERROR = list(range(8))


def set_object_properties(obj, kwargs):
    for k,v in list(kwargs.items()):
        obj.set_property(k,v)

@implementer(IAutomounter)
class AutoMounter(Device):
    """
    Base class for all Sample Automounters.

    Properties:
        - **layout**: container layout dictionary
        - **sample**: mounted sample
        - **next_port**: next port to mount
        - **containers**: container meta-data
        - **status**: automounter status
        - **failure**: failure meta-data
    """

    class Signals:
        layout = Signal('layout', arg_types=(object,))
        sample = Signal('sample', arg_types=(object,))
        next_port =Signal('next-port', arg_types=(object,))
        ports = Signal('ports', arg_types=(object,))
        containers = Signal('containers', arg_types=(object,))
        status = Signal('status', arg_types=(object,))
        failure = Signal('failure', arg_types=(object,))

    def __init__(self):
        super().__init__()
        self.name = 'Automounter'
        self.state_history = set()
        self.set_state(
            layout={}, sample={}, ports={}, containers=set(), status=State.IDLE, busy=False
        )
        self.state_link = self.connect('status', self._record_state)
        self.connect('status', self._emit_state)

    def configure(self, **kwargs):
        """
        Configure the automounter

        :param kwargs: Accepted kwargs are the same as the device properties.
        """
        pass

    def _emit_state(self, obj, status):
        self.set_state(busy=(status == State.BUSY))

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

    def _record_state(self, obj, status):
        """
        Record all state changes into a set
        """
        self.state_history.add(status)

    def recover(self, failure):
        """
        Recover from a specific failure type

        :param failure:  Failure type
        """
        logger.error('Recovery procedure {} not implemented'.format(failure))

    def prefetch(self, port, wait=False):
        """
        For automounters which support pre-fetching. Prefetch the next sample for mounting

        :param port: next port to mount
        :param wait: boolean, wait for prefetch to complete
        """
        pass

    def prepare(self):
        """
        Get ready to start.
        """
        if self.is_ready() or self.is_preparing():
            self.set_state(status=State.PREPARING)
            return True
        else:
            return False

    def cancel(self):
        """
        Cancel Standby state
        """
        if self.is_preparing():
            self.set_state(status=State.IDLE)
            return True
        else:
            return False

    def mount(self, port, wait=False):
        """
        Mount the sample at the given port. Must take care of preparing the end station
        and dismounting any mounted samples before mounting

        :param port: str, the port to mount
        :param wait: bool, whether to block until operation is completed
        :return: bool, True if successful
        """
        raise NotImplementedError('Sub-classes must implement mount method')

    def dismount(self, wait=False):
        """
        Dismount the currently mounted sample.
        Must take care of preparing the end station
        and dismounting any mounted samples before mounting
        :return: bool, True if successful
        """
        raise NotImplementedError('Sub-classes must implement dismount method')

    def abort(self):
        """
        Abort current operation
        """
        raise NotImplementedError('Sub-classes must implement dismount method')

    def wait_until(self, *states, timeout=20.0):
        """
        Wait for a maximum amount of time until the state is one of the specified states, or busy
        if no states are specified.

        :param states: states to check for. Attaining any of the states will terminate the wait
        :param timeout: Maximum time in seconds to wait
        :return: True if state was attained, False if timeout was reached.
        """

        states = states if len(states) else (State.BUSY,)
        states_text = "|".join((str(s) for s in states))

        logger.debug('"{}" Waiting for {}'.format(self.name, states_text))
        elapsed = 0
        status = self.get_state('status')
        while elapsed <= timeout and status not in states:
            elapsed += 0.05
            time.sleep(0.05)
            status = self.get_state('status')
            if status == State.FAILURE:
                break

        if elapsed <= timeout:
            logger.debug('"{}": {} attained after {:0.2f}s'.format(self.name, status, elapsed))
            return True
        elif status == State.FAILURE:
            logger.warning('{} operation failed.'.format(self.name))
            return False
        else:
            logger.warning('"{}" timed-out waiting for "{}"'.format(self.name, states_text))
            return False

    def wait_while(self, *states, timeout=20.0):
        """
        Wait for a maximum amount of time while the state is one of the specified states, or not busy
        if no states are specified.

        :param state: states to check for. Attaining a state other than any of the states will terminate the wait
        :param timeout: Maximum time in seconds to wait
        :return: True if state was attained, False if timeout was reached.
        """

        states = states if len(states) else (State.BUSY,)
        states_text = "|".join([str(state) for state in states])

        logger.debug('"{}" Waiting while {}'.format(self.name, states_text))
        elapsed = 0
        status = self.get_state('status')
        while elapsed <= timeout and status in states:
            elapsed += 0.05
            time.sleep(0.05)
            status = self.get_state('status')
            if status == State.FAILURE:
                break

        if elapsed <= timeout:
            logger.debug('"{}": not {} after {:0.2f}s'.format(self.name, status, elapsed))
            return True
        elif status == State.FAILURE:
            logger.warning('{} operation failed.'.format(self.name))
            return False
        else:
            logger.warning('"{}" timed-out waiting in "{}"'.format(self.name, states_text))
            return False

    def wait(self, states=(State.IDLE,), timeout=60):
        """
        Wait for the given state to be attained

        :param states: requested state to wait for or a list of states
        :param timeout: maximum time to wait
        :return: bool, True if state was attained or False if timeout was exhausted
        """

        return self.wait_until(*states, timeout=timeout)

    def is_mountable(self, port):
        """
        Check if the specified port can be mounted successfully

        :param port: str representation of the port
        :return: bool, True if it is mounted
        """
        raise NotImplementedError('Sub-classes must implement is_mountable method')

    def is_valid(self, port):
        """
        Check if the specified port is a valid port designation for this automounter

        :param port: str representation of the port
        :return: bool, True if it is valid
        """
        raise NotImplementedError('Sub-classes must implement is_valid method')

    def is_mounted(self, port=None):
        """
        Check if the specified port is mounted
        :param port: str representation of the port or None if checking for any
        :return: bool, True if it is mounted
        """
        sample = self.get_state('sample')
        return bool(
                (port is None and bool(sample)) or
                ((port is not None) and sample and sample.get('port') == port)
        )

    def is_ready(self):
        """
        Check if the automounter is ready for an operation
        """
        return self.get_state('status') in [State.IDLE] and self.is_active() and not self.is_busy()

    def is_preparing(self):
        """
        Check if the automounter is preparing to start
        """
        return self.get_state('status') == State.PREPARING