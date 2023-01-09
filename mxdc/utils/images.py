import json
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Tuple, List, Union

import cv2
import matplotlib

import numpy
import threading
import time
from collections import deque
from enum import Enum
from pathlib import Path

import zmq
from methodtools import lru_cache
from mxio import read_image, DataSet, XYPair
from mxio.formats import eiger

from mxdc import Engine
from mxdc.utils import log, misc

logger = log.get_module_logger('frames')

SCALE_MULTIPLIER = 3.0
MAX_SCALE = 12.0
MIN_SCALE = 0.0
RESOLUTION_STEP_SIZE = 30  # Radial step size between resolution rings in mm
LABEL_GAP = 0.0075  # Annotation label gap
COLOR_MAPS = ('binary', 'inferno')
MAX_SAVE_JITTER = 0.5  # maximum amount of time in seconds to wait for file to be done writing to disk
MAX_FILE_FREQUENCY = 5


class DataMonitor(Engine):
    """
    A detector helper engine which loads frames and emits them to watchers as they are being acquired.

    :param master: Master object to which new data should be added. Must implement the
        process_frame(data) method takes a single parameter which is a imageio.DataSet object
    """

    def __init__(self, master):
        super().__init__()
        self.master = master

    def set_master(self, master):
        """
        Change the master device to which datasets should be sent

        :param master: Master, must implement a `process_frame` function that accepts a single parameter which is
            an instance of a imageio.DataSet object.
        """
        self.master = master


class FileMonitor(DataMonitor):
    """
    Data Monitor which reads frames from disk
    """

    MAX_SAVE_JITTER = 0.5  # maximum amount of time in seconds to wait for file to be done writing to disk

    def __init__(self, master):
        super().__init__(master)
        self.inbox = deque(maxlen=10)
        self.start()

    def add(self, path):
        self.inbox.append(path)

    def load(self, path):
        self.set_state(busy=True)
        attempts = 0
        success = False
        path = Path(path)

        while not success and attempts < 10:
            # ping disk location
            if path.exists():
                try:
                    dataset = read_image(str(path))
                    if self.master:
                        self.master.process_frame(dataset)
                    success = True
                except Exception as e:
                    success = False
            attempts += 1
            time.sleep(1 / MAX_FILE_FREQUENCY)
        self.set_state(busy=False)
        return success

    def run(self):
        path = None
        while not self.stopped:
            # Load frame if path exists
            if len(self.inbox):
                path = self.inbox.popleft()

            if path and not self.is_busy():
                success = self.load(path)
                if success:
                    path = None
            time.sleep(1 / MAX_FILE_FREQUENCY)


class StreamTypes(Enum):
    PUSH = 1
    PUBLISH = 2


class StreamMonitor(DataMonitor):
    """
    A data monitor which monitors a zeromq stream for new data
    """

    def __init__(self, master, address: str, kind: StreamTypes =StreamTypes.PUSH, max_freq: int = 10):
        super().__init__(master)
        self.context = None
        self.receiver = None
        self.dataset = None
        self.kind = kind
        self.address = address
        self.last_time = time.time()
        self.inbox = deque(maxlen=100)
        self.max_freq = max_freq
        self.start()

    def start(self):
        super().start()
        parser_thread = threading.Thread(target=self.run_parser, daemon=True, name=self.__class__.__name__ + ":Parser")
        parser_thread.start()

    def run_parser(self):
        count = 0
        show_every = 1
        while not self.is_stopped():
            if len(self.inbox) and not self.is_paused() and self.master:
                msg = self.inbox.popleft()
                msg_type = json.loads(msg[0])
                try:
                    if msg_type['htype'] == 'dheader-1.0':
                        self.dataset = eiger.EigerStream()
                        self.dataset.parse_header(msg)
                        count = 0

                    elif msg_type['htype'] == 'dimage-1.0' and self.dataset is not None:
                        count += 1
                        if count % show_every == 0 or count == self.dataset.size:
                            self.dataset.parse_image(msg)
                            show_every = int(math.ceil(1 / self.dataset.frame.exposure / self.max_freq))
                            count = self.dataset.index
                            self.master.process_frame(self.dataset)

                        fraction = count / self.dataset.size
                        self.set_state(progress=(fraction, 'frames collected'))
                except Exception as e:
                    logger.exception(f'Error parsing stream: {e}')
            time.sleep(0.001)

    def run(self):
        self.context = zmq.Context()
        socket_type = zmq.SUB if self.kind == StreamTypes.PUBLISH else zmq.PULL
        with self.context.socket(socket_type) as receiver:
            receiver.connect(self.address)
            if self.kind == StreamTypes.PUBLISH:
                receiver.setsockopt_string(zmq.SUBSCRIBE, "")
            while not self.stopped:
                messages = receiver.recv_multipart()
                self.inbox.append(messages)
                time.sleep(0.0)


