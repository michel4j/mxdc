import random
import time

import numpy
import gi
gi.require_version('GLib', '2.0')

from gi.repository import GLib
from zope.interface import implementer
from mxdc import Signal, Device, Property
from mxdc.devices.interfaces import IStorageRing
from mxdc.devices.misc import logger


@implementer(IStorageRing)
class BaseStorageRing(Device):
    """
    Base class for storage ring devices

    Signals:
        - **ready**: arg_types=(bool,), beam available state

    Properties:
        - **current**: float, stored current
        - **mode**:  int, operational mode
        - **state**: int, storage ring state
        - **message**: str, storage ring message
    """

    class Signals:
        ready = Signal("ready", arg_types=(bool,))

    # Properties
    current = Property(type=float, default=0.0)
    mode = Property(type=int, default=0)
    state = Property(type=int, default=0)
    message = Property(type=str, default='')
    uri = Property(type=str, default='')

    def __init__(self):
        super().__init__()

    def get_uri(self):
        return self.uri

    def check_ready(self, *args, **kwargs):
        return True

    def beam_available(self):
        """
        Check beam availability
        """
        return self.get_state('ready')

    def wait_for_beam(self, timeout=60):
        """
        Wait for beam to become available

        :param timeout: timeout period
        """
        while not self.get_state('ready') and timeout > 0:
            time.sleep(0.05)
            timeout -= 0.05
        logger.warn('Timed out waiting for beam!')


class StorageRing(BaseStorageRing):
    """
    EPICS Storage Ring Device
    """

    def __init__(self, current_pv, mode_pv, state_pv, uri: str = ''):
        """

        :param current_pv:
        :param mode_pv: mode PV name
        :param state_pv: state PV name
        :param uri: Web address of machine status
        """
        super().__init__()
        self.name = "CLS Storage Ring"
        self.mode_pv = self.add_pv(mode_pv)
        self.current_pv = self.add_pv(current_pv)
        self.state_pv = self.add_pv('{}:shutters'.format(state_pv))
        self.props.uri = uri
        self.messages = [
            self.add_pv('{}:msg:L{}'.format(state_pv, i + 1))
            for i in range(3)
        ]

        self.mode_pv.connect('changed', self.update)
        self.current_pv.connect('changed', self.update)
        self._last_current = 0.0

    def check_ready(self, *args, **kwargs):
        if self.props.current > 5.0 and self.props.mode == 4:
            self.set_state(ready=True, health=(0, 'mode', ''))
        elif self.props.mode == 3:
            self.set_state(ready=False, health=(2, 'mode', 'Re-Fill'))
        else:
            self.set_state(ready=False, health=(4, 'mode', 'Beam Unavailable'))

    def update(self, *args, **kwargs):
        mode = self.mode_pv.get()
        current = self.current_pv.get()
        state = self.state_pv.get()
        if None not in (mode, current, state):
            self.props.current = self.current_pv.get()
            self.props.mode = self.mode_pv.get()
            self.props.state = self.state_pv.get()
            self.props.message = ', '.join([_f for _f in [msg.get().strip() for msg in self.messages] if _f])
            self.check_ready()


class SimStorageRing(BaseStorageRing):
    """
    Simulated Storage Ring.
    """

    def __init__(self, name, uri=''):
        super().__init__()
        self.name = name
        self.props.message = 'SR Testing!'
        self.props.uri = uri
        self.props.current = 250.0
        self.set_state(ready=True, active=True, health=(0, '', ''))
        GLib.timeout_add_seconds(5, self.update)

    def update(self, *args, **kwargs):
        self.props.mode = numpy.random.choice([0, 1, 2, 3, 4], replace=False, p=[0.01, 0.02, 0.01, 0.01, 0.95])
        self.props.state = numpy.random.choice([0, 1], replace=False, p=[0.05, 0.95])
        if self.props.state == 0:
            self.props.current = 0.0
            self.set_state(ready=False, health=(1, 'mode', 'No beam!'))
        else:
            self.set_state(ready=True, health=(0, 'mode', ''))
            if self.props.current < 240.0:
                self.props.current = 250.0
            else:
                self.props.current = self.props.current - numpy.random.rand()
        return True

    def check_ready(self, *args, **kwargs):
        if self.props.current > 5.0 and self.props.state == 1 and self.props.mode == 4:
            self.set_state(ready=True, health=(0, 'mode', ''))
        elif self.props.current > 5.0 and self.props.state == 1:
            self.set_state(ready=False, health=(1, 'mode', 'Re-Fill'))
        elif self.props.current > 5.0 and self.props.state != 1:
            self.set_state(ready=False, health=(1, 'mode', 'Disabled'))
        else:
            self.set_state(ready=False, health=(4, 'mode', (self.props.message or 'No beam!')))
