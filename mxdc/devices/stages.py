import time

import numpy
from zope.interface import implementer

from mxdc import Signal, Device
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
class BaseSampleStage(Device):
    """
    Base class for sample alignment stages

    Signals:
        - **changed**: (object,) stage information
    """
    class Signals:
        changed = Signal("changed", arg_types=(object,))

    def xyz_to_xvw(self, x, y, z):
        """
        Convert 3D x, y, z coordinates to horizontal, vertical and angle coordinates

        :param x: x-position
        :param y: y-position
        :param z: z-position
        :return: (x, v, w) ie (horizontal, vertical, omega angle)
        """
        return x, numpy.hypot(y, z), numpy.arctan2(z, y)

    def xvw_to_xyz(self, x, v, w):
        """
        Convert 3D horizontal, vertical, omega coordinates to  x, y, z coordinates

        :param x: horizontal position
        :param v: vertical position
        :param w: omega angle position
        :return: (x, y, z)
        """
        ang = self.invert_omega * w
        return self.invert_x * x, v * numpy.cos(ang), v * numpy.sin(ang)

    def xvw_to_screen(self, x, v, w):
        """
        Convert 3D horizontal, vertical, omega coordinates to screen coordinates

        :param x: horizontal position
        :param v: vertical position
        :param w: omega angle position
        :return: (x, y, z) screen coordinates
        """
        theta = self.get_omega() - w
        return x, v * numpy.cos(theta), v * numpy.sin(theta)

    def xyz_to_screen(self, x, y, z):
        """
        Convert 3D horizontal, x, y, z to screen coordinates

        :param x: x-position
        :param y: y-position
        :param z: z-position
        :return: (x, y, z) screen coordinates
        """
        x, v, w = self.xyz_to_xvw(x, y, z)
        return self.xvw_to_screen(self.invert_x * x, v, self.invert_omega * w)

    def screen_to_xyz(self, x, y, z):
        """
        Convert screen coordiantes to x, y, z

        :param x: x-position
        :param y: y-position
        :param z: z-position
        :return: (x, y, z) screen coordinates
        """
        phi = self.invert_omega * (self.get_omega() - numpy.arctan2(z, y))
        h = numpy.hypot(z, y)
        return self.invert_x * x, h * numpy.cos(phi), h * numpy.sin(phi)

    def get_omega(self):
        """
        Get the angle position
        """
        return numpy.radians(self.omega.get_position() - self.offset)

    def wait(self, start=True, stop=True, timeout=30):
        """
        Wait for the busy state to change.

        Kwargs:
            - `start` (bool): Wait for the motor to start moving.
            - `stop` (bool): Wait for the motor to stop moving.
        """

        # initialize precision
        success = True
        if start:
            logger.debug(f'{self.name}: Waiting to start')
            end_time = time.time() + timeout
            while time.time() < end_time:
                if self.is_busy():
                    logger.debug(f'{self.name}: moving ...')
                    break
                time.sleep(0.01)
            else:
                logger.warning(f'{self.name}: Timed-out waiting to start after {timeout} sec')
                success = False
        if stop:
            logger.debug(f'{self.name}: Waiting to stop')
            end_time = time.time() + timeout
            while time.time() < end_time:
                if not self.is_busy():
                    logger.debug(f'{self.name}: stopped moving!')
                    break
                time.sleep(0.01)
            else:
                logger.warning(f'{self.name}: Timed-out waiting to stop after {timeout} sec')
                success = False
        return success


