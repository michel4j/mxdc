import time
from dataclasses import dataclass
from zope.interface import implementer

from mxdc import Device, Signal, Registry
from .interfaces import ICenter

MIN_WIDTH = 20


@dataclass
class CenterObject:
    x: int = 0
    y: int = 0
    score: float = 0.0
    w: int = 0
    h: int = 0
    label: str = 'none'


@implementer(ICenter)
class BaseCenter(Device):
    class Signals:
        found = Signal("found", arg_types=(int, int, float, str))
        loop = Signal("loop", arg_types=(object, float))
        crystals = Signal("crystal", arg_types=(object, float))

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

    def wait(self, timeout=2):
        """
        Wait for up to a given amount time for the crystal position to be updated

        :param timeout: time to wait
        :return: True if crystal found in the given time
        """

        expired = time.time() + timeout
        self.found_since = 0  # invalidate coords first
        while time.time() < expired:
            if self.found_since > 0:
                return self.get_state('found')
            time.sleep(0.001)
        return None


class ExtCenter(BaseCenter):
    """
    An external centering device.
    """

    def __init__(self, root, threshold=0.25):
        super().__init__(threshold=threshold)
        self.name = root

        self.x = self.add_pv(f'{root}:x')
        self.y = self.add_pv(f'{root}:y')
        self.score = self.add_pv(f'{root}:score')
        self.w = self.add_pv(f'{root}:w')
        self.h = self.add_pv(f'{root}:h')
        self.obj_x = self.add_pv(f'{root}:objects:x')
        self.obj_y = self.add_pv(f'{root}:objects:y')
        self.obj_scores = self.add_pv(f'{root}:objects:score')
        self.size = self.add_pv(f'{root}:objects:valid')

        self.status = self.add_pv(f'{root}:status')
        self.label = self.add_pv(f'{root}:label')
        self.score.connect('changed', self.on_pos_changed)
        self.size.connect('changed', self.on_obj_changed)
        Registry.add_utility(ICenter, self)

    def get_object(self, label='loop'):
        """
        Get the object coordinates with score
        """
        loop, timestamp = self.get_state(label)
        loop = CenterObject() if loop is None else loop
        return loop

    def on_pos_changed(self, *args, **kwargs):
        if self.score.get() > self.threshold and self.w.get() > MIN_WIDTH:
            cx = self.x.get() + self.w.get() / 2
            cy = self.y.get() + self.h.get() / 2

            self.update_found(cx, cy, self.score.get(), self.label.get())
            loop = CenterObject(cx, cy, self.score.get(), self.w.get(), self.h.get(), label=self.label.get())
            self.set_state(loop=(loop, time.time()))
        else:
            self.set_state(loop=(None, time.time()))

    def on_obj_changed(self, *args, **kwargs):
        if self.size.get() > 0:
            x = self.obj_x.get()[0]
            y = self.obj_y.get()[0]
            score = self.obj_scores.get()[0]
            crystal = CenterObject(x, y, score, label='xtal')
            self.set_state(crystal=(crystal, time.time()))
        else:
            self.set_state(crystal=(None, time.time()))


class SimCenter(BaseCenter):
    """
    A simulated centering device.
    """

    def __init__(self, root, threshold=0.5):
        super().__init__(threshold=threshold)
        self.name = root

        Registry.add_utility(ICenter, self)
