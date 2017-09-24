import numpy
from gi.repository import GObject
from zope.interface import implements

from interfaces import IDevice
from mxdc.devices.base import BaseDevice


class ISampleStage(IDevice):
    """A specialized stage for the goniometer sample alignment"""

    def wait():
        """Wait for stage become idle."""

    def stop():
        """Terminate all operations."""

    def move_world(x, y, z):
        """Move to absolute position in world coordinages"""

    def move_local(x, y, z):
        """Move to absolute position in local coordinages"""

    def move_world_by(xd, yd, zd):
        """Move to relative position in world coordinages"""

    def move_local_by(xd, yd, zd):
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


class SampleStageBase(BaseDevice):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def xyz_to_xvw(self, x, y, z):
        return x, numpy.hypot(y, z), numpy.arctan2(z, y)

    def xvw_to_xyz(self, x, v, w):
        return x, v * numpy.cos(w), v* numpy.sin(w)

    def xvw_to_screen(self, x, v, w):
        theta = self.get_omega() - w
        return x, v*numpy.cos(theta), v*numpy.sin(theta)

    def xyz_to_screen(self, x, y, z):
        x, v, w = self.xyz_to_xvw(x, y, z)
        return self.xvw_to_screen(x, v, w)

    def screen_to_xyz(self, x, y, z):
        phi = self.get_omega() - numpy.arctan2(z, y)
        h = numpy.hypot(z, y)
        return x, h*numpy.cos(phi), h*numpy.sin(phi)

    def get_omega(self):
        return numpy.radians(self.omega.get_position() - self.offset)


class Sample3Stage(SampleStageBase):
    implements(ISampleStage)

    def __init__(self, x, y1, y2, omega, name='Sample Stage', offset=0.0, independent=False):
        SampleStageBase.__init__(self)
        self.name = name
        self.x = x
        self.y1 = y1
        self.y2 = y2
        self.offset = offset
        self.independent = independent
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

    def move_xyz(self, xl, yl, zl):
        self.x.move_to(xl, wait=True)
        self.y1.move_to(yl, wait=True)
        self.y2.move_to(zl, wait=True)

    def move_xyz_by(self, xd, yd, zd):
        self.x.move_by(xd, wait=True)
        self.y1.move_by(yd, wait=True)
        self.y2.move_by(zd, wait=True)

    def move_screen(self, xw, yw, zw):
        xl, yl, zl = self.screen_to_xyz(xw, yw, zw)
        self.x.move_to(xl, wait=True)
        self.y1.move_to(yl, wait=True)
        self.y2.move_to(zl, wait=True)

    def move_screen_by(self, xwd, ywd, zwd):
        xld, yld, zld = self.screen_to_xyz(xwd, ywd, zwd)
        self.x.move_by(xld, wait=True)
        self.y1.move_by(yld, wait=True)
        self.y2.move_by(zld, wait=True)

    def wait(self):
        self.x.wait()
        self.y1.wait()
        self.y2.wait()

    def stop(self):
        self.x.stop()
        self.y1.stop()
        self.y2.stop()

    def is_busy(self):
        return any((self.x.is_busy(), self.y1.is_busy(), self.y2.is_busy()))


class Sample2Stage(SampleStageBase):
    implements(ISampleStage)

    def __init__(self, x, y, omega, name='Sample Stage', independent=False):
        super(Sample2Stage, self).__init__()
        self.name = name
        self.x = x
        self.y = y
        self.independent = independent
        self.omega = omega
        self.add_devices(x, y, omega)

    def get_local_xyz(self):
        return self.xvw_to_xyz(*self.get_world_xyz())

    def get_world_xyz(self):
        return self.x.get_position(), self.y.get_position(), 0.0

    def move_local(self, xl, yl, zl):
        xw, yw, zw = self.xyz_to_xvw(xl, yl, zl)
        self.x.move_to(xw, wait=True)
        self.y.move_to(yw, wait=True)

    def move_local_by(self, xld, yld, zld):
        xwd, ywd, zwd = self.xyz_to_xvw(xld, yld, zld)
        self.x.move_by(xwd, wait=True)
        self.y.move_by(ywd, wait=True)

    def move_world(self, xw, yw, zw):
        self.x.move_to(xw, wait=True)
        self.y.move_to(yw, wait=True)

    def move_world_by(self, xwd, ywd, zwd):
        self.x.move_by(xwd, wait=True)
        self.y.move_by(ywd, wait=True)

    def wait(self):
        self.x.wait()
        self.y.wait()

    def stop(self):
        self.x.stop()
        self.y.stop()

    def is_busy(self):
        return any((self.x.is_busy(), self.y.is_busy()))


