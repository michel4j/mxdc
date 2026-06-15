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
    id: int = 0
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
        return False

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

        self.obj_pvs = {
            label: {
                attr: self.add_pv(f'{root}:{label}:{attr}')
                for attr in ['box', 'score', 'id', 'valid']
            }
            for label in ['loop', 'crystal', 'pin', 'extra']
        }
        self.status = self.add_pv(f'{root}:enable')

        # connect signals for loop, crystals and pins (ignore extra for now)
        for label in ['loop', 'crystal', 'pin']:
            pvs = self.obj_pvs[label]
            pvs['box'].connect('changed', self.on_box_changed, label)

        Registry.add_utility(ICenter, self)

    def on_box_changed(self, pv, value, label):
        valid = self.obj_pvs[label]['valid'].get()
        score = self.obj_pvs[label]['score'].get()
        obj_id = self.obj_pvs[label]['id'].get()
        box = self.obj_pvs[label]['box'].get()

        if not valid:
            self.set_state(**{label: None})
            return

        x1, y1, x2, y2 = box
        w = x2 - x1
        h = y2 - y1
        cy = y1 + h / 2
        if label == 'pin':
            cx = x1 + 0.9 * w   # center pins 90% of the way horizontally
        else:
            cx = x1 + w / 2

        obj = CenterObject(cx, cy, score, w, h, label=label, id=obj_id)
        self.update_found(obj)
        self.set_state(**{label: obj})


class SimCenter(BaseCenter):
    """
    A simulated centering device.
    """

    def __init__(self, root, threshold=0.5):
        super().__init__(threshold=threshold)
        self.name = root

        Registry.add_utility(ICenter, self)
