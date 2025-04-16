import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal, Optional

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
    time: float = 0.0

    def __post_init__(self):
        self.time = time.time()


OBJECT_LABEL = Literal["loop", "crystal", "pin"]


@implementer(ICenter)
class BaseCenter(Device):
    class Signals:
        found = Signal("found", arg_types=(int, str))
        loop = Signal("loop", arg_types=(object,))
        crystal = Signal("crystal", arg_types=(object,))
        pin = Signal("pin", arg_types=(object,))

    def __init__(self, threshold=0):
        super().__init__()
        self.found_since = time.time()
        self.threshold = threshold

    def update_found(self, obj: CenterObject) -> bool:
        """
        Update position

        :param obj: Center object
        :return: True if signal sent
        """

        if obj.score >= self.threshold:
            self.set_state(found=(obj.time, obj.label))
            self.found_since = obj.time
            return True

    def get_object(self, label: str = 'loop') -> Optional[CenterObject]:
        """
        Get the object coordinates with score
        """
        return self.get_state(label)

    def get_objects(self, since: float = 0.0, threshold: float = None) -> dict[str, CenterObject]:
        """
        Get all objects coordinates with score updated since the provided timestamp
        :param since: time stamp to check for updates
        :param threshold: minimum score to consider, if None use the current threshold
        """
        threshold = self.threshold if threshold is None else threshold
        objects = {}
        for label in ['loop', 'crystal', 'pin']:
            obj = self.get_object(label)
            if obj and obj.time > since and obj.score >= threshold:
                objects[label] = obj

        return objects

    def fetch(self):
        """
        Get last loop coordinates with score
        """
        return self.get_state('found')

    def wait(self, timeout=2):
        """
        Wait for up to a given amount time for the object position to be updated

        :param timeout: time to wait
        :return: True if object found in the given time
        """

        expired = time.time() + timeout
        self.found_since = 0  # invalidate coords first
        while time.time() < expired:
            time.sleep(0.01)
            if self.found_since > 0:
                return self.get_objects()

        return {}


class ExtCenter(BaseCenter):
    """
    An external centering device.
    """

    class ObjectType(IntEnum):
        """
        Object type for the centering device, update this if the definition
        in the centering device changes
        """
        NONE, LOOP, CRYSTAL, PIN = range(4)

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
        self.obj_types = self.add_pv(f'{root}:objects:type')
        self.size = self.add_pv(f'{root}:objects:valid')

        self.status = self.add_pv(f'{root}:status')
        self.label = self.add_pv(f'{root}:label')
        self.score.connect('changed', self.on_pos_changed)
        self.obj_scores.connect('changed', self.on_obj_changed)
        Registry.add_utility(ICenter, self)

    def on_pos_changed(self, *args, **kwargs):
        if self.score.get() > self.threshold and self.w.get() > MIN_WIDTH:
            cx = self.x.get() + self.w.get() / 2
            cy = self.y.get() + self.h.get() / 2
            loop = CenterObject(cx, cy, self.score.get(), self.w.get(), self.h.get(), label=self.label.get())
            self.update_found(loop)
            self.set_state(loop=loop)
        else:
            self.set_state(loop=None)

    def on_obj_changed(self, *args, **kwargs):
        num_obj = self.size.get()
        if num_obj > 0:
            xs = self.obj_x.get()[:num_obj]
            ys = self.obj_y.get()[:num_obj]
            scores = self.obj_scores.get()[:num_obj]
            types = self.obj_types.get()[:num_obj]
            crystals = types == self.ObjectType.CRYSTAL
            pins = types == self.ObjectType.PIN
            objects = []
            if crystals.any():
                x = xs[crystals][0]
                y = ys[crystals][0]
                score = scores[crystals][0]
                crystal = CenterObject(x, y, score, label='xtal')
                self.set_state(crystal=crystal)
                objects.append(crystal)
            else:
                self.set_state(crystal=None)
            if pins.any():
                x = xs[pins][0]
                y = ys[pins][0]
                score = scores[pins][0]
                pin = CenterObject(x, y, score, label='pin')
                self.set_state(pin=pin)
                objects.append(pin)
            else:
                self.set_state(pin=None)

            for obj in objects:
                self.update_found(obj)
        else:
            self.set_state(crystal=None, pin=None)


class SimCenter(BaseCenter):
    """
    A simulated centering device.
    """

    def __init__(self, root, threshold=0.5):
        super().__init__(threshold=threshold)
        self.name = root

        Registry.add_utility(ICenter, self)
