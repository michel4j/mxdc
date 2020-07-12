import time

from zope.interface import implementer

from mxdc import Device, Signal, Registry
from .interfaces import ICenter


@implementer(ICenter)
class BaseCenter(Device):
    class Signals:
        found = Signal("found", arg_types=(int, int, float, str))

    def __init__(self, threshold=0):
        super().__init__()
        self.found_since = time.time()
        self.threshold = threshold

    def update_found(self, x, y, score, label):
        """
        Update position

        :param x: X position
        :param y: Y position
        :param score: score
        :param label: type of object found
        :return: True if signal sent
        """

        if score >= self.threshold:
            self.set_state(found=(x, y, score, label))
            self.found_since = time.time()
            return True

    def fetch(self):
        """
        Get last loop coordinates with score
        """
        return self.get_state('found')

    def wait(self, timeout=5):
        """
        Wait for up to a given amount time for the crystal position to be updated

        :param timeout: time to wait
        :return: True if crystal found in the given time
        """
        self.found_since = 0  # invalidate xtal coords first

        remaining = timeout
        while time.time() - self.found_since > timeout and remaining > 0:
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

        self.x = self.add_pv(f'{root}:x')
        self.y = self.add_pv(f'{root}:y')
        self.score = self.add_pv(f'{root}:score')
        self.w = self.add_pv(f'{root}:w')
        self.h = self.add_pv(f'{root}:h')
        self.label = self.add_pv(f'{root}:label')
        self.status = self.add_pv(f'{root}:status')
        self.score.connect('changed', self.on_score)

        Registry.add_utility(ICenter, self)

    def on_score(self, obj, value):
        if value > self.threshold:
            self.update_found(self.x.get(), self.y.get(), self.score.get(), self.label.get())
