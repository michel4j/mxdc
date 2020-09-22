import time

from zope.interface import implementer

from mxdc import Device, Signal
from mxdc.devices.interfaces import IShutter
from mxdc.devices.misc import logger
from mxdc.utils import misc
from mxdc.utils.decorators import async_call


@implementer(IShutter)
class BaseShutter(Device):
    """
    Base class for all shutters.

    Signals:
        - **changed**: (bool,) State of shutter
    """

    class Signals:
        changed = Signal("changed", arg_types=(bool,))

    def is_open(self):
        """
        Convenience function to check for opened state
        """
        return self.get_state("changed")

    def open(self, wait=False):
        """
        Open the shutter if closed

        :param wait: bool, if True, block until shutter is fully open
        """

    def close(self, wait=False):
        """
        Close the shutter if open

        :param wait: bool, if True, block until shutter is fully closed
        """

    def wait(self, state=True, timeout=5.0):
        """
        Wait for the shutter to reach a given state. Subclasses need not re-implement this method.

        :param state: bool, True = 'open', False = 'close'
        :param timeout: timeout duration
        """
        duration = 0
        action = {True: 'open', False: 'close'}[state]
        logger.debug(f'Waiting for {self.name} to {action}.')
        while self.get_state('changed') != state and duration < timeout:
            time.sleep(0.1)
            duration += 0.1
        if duration >= timeout:
            logger.warning(f'Timed-out waiting for {self.name} to {action}.')
            return False
        else:
            action = {True: 'opened', False: 'closed'}[state]
            logger.debug(f'{self.name} {action} after {duration:0.1f} sec.')
            return True


class EPICSShutter(BaseShutter):
    """
    EPICS Shutter requiring three PVs (close, open, state).

    :param open_name: PV name for open command
    :param close_name: PV name for close command
    :param state_name: PV name for shutter state
    :param name:  Descriptive name of shutter
    """

    def __init__(self, open_name, close_name, state_name, name='Shutter'):
        super().__init__()
        # initialize variables
        self._open_cmd = self.add_pv(open_name)
        self._close_cmd = self.add_pv(close_name)
        self._state = self.add_pv(state_name)
        self._state.connect('changed', self._signal_change)
        self._messages = ['Opening', 'Closing']
        self.name = name

    def open(self, wait=False):
        if self.get_state('changed'):
            return
        logger.debug(' '.join([self._messages[0], self.name]))
        self._open_cmd.put(1, wait=True)
        self._open_cmd.put(0)
        if wait:
            self.wait(state=True)

    def close(self, wait=False):
        if not self.get_state('changed'):
            return
        logger.debug(' '.join([self._messages[1], self.name]))
        self._close_cmd.put(1, wait=True)
        self._close_cmd.put(0)
        if wait:
            self.wait(state=False)

    def _signal_change(self, obj, value):
        if value == 1:
            self.set_state(changed=True)
        else:
            self.set_state(changed=False)


class StateLessShutter(BaseShutter):
    """
    EPICS shutter which has not state
    """

    def __init__(self, open_name, close_name):
        super().__init__()
        # initialize variables
        self._open_cmd = self.add_pv(open_name)
        self._close_cmd = self.add_pv(close_name)
        self._messages = ['Opening', 'Closing']
        self.name = open_name.split(':')[0]

    def open(self, wait=False):
        logger.debug(' '.join([self._messages[0], self.name]))
        self._open_cmd.put(1)
        self.set_state(changed=True)

    def close(self, wait=False):
        logger.debug(' '.join([self._messages[1], self.name]))
        self._close_cmd.put(1)
        self.set_state(changed=False)

    def wait(self, state=True, timeout=5.0):
        logger.debug('Stateless Shutter wont wait (%s).' % (self.name))


class ToggleShutter(BaseShutter):
    """
    A Toggle shutter controlled by a single process variable

    :param name: PV name
    """

    def __init__(self, name, reversed=False):
        super().__init__()
        self.cmd = self.add_pv(name)
        self.reversed = reversed
        self.cmd.connect('changed', self._signal_change)
        self._messages = ['Opening', 'Closing']
        self.name = name

    def open(self, wait=False):
        logger.debug(' '.join([self._messages[0], self.name]))
        self.cmd.put(1 if not self.reversed else 0)
        if wait:
            self.wait(state=True)

    def close(self, wait=False):
        logger.debug(' '.join([self._messages[1], self.name]))
        self.cmd.put(0 if not self.reversed else 1)
        if wait:
            self.wait(state=False)

    def _signal_change(self, obj, value):
        if value == 1:
            self.set_state(changed=(not self.reversed))
        else:
            self.set_state(changed=self.reversed)


class ShutterGroup(BaseShutter):
    """
    Meta Shutter controlling a sequence of shutters

    :param shutters: one or more shutters
    """

    def __init__(self, *shutters, close_last=False):
        super().__init__()
        self.close_last = close_last
        self._dev_list = list(shutters)
        self.add_components(*self._dev_list)
        self.name = 'Beamline Shutters'
        for dev in self._dev_list:
            dev.connect('changed', self.handle_change)

    def handle_change(self, obj, val):
        if val:
            if misc.every([dev.get_state('changed') for dev in self._dev_list]):
                self.set_state(changed=True, health=(0, 'state', ''))
        else:
            not_open = ','.join([dev.name for dev in self._dev_list if not dev.is_open()])
            self.set_state(changed=False, health=(2, 'state', f'{not_open} not open!'))

    @async_call
    def open(self, wait=False):
        for dev in self._dev_list:
            dev.open(wait=True)

    @async_call
    def close(self, wait=False):
        if not self.close_last:
            for dev in reversed(self._dev_list):
                dev.close(wait=True)
        else:
            self._dev_list[-1].close(wait=True)


class SimShutter(BaseShutter):
    """
    Simulated Shutter
    """

    def __init__(self, name):
        super().__init__()
        self.name = name
        self._state = False
        self.set_state(active=True, changed=self._state)

    def open(self, wait=False):
        self._state = True
        self.set_state(changed=True)

    def close(self, wait=False):
        self._state = False
        self.set_state(changed=False)


class Shutter(EPICSShutter):
    """
    CLS EPICS Shutter
    """

    def __init__(self, root, name='Shutter'):
        open_name = "{}:opr:open".format(root)
        close_name = "{}:opr:close".format(root)
        state_name = "{}:state".format(root)
        super().__init__(open_name, close_name, state_name, name=name)


class InvertedShutter(EPICSShutter):
    """
    CLS EPICS Shutter
    """

    def __init__(self, root, name='Shutter'):
        open_name = "{}:opr:close".format(root)
        close_name = "{}:opr:open".format(root)
        state_name = "{}:state".format(root)
        super().__init__(open_name, close_name, state_name, name=name)