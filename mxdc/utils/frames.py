import os
import time
import zmq
import numpy
import cv2
import lz4.block, lz4.frame

import json
from pprint import pprint
from queue import Queue

from mxdc import Engine
from mxdc.libs.imageio import read_image
from mxdc.libs.imageio.formats import DataSet

MAX_FILE_FREQUENCY = 10

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
        process_frame(data) method.
    """

    def __init__(self, master):
        super().__init__()
        self.master = master


class FileMonitor(DataMonitor):
    """
    Data Monitor which reads frames from disk
    """

    MAX_SAVE_JITTER = 0.5  # maxium amount of time in seconds to wait for tile to be done writing to disk

    def __init__(self, *args):
        super().__init__(*args)
        self.skip_count = 10  # number of frames to skip at once
        self.inbox = Queue(10000)
        self.start()

    def add(self, path):
        self.inbox.put(path)

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
            count = 0
            while not self.inbox.empty() and count < self.skip_count:
                path = self.inbox.get()
                count += 1

            if path and not self.get_state("busy"):
                success = self.load(path)
                if success:
                    path = None
            time.sleep(1/MAX_FILE_FREQUENCY)


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
        'detector_size': ('x_pixels_in_detector',
                          'y_pixels_in_detector'),

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

    def __init__(self, master, address):
        super().__init__(master)
        self.context = None
        self.receiver = None
        self.dataset = None
        self.address = address
        self.metadata = {}
        self.start()

    def parse_header(self, info, msg):
        header = json.loads(msg[1])
        pprint(header)
        for key, field in self.HEADER_FIELDS.items():
            converter = self.CONVERTERS.get(key, lambda v: v)
            try:
                if not isinstance(field, (tuple, list)):
                    self.metadata[key] = converter(header[field])
                else:
                    self.metadata[key] = tuple(converter(header[sub_field]) for sub_field in field)
            except ValueError:
                pass
            print(header, key, field, self.metadata)

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

    def parse_image(self, info, msg):
        frame = json.loads(msg[1])
        extra = json.loads(msg[3])
        size = frame['shape'][0]*frame['shape'][1] * SIZES[frame['type']]
        raw_data = lz4.block.decompress(msg[2], uncompressed_size=size)
        dtype = TYPES[frame['type']]
        data = numpy.fromstring(raw_data, dtype=frame['type']).reshape(*frame['shape'])

        self.dataset = DataSet()
        header = self.metadata.copy()

        data = data.view(dtype)

        header['saturated_value'] = data.max()
        stats_data = data[(data >= 0) & (data < header['saturated_value'])].view(dtype)

        avg, stdev = numpy.ravel(cv2.meanStdDev(stats_data))

        header['average_intensity'] = avg
        header['std_dev'] = stdev
        header['min_intensity'] = stats_data.min()
        header['max_intensity'] = stats_data.max()
        header['overloads'] = 0
        header['frame_number'] = int(info['frame'])
        header['filename'] = 'Frame {}'.format(info['frame'])
        header['name'] = 'Frame {}'.format(info['frame'])
        header['start_angle'] += header['frame_number'] * header['delta_angle']

        # update dataset
        self.dataset.header = header
        self.dataset.data = data
        self.dataset.stats_data = stats_data

        self.master.process_frame(self.dataset)

    def parse_footer(self, info, msg):
        print(info)

    def run(self):
        self.context = zmq.Context()
        self.receiver = self.context.socket(zmq.PULL)
        self.receiver.connect(self.address)
        while not self.stopped:
            msg = self.receiver.recv_multipart()
            msg_type = json.loads(msg[0])
            print(msg_type)
            if msg_type['htype'] == 'dheader-1.0':
                self.parse_header(msg_type, msg)
            elif msg_type['htype'] == 'dimage-1.0':
                try:
                    self.parse_image(msg_type, msg)
                except:
                    pass
            elif msg_type['htype'] == 'dseries_end-1.0':
                self.parse_footer(msg_type, msg)
            time.sleep(0)
