import json
import os
import time
from enum import Enum
import threading
from collections import deque

import cv2
import lz4.block
import lz4.frame
import numpy
import zmq
from mxio import read_image
from mxio.formats import DataSet

from mxdc import Engine
from mxdc.utils import log

logger = log.get_module_logger('frames')

MAX_FILE_FREQUENCY = 5

SIZES = {
    'uint16': 2,
    'uint32': 4
}

TYPES = {
    'uint16': numpy.int16,
    'uint32': numpy.int32
}


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
                path = self.inbox.pop()

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
    HEADER_FIELDS = {
        'detector_type': 'description',
        'two_theta': 'two_theta_start',
        'pixel_size': 'x_pixel_size',
        'exposure_time': 'frame_time',
        'wavelength': 'wavelength',
        'distance': 'detector_distance',
        'beam_center': ('beam_center_x', 'beam_center_y'),
        'energy': 'photon_energy',
        'sensor_thickness': 'sensor_thickness',
        'detector_size': ('x_pixels_in_detector', 'y_pixels_in_detector'),

    }
    CONVERTERS = {
        'pixel_size': lambda v: float(v) * 1000,
        'exposure_time': float,
        'wavelength': float,
        'distance': float,
        'beam_center': float,
        'saturated_value': int,
        'num_frames': int,
        'date': 'data_collection_date',
        'energy': float,
        'sensor_thickness': lambda v: float(v) * 1000,
        'detector_size': int,
    }

    def __init__(self, master, address, kind=StreamTypes.PUSH, maxfreq=10):
        super().__init__(master)
        self.context = None
        self.receiver = None
        self.dataset = None
        self.kind = kind
        self.address = address
        self.last_time = time.time()
        self.metadata = {}
        self.inbox = deque(maxlen=10)
        self.parser_delay = 1/maxfreq
        self.start()

    def start(self):
        super().start()
        parser_thread = threading.Thread(target=self.run_parser, daemon=True, name=self.__class__.__name__ + ":Parser")
        parser_thread.start()

    def run_parser(self):
        while not self.is_stopped():
            if len(self.inbox) and not self.is_paused():
                msg = self.inbox.pop()
                msg_type = json.loads(msg[0])
                if msg_type['htype'] == 'dheader-1.0':
                    self.parse_header(msg_type, json.loads(msg[1]))
                elif msg_type['htype'] == 'dimage-1.0':
                    try:
                        self.parse_image(msg_type, json.loads(msg[1]), msg[2])
                    except:
                        pass
                elif msg_type['htype'] == 'dseries_end-1.0':
                    self.parse_footer(msg_type, msg)
            time.sleep(0.0)

    def parse_header(self, info, header):
        logger.debug('Stream started - Parsing header')
        for key, field in self.HEADER_FIELDS.items():
            converter = self.CONVERTERS.get(key, lambda v: v)
            try:
                if not isinstance(field, (tuple, list)):
                    self.metadata[key] = converter(header[field])
                else:
                    self.metadata[key] = tuple(converter(header[sub_field]) for sub_field in field)
            except ValueError:
                pass

        # try to find oscillation axis and parameters as first non-zero average
        for axis in ['chi', 'kappa', 'omega', 'phi']:
            if header.get('{}_increment'.format(axis), 0) > 0:
                self.metadata['num_frames'] = info
                self.metadata['rotation_axis'] = axis
                self.metadata['start_angle'] = header['{}_start'.format(axis)]
                self.metadata['delta_angle'] = header['{}_increment'.format(axis)]
                self.metadata['num_images'] = header['nimages']*header['ntrigger']
                self.metadata['total_angle'] = self.metadata['num_images'] * self.metadata['delta_angle']
                break

    def parse_image(self, info, frame, img_data):
        logger.debug(f"Parsing stream image {info} {frame} {len(img_data)}")
        size = frame['shape'][0]*frame['shape'][1] * SIZES[frame['type']]
        self.dataset = DataSet()
        meta = self.metadata.copy()
        frame_number = int(info['frame']) + 1
        self.dataset.header.update({
            'saturated_value': 1e6,
            'overloads': 0,
            'frame_number': frame_number,
            'filename': 'Stream',
            'name': 'Stream',
            'start_angle': meta['start_angle'] + frame_number * meta['delta_angle'],
        })

        try:
            raw_data = lz4.block.decompress(img_data[12:], uncompressed_size=size*4)
            dtype = TYPES[frame['type']]
            data = numpy.fromstring(raw_data, dtype=frame['type']).reshape(*frame['shape'])
            stats_data = data[(data >= 0) & (data < self.dataset.header['saturated_value'])].view(dtype)
            data = data.view(dtype)
            avg, stdev = numpy.ravel(cv2.meanStdDev(stats_data))
            self.dataset.header.update({
                'average_intensity': avg,
                'std_dev': stdev,
                'min_intensity': stats_data.min(),
                'max_intensity': stats_data.max(),
            })
            self.dataset.data = data
            self.dataset.stats_data = stats_data

            if self.master:
                self.master.process_frame(self.dataset)
        except Exception as e:
            logger.error(f'Error decoding stream: {e}')
            self.set_state(progress=(self.dataset.header['frame_number'] / meta['num_images'], 'frames collected'))

        self.last_time = time.time()


    def parse_footer(self, info, msg):
        logger.debug('Stream Ended')

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