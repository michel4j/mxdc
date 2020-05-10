import time

from zope.interface import implementer

from mxdc import Device, Signal, Registry
from .interfaces import ICenter


@implementer(ICenter)
class BaseCenter(Device):
    class Signals:
        loop = Signal("loop", arg_types=(int, int, float))
        xtal = Signal("xtal", arg_types=(int, int, float))

    def __init__(self, threshold=0):
        super().__init__()
        self.loop_since = time.time()
        self.xtal_since = time.time()
        self.threshold = threshold

    def update_loop(self, x, y, score):
        """
        Update the loop position

        :param x: X position
        :param y: Y position
        :param score: score
        :return: True if signal sent
        """

        if score >= self.threshold:
            self.set_state(loop=(x, y, score))
            self.loop_since = time.time()
            return True

    def update_xtal(self, x, y, score):
        """
        Update the xtal position

        :param x: X position
        :param y: Y position
        :param score: score
        :return: True if signal sent
        """
        if score >= self.threshold:
            self.set_state(xtal=(x, y, score))
            self.xtal_since = time.time()
            return True

    def loop(self):
        """
        Get last loop coordinates with score
        """
        return self.get_state('loop')

    def xtal(self):
        """
        Get last crystal coordinates with score
        """
        return self.get_state('xtal')

    def wait_xtal(self, timeout=5):
        """
        Wait for up to a given amount time for the crystal position to be updated

        :param timeout: time to wait
        :return: True if crystal found in the given time
        """
        self.xtal_since = 0  # invalidate xtal coords first

        remaining = timeout
        while time.time() - self.xtal_since > timeout and remaining > 0:
            remaining -= 0.01
            time.sleep(0.01)

        if remaining <= 0.0:
            return False

        return True

    def wait_loop(self, timeout=5):
        """
        Wait for up to a given amount time for the loop position to be updated

        :param timeout: time to wait
        :return: True if crystal found in the given time
        """
        self.loop_since = 0  # invalidate xtal coords first

        remaining = timeout
        while time.time() - self.loop_since > timeout and remaining > 0:
            remaining -= 0.01
            time.sleep(0.01)

        if remaining <= 0.0:
            return False

        return True


class ExtCenter(BaseCenter):
    """
    An external centering device.
    """

    def __init__(self, root, threshold=0.5):
        super().__init__(threshold=threshold)
        self.name = root

        self.loop_x = self.add_pv(f'{root}:loop:x')
        self.loop_y = self.add_pv(f'{root}:loop:y')
        self.loop_score = self.add_pv(f'{root}:loop:score')

        self.xtal_x = self.add_pv(f'{root}:xtal:x')
        self.xtal_y = self.add_pv(f'{root}:xtal:y')
        self.xtal_score = self.add_pv(f'{root}:xtal:score')

        self.loop_score.connect('changed', self.on_loop)
        self.xtal_score.connect('changed', self.on_xtal)

        Registry.add_utility(ICenter, self)

    def on_loop(self, obj, value):
        self.update_loop(self.loop_x.get(), self.loop_y.get(), self.loop_score.get())

    def on_xtal(self, obj, value):
        self.update_xtal(self.xtal_x.get(), self.xtal_y.get(), self.xtal_score.get())
