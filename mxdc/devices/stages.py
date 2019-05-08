import time

import numpy
from gi.repository import GObject
from zope.interface import implementer

from mxdc.devices.base import BaseDevice
from mxdc.utils.log import get_module_logger
from .interfaces import IDevice

logger = get_module_logger(__name__)


class ISampleStage(IDevice):
    """A specialized stage for the goniometer sample alignment"""

    def wait():
        """Wait for stage become idle."""

    def stop():
        """Terminate all operations."""

    def move_xyz(x, y, z, wait=False):
        """Move to absolute position in world coordinages"""

    def move_screen(x, y, z, wait=False):
        """Move to absolute position in local coordinages"""

    def move_xyz_by(xd, yd, zd, wait=False):
        """Move to relative position in world coordinages"""

    def move_screen_by(xd, yd, zd, wait=False):
        """Move to relative position in local coordinages"""

    def get_local_xyz():
        """Get current positions in coordinates relative to self"""

    def get_world_xyz():
        """Get Current position in relative to laboratory frame"""

    def world_to_local(x, y, z):
        """Convert world coordinates to local coordinates"""

    def local_to_world(x, y, z):
        """Convert local coordiantes to world coordinates"""

    def is_busy():
        """Is the stage busy"""


@implementer(ISampleStage)
class SampleStageBase(BaseDevice):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def xyz_to_xvw(self, x, y, z):
        return x, numpy.hypot(y, z), numpy.arctan2(z, y)

    def xvw_to_xyz(self, x, v, w):
        return x, v * numpy.cos(w), v * numpy.sin(w)

    def xvw_to_screen(self, x, v, w):
        theta = self.get_omega() - w
        return x, v * numpy.cos(theta), v * numpy.sin(theta)

    def xyz_to_screen(self, x, y, z):
        x, v, w = self.xyz_to_xvw(x, y, z)
        return self.xvw_to_screen(x, v, w)

    def screen_to_xyz(self, x, y, z):
        phi = self.get_omega() - numpy.arctan2(z, y)
        h = numpy.hypot(z, y)
        return x, h * numpy.cos(phi), h * numpy.sin(phi)

    def get_omega(self):
        return numpy.radians(self.omega.get_position() - self.offset)

    def is_busy(self):
        raise NotImplementedError('Sub classes must implement "is_busy"')

    def wait(self, start=False, stop=True):
        """Wait for the busy state to change.

        Kwargs:
            - `start` (bool): Wait for the motor to start moving.
            - `stop` (bool): Wait for the motor to stop moving.
        """
        poll = 0.05
        timeout = 5.0

        # initialize precision
        if start and not self.is_busy():
            while self.is_busy() and timeout > 0:
                timeout -= poll
                time.sleep(poll)
            if timeout <= 0:
                logger.warning('%s timed out waiting for sample stage to start moving')
                return False
        timeout = 120
        if stop and self.is_busy():
            while self.is_busy() and timeout > 0:
                time.sleep(poll)
                timeout -= poll
            if timeout <= 0:
                logger.warning('%s timed out waiting for sample stage to stop moving')
                return False


class SampleStage(SampleStageBase):

    def __init__(self, x, y1, y2, omega, name='Sample Stage', offset=0.0, linked=False):
        SampleStageBase.__init__(self)
        self.name = name
        self.x = x
        self.y1 = y1
        self.y2 = y2
        self.offset = offset
        self.linked = linked
        self.omega = omega
        self.add_devices(x, y1, y2, omega)
        for dev in (self.x, self.y1, self.y2, self.omega):
            dev.connect('changed', self.emit_change)

    def emit_change(self, *args, **kwargs):
        pos = (self.get_omega(), self.x.get_position(), self.y1.get_position(), self.y2.get_position())
        self.set_state(changed=pos)

    def get_xvw(self):
        """x = horizontal, v = vertical, w= angle in radians"""
        y1, y2 = self.y1.get_position(), self.y2.get_position()
        return self.x.get_position(), numpy.hypot(y1, y2), numpy.arctan2(y2, y1)

    def get_xyz(self):
        return self.x.get_position(), self.y1.get_position(), self.y2.get_position()

    def move_xyz(self, xl, yl, zl, wait=False):
        self.wait(start=False)
        self.y1.move_to(yl, wait=self.linked)
        self.y2.move_to(zl, wait=self.linked)
        self.x.move_to(xl, wait=self.linked)
        self.wait(start=(not self.linked), stop=wait)

    def move_xyz_by(self, xd, yd, zd, wait=False):
        self.wait(start=False)
        self.y1.move_by(yd, wait=self.linked)
        self.y2.move_by(zd, wait=self.linked)
        self.x.move_by(xd, wait=self.linked)
        self.wait(start=(not self.linked), stop=wait)

    def move_screen(self, xw, yw, zw, wait=False):
        self.wait(start=False)
        xl, yl, zl = self.screen_to_xyz(xw, yw, zw)
        self.y1.move_to(yl, wait=self.linked)
        self.y2.move_to(zl, wait=self.linked)
        self.x.move_to(xl, wait=self.linked)
        self.wait(start=(not self.linked), stop=wait)

    def move_screen_by(self, xwd, ywd, zwd, wait=False):
        self.wait(start=False)
        xld, yld, zld = self.screen_to_xyz(xwd, ywd, zwd)
        self.y1.move_by(yld, wait=self.linked)
        self.y2.move_by(zld, wait=self.linked)
        self.x.move_by(xld, wait=self.linked)
        self.wait(start=(not self.linked), stop=wait)

    def stop(self):
        self.x.stop()
        self.y1.stop()
        self.y2.stop()

    def is_busy(self):
        return any((self.x.is_busy(), self.y1.is_busy(), self.y2.is_busy()))