class SampleStage(BaseSampleStage):
    """
    Sample stage based based on x, y1, y2 and omega motors. Y1 and Y2 motors are at 90 degrees.
    """

    def __init__(self, x, y1, y2, omega, name='Sample Stage', label='stage', offset=0.0, linked=False, invert_x=False, invert_omega=False):
        """
        :param x: x axis motor
        :param y1: y1 axis motor
        :param y2:  y2 axis motor (at 90 degrees from y1)
        :param omega: omega rotation motor
        :param name:  name of stage
        :param label: description of stage
        :param offset: offset angle, default 0.0
        :param linked: bool, if True, motors can't move simultaneously
        :param invert_x:  bool, invert direction of x translation relative to screen
        :param invert_omega: Invert directon of omega rotation
        """
        super().__init__()
        self.name = name
        self.set_label(label)
        self.x = x
        self.y1 = y1
        self.y2 = y2
        self.moving = False
        self.motion_mask = {0: 0, 1: 0, 2 : 0, 3 : 0}
        self.offset = offset
        self.linked = linked
        self.omega = omega
        self.invert_x = -1 if invert_x else 1
        self.invert_omega = -1 if invert_omega else 1
        self.add_components(x, y1, y2, omega)
        for i, dev in enumerate((self.x, self.y1, self.y2, self.omega)):
            dev.connect('changed', self.emit_change)
            dev.connect('busy', self.check_busy, i)

    def emit_change(self, *args, **kwargs):
        pos = (self.get_omega(), self.x.get_position(), self.y1.get_position(), self.y2.get_position())
        self.set_state(changed=(pos,))

    def check_busy(self, pv, state, index):
        self.motion_mask[index] = int(state)
        self.moving = sum(self.motion_mask.values()) > 0

    def get_xvw(self):
        """x = horizontal, v = vertical, w= angle in radians"""
        y1, y2 = self.y1.get_position(), self.y2.get_position()
        return self.x.get_position(), numpy.hypot(y1, y2), numpy.arctan2(y2, y1)

    def get_xyz(self):
        return self.x.get_position(), self.y1.get_position(), self.y2.get_position()

    def move_xyz(self, xl, yl, zl, wait=False):
        self.y1.move_to(yl, wait=self.linked)
        self.y2.move_to(zl, wait=self.linked)
        self.x.move_to(xl, wait=self.linked)
        if wait and not self.linked:
            self.wait()

    def move_xyz_by(self, xd, yd, zd, wait=False):
        self.y1.move_by(yd, wait=self.linked)
        self.y2.move_by(zd, wait=self.linked)
        self.x.move_by(xd, wait=self.linked)
        if wait and not self.linked:
            self.wait()

    def move_screen(self, xw, yw, zw, wait=False):
        xl, yl, zl = self.screen_to_xyz(xw, yw, zw)
        self.x.move_to(xl, wait=self.linked)
        self.y1.move_to(yl, wait=self.linked)
        self.y2.move_to(zl, wait=self.linked)
        if wait and not self.linked:
            self.wait()

    def move_screen_by(self, xwd, ywd, zwd, wait=False):
        xld, yld, zld = self.screen_to_xyz(xwd, ywd, zwd)
        self.y1.move_by(yld, wait=self.linked)
        self.y2.move_by(zld, wait=self.linked)
        self.x.move_by(xld, wait=self.linked)

        if wait and not self.linked:
            self.wait()

    def stop(self):
        self.x.stop()
        self.y1.stop()
        self.y2.stop()

    def is_busy(self):
        return self.moving