def bressenham_line(x1, y1, x2, y2):
    steep = 0
    coords = []
    dx = abs(x2 - x1)
    sx = numpy.sign(x2 - x1)

    dy = abs(y2 - y1)
    sy = numpy.sign(y2 - y1)

    if dy > dx:
        steep = 1
        x1, y1, dx, dy, sx, sy = y1, x1, dy, dx, sy, sx

    d = (2 * dy) - dx
    for i in range(0, dx):
        if steep:
            coords.append((y1, x1))
        else:
            coords.append((x1, y1))

        while d >= 0:
            y1 = y1 + sy
            d = d - (2 * dx)

        x1 = x1 + sx
        d = d + (2 * dy)
    coords.append((x2, y2))
    return coords


def bounding_box(x0, y0, x1, y1):
    x = int(min(x0, x1))
    y = int(min(y0, y1))
    w = int(abs(x0 - x1))
    h = int(abs(y0 - y1))
    return x, y, w, h


@dataclass
class Box:
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    def get_start(self):
        return self.x, self.y

    def get_end(self):
        return self.x + self.width, self.y + self.height

    def set_end(self, x, y):
        self.width = x - self.x
        self.height = y - self.y

    def set_start(self, x, y):
        self.x = x
        self.y = y

    def normalize(self):
        self.x = int(min(self.x, self.x + self.width))
        self.width = int(abs(self.width))
        self.y = int(min(self.y, self.y + self.height))
        self.height = int(abs(self.height))


