import time

from zope.interface import implementer

from mxdc import Device, Signal
from mxdc.devices.interfaces import IShutter
from mxdc.devices.misc import logger
from mxdc.utils import misc
from mxdc.utils.decorators import async_call


@implementer(IShutter)
class ShutterBase(Device):
    class Signals:
        changed = Signal("changed", arg_types=(bool,))


class BasicShutter(ShutterBase):
    def __init__(self, open_name, close_name, state_name):
        super().__init__()
        # initialize variables
        self._open_cmd = self.add_pv(open_name)
        self._close_cmd = self.add_pv(close_name)
        self._state = self.add_pv(state_name)
        self._state.connect('changed', self._signal_change)
        self._messages = ['Opening', 'Closing']
        self.name = open_name.split(':')[0]

    def is_open(self):
        """Convenience function for open state"""
        return self.get_state('changed')

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

    def wait(self, state=True, timeout=5.0):
        logger.debug('Waiting for {} to {}.'.format(self.name, {True: 'open', False: 'close'}[state]))
        while self.get_state('changed') != state and timeout > 0:
            time.sleep(0.1)
            timeout -= 0.1
        if timeout <= 0:
            logger.warning('Timed-out waiting for %s.' % (self.name))

    def _signal_change(self, obj, value):
        if value == 1:
            self.set_state(changed=True)
        else:
            self.set_state(changed=False)


class StateLessShutter(ShutterBase):

    def __init__(self, open_name, close_name):
        super().__init__()
        # initialize variables
        self._open_cmd = self.add_pv(open_name)
        self._close_cmd = self.add_pv(close_name)
        self._messages = ['Opening', 'Closing']
        self.name = open_name.split(':')[0]

    def open(self, wait=False):
        logger.debug(' '.join([self._messages[0], self.name]))
        self._open_cmd.toggle(1, 0)

    def close(self, wait=False):
        logger.debug(' '.join([self._messages[1], self.name]))
        self._close_cmd.toggle(1, 0)

    def wait(self, state=True, timeout=5.0):
        logger.debug('Stateless Shutter wont wait (%s).' % (self.name))



class ToggleShutter(ShutterBase):

    def __init__(self, name, reversed=False):
        super().__init__()
        self.cmd = self.add_pv(name)
        self.reversed = reversed
        self.cmd.connect('changed', self._signal_change)
        self._messages = ['Opening', 'Closing']
        self.name = name

    def is_open(self):
        """Convenience function for open state"""
        return self.changed_state

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

    def wait(self, state=True, timeout=5.0):
        logger.debug('Waiting for {} to {}.'.format(self.name, {True: 'open', False: 'close'}[state]))
        while self.get_state('changed') != state and timeout > 0:
            time.sleep(0.1)
            timeout -= 0.1
        if timeout <= 0:
            logger.warning('Timed-out waiting for %s.' % (self.name))

    def _signal_change(self, obj, value):
        if value == 1:
            self.set_state(changed=(not self.reversed))
        else:
            self.set_state(changed=self.reversed)


class ShutterGroup(ShutterBase):

    def __init__(self, *args, **kwargs):
        super().__init__()
        self._dev_list = list(args)
        self.add_devices(*self._dev_list)
        self.name = 'Beamline Shutters'
        for dev in self._dev_list:
            dev.connect('changed', self.handle_change)

    def is_open(self):
        """Convenience function for open state"""
        return self.get_state('changed')

    def handle_change(self, obj, val):
        if val:
            if misc.every([dev.get_state('changed') for dev in self._dev_list]):
                self.set_state(changed=True, health=(0, 'state', ''))
        else:
            self.set_state(changed=False, health=(2, 'state','Not Open!'))

    @async_call
    def open(self, wait=False):
        for dev in self._dev_list:
            dev.open(wait=True)

    @async_call
    def close(self, wait=False):
        newlist = self._dev_list[:]
        newlist.reverse()
        for i, dev in enumerate(newlist):
            dev.close(wait=True)

    def wait(self, state=True, timeout=5.0):
        logger.debug('Waiting for {} to {}.'.format(self.name, {True: 'open', False: 'close'}[state]))
        while self.get_state('changed') != state and timeout > 0:
            time.sleep(0.1)
            timeout -= 0.1
        if timeout <= 0:
            logger.warning('Timed-out waiting for %s.' % (self.name))


class SimShutter(ShutterBase):

    def __init__(self, name):
        super().__init__()
        self.name = name
        self._state = False
        self.set_state(active=True, changed=self._state)

    def is_open(self):
        """Convenience function for open state"""
        return self.get_state('changed')

    def open(self, wait=False):
        self._state = True
        self.set_state(changed=True)

    def close(self, wait=False):
        self._state = False
        self.set_state(changed=False)

    def wait(self, state=True, timeout=5.0):
        pass


class Shutter(BasicShutter):
    def __init__(self, name):
        open_name = "{}:opr:open".format(name)
        close_name = "{}:opr:close".format(name)
        state_name = "{}:state".format(name)
        super().__init__(open_name, close_name, state_name)