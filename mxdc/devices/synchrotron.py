import time
import numpy
import random

from gi.repository import GObject
from mxdc.devices.base import BaseDevice
from mxdc.devices.interfaces import IStorageRing
from mxdc.devices.misc import logger
from zope.interface import implements


class BaseStorageRing(BaseDevice):
    implements(IStorageRing)
    __gsignals__ = {
        "ready": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
    }
    current = GObject.property(type=float, default=0.0)
    mode = GObject.property(type=int, default=0)
    state = GObject.property(type=int, default=0)
    message = GObject.property(type=str, default='')

    def __init__(self):
        super(BaseStorageRing, self).__init__()
        for param in ['current', 'mode', 'state', 'message']:
            self.connect('notify::{}'.format(param), self.check_ready)

    def check_ready(self, *args, **kwargs):
        return True

    def beam_available(self):
        return self.ready_state

    def wait_for_beam(self, timeout=60):
        while not self.read_state and timeout > 0:
            time.sleep(0.05)
            timeout -= 0.05
        logger.warn('Timed out waiting for beam!')


class StorageRing(BaseStorageRing):
    def __init__(self, current_pv, mode_pv, state_pv):
        super(StorageRing, self).__init__()
        self.name = "CLS Storage Ring"
        self.mode_pv = self.add_pv(mode_pv)
        self.current_pv = self.add_pv(current_pv)
        self.state_pv = self.add_pv('{}:shutters'.format(state_pv))
        self.messages = [
            self.add_pv('{}:msg:L{}'.format(state_pv, i+1))
            for i in range(3)
        ]

        self.mode_pv.connect('changed', self.update)
        self.current_pv.connect('changed', self.update)
        self._last_current = 0.0

    def check_ready(self, *args, **kwargs):
        if self.props.current > 5.0 and self.props.mode == 4:
            self.set_state(ready=True, health=(0, 'mode'))
        elif self.props.current > 5.0:
            self.set_state(ready=False, health=(2, 'mode', 'Maintenance'))
        else:
            self.set_state(ready=False, health=(4, 'mode', self.props.message or 'No beam!'))

    def update(self, *args, **kwargs):
        self.props.current = self.current_pv.get()
        self.props.mode = self.mode_pv.get()
        self.props.state = self.state_pv.get()
        self.props.message = ', '.join(filter(None, [msg.get().strip() for msg in self.messages]))


class SimStorageRing(BaseStorageRing):
    def __init__(self, name):
        super(SimStorageRing, self).__init__()
        self.name = name
        self.props.message = 'SR Testing!'
        self.set_state(ready=True, active=True, health=(0, ''))
        GObject.timeout_add(10000, self.update)

    def update(self, *args, **kwargs):
        if numpy.random.normal() > 0.5:
            self.props.current = numpy.random.rand() * 250
            self.props.mode = random.choice(range(5))
            self.props.state = random.choice([0, 1, 1, 1, 1])
        return True

    def check_ready(self, *args, **kwargs):
        if self.props.current > 5.0 and self.props.state == 1 and self.props.mode == 4:
            self.set_state(ready=True, health=(0, 'mode'))
        elif self.props.current > 5.0 and self.props.state == 1:
            self.set_state(ready=False, health=(1, 'mode', 'Maintenance'))
        elif self.props.current > 5.0 and self.props.state != 1:
            self.set_state(ready=False, health=(1, 'mode', 'Disabled'))
        else:
            self.set_state(ready=False, health=(4, 'mode', self.props.message or 'No beam!'))