@dataclass
class Spots:
    data: Any = None
    selected: Any = None

    def select(self, frame_number, span=5):
        if self.data is not None:
            sel = (self.data[:, 2] >= frame_number - span // 2)
            sel &= (self.data[:, 2] <= frame_number + span // 2)
            self.selected = self.data[sel]
        else:
            self.selected = None


@dataclass
class ScaleSettings:
    maximum: float
    average: float
    sigma: float
    multiplier: float = SCALE_MULTIPLIER
    default: float = field(init=False)
    scale: float = field(init=False)

    def __post_init__(self):
        if self.sigma > 0.0:
            self.default = SCALE_MULTIPLIER * (self.maximum - self.average) / self.sigma
            self.multiplier = self.default
        else:
            self.default = SCALE_MULTIPLIER
        self.scale = self.average + self.multiplier * self.sigma

    def adjust(self, direction: Union[int, None] = None):
        if direction is None:
            self.multiplier = self.default
        else:
            step = direction * max(round(self.multiplier / 10, 2), 0.1)
            self.multiplier = min(MAX_SCALE, max(MIN_SCALE, self.multiplier + step))
        self.scale = self.average + self.multiplier * self.sigma


class InvalidFrameData(Exception):
    ...


@dataclass
class DisplayFrame:
    dataset: DataSet
    color_scheme: Union[str, None] = 'binary'
    settings: Union[ScaleSettings, None] = field(repr=False, default=None)
    color_map: Any = field(init=False, repr=False)
    data: numpy.ndarray = field(init=False, repr=False)
    stats_data: numpy.ndarray = field(init=False, repr=False)
    image: Any = field(init=False, repr=False)
    redraw: bool = False
    dirty: bool = True

    name: str = field(init=False)
    size: XYPair = field(init=False)
    pixel_size: float = field(init=False)
    center: XYPair = field(init=False)
    index: int = field(init=False)
    delta_angle: float = field(init=False)
    distance: float = field(init=False)
    wavelength: float = field(init=False)
    saturated_value: float = field(init=False)
    resolution_shells: List[float] = field(init=False, repr=False)

    def __post_init__(self):
        self.set_colormap(self.color_scheme)
        frame = self.dataset.frame
        self.data = frame.data
        self.stats_data = frame.data
        self.size = frame.size
        self.index = self.dataset.index
        self.name = f'{self.dataset.name} [ {self.index} ]'
        self.center = frame.center
        self.delta_angle = frame.delta_angle
        self.pixel_size = frame.pixel_size.x
        self.distance = frame.distance
        self.wavelength = frame.wavelength
        self.saturated_value = frame.cutoff_value

        if self.data is None:
            raise InvalidFrameData("Data appears invalid!")

        if self.settings is None:
            maximum = numpy.percentile(frame.data, 95)
            self.settings = ScaleSettings(
                maximum=maximum, average=frame.average, sigma=frame.sigma
            )
        self.setup()
        radii = numpy.arange(0, int(1.4142 * self.size.x / 2), RESOLUTION_STEP_SIZE / self.pixel_size)[1:]
        self.resolution_shells = self.radius_to_resolution(radii)

    def setup(self, settings: Union[ScaleSettings, None] = None):
        if self.dirty:
            if settings is not None:
                self.settings = settings
            data = self.data.astype(numpy.int32) if str(self.data.dtype) == 'uint32' else self.data
            img0 = cv2.convertScaleAbs(data, None, 256 / self.settings.scale, 0)
            img1 = cv2.applyColorMap(img0, self.color_map)
            self.image = cv2.cvtColor(img1, cv2.COLOR_BGR2BGRA)

            self.dirty = False
            self.redraw = True

    @lru_cache()
    def get_resolution_rings(self, view_x, view_y, view_width, view_height, scale):
        x, y, w, h = view_x, view_y, view_width, view_height
        cx = int((self.center.x - x) * scale)
        cy = int((self.center.y - y) * scale)

        # calculate optimal angle for labels
        corners = numpy.array([(x, y), (x, y+w), (x+w, y), (x+w, y+w)]) - (self.center.x, self.center.y)
        best = numpy.argmax(numpy.linalg.norm(corners, axis=1))
        label_angle = numpy.arctan2(corners[best, 1], corners[best, 0])

        ux = scale * math.cos(label_angle)
        uy = scale * math.sin(label_angle)

        radii = numpy.arange(0, int(1.4 * self.size.x / 2), RESOLUTION_STEP_SIZE / self.pixel_size)[1:]
        shells = self.radius_to_resolution(radii)
        lx = cx + radii * ux
        ly = cy + radii * uy
        offset = shells * LABEL_GAP / scale

        return numpy.column_stack((radii * scale, shells, lx, ly, label_angle + offset, label_angle - offset)), (cx, cy)

    def image_resolution(self, x, y):
        displacement = numpy.sqrt((x - self.center.x) ** 2 + (y - self.center.y) ** 2)
        return self.radius_to_resolution(displacement)

    def resolution_to_radius(self, d):
        angle = numpy.arcsin(numpy.float32(self.wavelength) / (2 * d))
        return self.distance * numpy.tan(2 * angle) / self.pixel_size

    def radius_to_resolution(self, r):
        angle = 0.5 * numpy.arctan2(r * self.pixel_size, self.distance)
        return numpy.float32(self.wavelength) / (2 * numpy.sin(angle))

    def radial_distance(self, x0, y0, x1, y1):
        d = numpy.sqrt((x0 - x1) ** 2 + (y0 - y1) ** 2) * self.pixel_size
        return d

    def set_colormap(self, name: str):
        c_map = matplotlib.cm.get_cmap(name, 256)
        rgba_data = matplotlib.cm.ScalarMappable(cmap=c_map).to_rgba(numpy.arange(0, 1.0, 1.0 / 256.0), bytes=True)
        rgba_data = rgba_data[:, :-1].reshape((256, 1, 3))
        self.color_map = rgba_data[:, :, ::-1]
        self.dirty = True

    def adjust(self, direction=None):
        self.settings.adjust(direction)
        self.dirty = True

    def next_frame(self):
        return self.dataset.next_frame()

    def prev_frame(self):
        return self.dataset.prev_frame()

    def load_frame(self, number):
        return self.dataset.get_frame(number)