class XYStage(Device):
    """
    X, Y stage.

    :param x: x axis motor
    :param y: y axis motor
    """
    class Signals:
        changed = Signal("changed", arg_types=(object,))

    def __init__(self, x, y, name="XY Stage", label="stage"):
        super().__init__()
        self.name = name
        self.set_label(label)
        self.x = x
        self.y = y
        self.moving = False
        self.motion_mask = {0: 0, 1: 0}
        self.add_components(self.x, self.y)
        for i, dev in enumerate((self.x, self.y)):
            dev.connect('changed', self.emit_change)
            dev.connect('busy', self.check_busy, i)

    def emit_change(self, *args, **kwargs):
        pos = (self.x.get_position(), self.y.get_position())
        self.set_state(changed=(pos,))

    def check_busy(self, pv, state, index):
        self.motion_mask[index] = int(state)
        self.moving = sum(self.motion_mask.values()) > 0

    def is_busy(self):
        return self.moving

    def wait(self, start=True, stop=True):
        """
        Wait for the busy state to change.

        Kwargs:
            - `start` (bool): Wait for the motor to start moving.
            - `stop` (bool): Wait for the motor to stop moving.
        """
        poll = 0.001
        end_time = time.time() + 5

        # initialize precision
        if start and not self.is_busy():
            logger.debug(f'{self.name}: Waiting for stage to start moving')
            while self.is_busy() and time.time() < end_time:
                time.sleep(poll)
            if time.time() > end_time:
                logger.warning('%s timed out waiting for stage to start moving')
                return False
            logger.debug(f'{self.name}: Stage is now moving')

        if stop:
            logger.debug(f'{self.name}: Waiting for to stop moving')
            end_time = time.time() + 120
            time.sleep(poll)
            while self.is_busy() and time.time() < end_time:
                time.sleep(poll)
            if time.time() > end_time:
                logger.warning('%s timed out waiting for stage to stop moving')
                return False
        return True

    def stop(self):
        self.x.stop()
        self.y.stop()

    def move_xy(self, x, y, wait=False):
        self.wait(start=False)
        self.x.move_to(x,  wait=wait)
        self.y.move_to(y, wait=wait)

    def get_xy(self):
        return self.x.get_position(), self.y.get_position()


class XYZStage(Device):
    """
    X, Y, Z stage.

    :param x: x axis motor
    :param y: y axis motor
    :param z: z axis motor
    """
    class Signals:
        changed = Signal("changed", arg_types=(object,))

    def __init__(self, x, y, z, name="XYZ Stage", label="stage"):
        super().__init__()
        self.name = name
        self.set_label(label)
        self.x = x
        self.y = y
        self.z = z
        self.moving = False
        self.motion_mask = {0: 0, 1: 0, 2: 0}
        self.add_components(self.x, self.y, self.z)
        for i, dev in enumerate((self.x, self.y, self.z)):
            dev.connect('changed', self.emit_change)
            dev.connect('busy', self.check_busy, i)

    def emit_change(self, *args, **kwargs):
        pos = (self.x.get_position(), self.y.get_position(), self.z.get_position())
        self.set_state(changed=(pos,))

    def check_busy(self, pv, state, index):
        self.motion_mask[index] = int(state)
        self.moving = sum(self.motion_mask.values()) > 0

    def is_busy(self):
        return self.moving

    def wait(self, start=True, stop=True):
        """
        Wait for the busy state to change.

        Kwargs:
            - `start` (bool): Wait for the motor to start moving.
            - `stop` (bool): Wait for the motor to stop moving.
        """
        poll = 0.001
        end_time = time.time() + 5

        # initialize precision
        if start and not self.is_busy():
            logger.debug(f'{self.name}: Waiting for stage to start moving')
            while self.is_busy() and time.time() < end_time:
                time.sleep(poll)
            if time.time() > end_time:
                logger.warning('%s timed out waiting for stage to start moving')
                return False
            logger.debug(f'{self.name}: Stage is now moving')

        if stop:
            logger.debug(f'{self.name}: Waiting for to stop moving')
            end_time = time.time() + 120
            time.sleep(poll)
            while self.is_busy() and time.time() < end_time:
                time.sleep(poll)
            if time.time() > end_time:
                logger.warning('%s timed out waiting for stage to stop moving')
                return False
        return True

    def stop(self):
        self.x.stop()
        self.y.stop()
        self.z.stop()

    def move_xyz(self, x, y, z, wait=False):
        self.x.move_to(x,  wait=wait)
        self.y.move_to(y, wait=wait)
        self.z.move_to(z, wait=wait)

    def get_xyz(self):
        return self.x.get_position(), self.y.get_position(), self.z.get_position()