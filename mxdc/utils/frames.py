import json
import os
import threading
import time
from collections import deque
from enum import Enum

import zmq
from mxio import read_image
from mxio.formats import eiger

from mxdc import Engine
from mxdc.utils import log

logger = log.get_module_logger('frames')

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

    MAX_SAVE_JITTER = 0.5  # maxium amount of time in seconds to wait for tile to be done writing to disk

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
        while not success and attempts < 10:
            loadable = (
                os.path.exists(path) and
                time.time() - os.path.getmtime(path) > self.MAX_SAVE_JITTER
            )
            if loadable:
                try:
                    dataset = read_image(path)
                    if self.master:
                        self.master.process_frame(dataset)
                    success = True
                except Exception:
                    success = False
            attempts += 1
            time.sleep(1/MAX_FILE_FREQUENCY)
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
            time.sleep(1/MAX_FILE_FREQUENCY)


class StreamTypes(Enum):
    PUSH = 1
    PUBLISH = 2


class StreamMonitor(DataMonitor):
    """
    A data monitor which monitors a zeromq stream for new data
    """

    def __init__(self, master, address, kind=StreamTypes.PUSH, maxfreq=10):
        super().__init__(master)
        self.context = None
        self.receiver = None
        self.dataset = None
        self.kind = kind
        self.address = address
        self.last_time = time.time()
        self.inbox = deque(maxlen=50)
        self.start()

    def start(self):
        super().start()
        parser_thread = threading.Thread(target=self.run_parser, daemon=True, name=self.__class__.__name__ + ":Parser")
        parser_thread.start()

    def run_parser(self):
        while not self.is_stopped():
            if len(self.inbox) and not self.is_paused():
                msg = self.inbox.popleft()
                msg_type = json.loads(msg[0])
                if msg_type['htype'] == 'dheader-1.0':
                    self.dataset = eiger.EigerStream()
                    self.dataset.read_header(msg)
                elif msg_type['htype'] == 'dimage-1.0' and self.dataset is not None:
                    self.dataset.read_image(msg)
                    fraction = self.dataset.header['frame_number'] / self.dataset.header['num_images']
                    if self.master:
                        self.master.process_frame(self.dataset)
                    self.set_state(progress=(fraction, 'frames collected'))
            time.sleep(0.01)

    def run(self):
        self.context = zmq.Context()
        socket_type = zmq.SUB if self.kind == StreamTypes.PUBLISH else zmq.PULL
        with self.context.socket(socket_type) as receiver:
            receiver.connect(self.address)
            if self.kind == StreamTypes.PUBLISH:
                receiver.setsockopt_string(zmq.SUBSCRIBE, "")
            self.last_time = time.time()
            while not self.stopped:
                messages = receiver.recv_multipart()
                self.inbox.append(messages)
                time.sleep(0.0)


def line(x1, y1, x2, y2):
    steep = 0
    coords = []
    dx = abs(x2 - x1)
    sx = 1 if (x2 - x1) > 0 else -1

    dy = abs(y2 - y1)
    sy = 1 if (y2 - y1) > 0 else -1

    if dy > dx:
        steep = 1
        x1, y1 = y1, x1
        dx, dy = dy, dx
        sx, sy = sy, sx

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
    return (x, y, w, h)