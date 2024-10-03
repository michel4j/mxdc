import hashlib
import ipaddress
import json
import math
import os
import pwd
import gzip
import pickle
import re
import reprlib
import socket
import string
import struct
import threading
import time
import unicodedata
import uuid
import shutil

from abc import ABC
from pathlib import Path
from os import PathLike
from html.parser import HTMLParser
from importlib import import_module
from typing import Any

import numpy
import msgpack

from gi.repository import GLib
from scipy import interpolate

from mxdc.com import ca
from . import log

logger = log.get_module_logger(__name__)


def get_short_uuid():
    return str(uuid.uuid1()).split('-')[0]


def get_min_max(values, ldev=1, rdev=1):
    a = numpy.array(values)
    a = a[(~numpy.isnan(a))]
    if len(a) == 0:
        mn, mx = -0.1, 0.1
    else:
        mn, mx = a.min(), a.max()
    dev = (mx - mn) / 10
    return mn - ldev * dev, mx + rdev * dev


def same_value(a, b, prec, deg=False):
    if deg:
        a = a % 360.0
        b = b % 360.0
    return abs(round(a - b, prec)) <= 10 ** -prec


SUPERSCRIPTS_TRANS = str.maketrans('0123456789+-', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻')


def sci_fmt(number, digits=3):
    exp = 0 if number == 0 else math.floor(math.log10(abs(number)))
    try:
        value = number * (10 ** -exp)
    except OverflowError as e:
        logger.error(f'Overflow Error: {number}: {e}')
        value = number
    exp_text = f'{exp}'.translate(SUPERSCRIPTS_TRANS)
    val_fmt = f'{{:0.{digits}f}}'
    val_text = val_fmt.format(value)
    return f"{val_text}" if exp == 0 else f"{val_text}×10{exp_text}"


class NameToInt(object):
    registry = {}

    @classmethod
    def get(cls, name):
        if name in cls.registry:
            return cls.registry[name]
        else:
            cls.registry[name] = len(cls.registry)
            return cls.registry[name]


class SignalWatcher(object):
    def __init__(self):
        self.activated = False
        self.data = None

    def __call__(self, obj, *args):
        self.activated = True
        self.data = args


def wait_for_signal(obj, signal, timeout=10):
    sw = SignalWatcher()
    _id = obj.connect(signal, sw)
    while not sw.activated and timeout > 0:
        time.sleep(0.05)
        timeout -= 0.05
    GLib.source_remove(_id)
    return sw.data


def every(iterable):
    for element in iterable:
        if not element:
            return False
    return True


def identifier_slug(value):
    """
    Converts to lowercase, removes non-word characters (alphanumerics and
    underscores) and converts spaces to hyphens. Also strips leading and
    trailing whitespace.
    """
    value = re.sub(r'[^\w\s-]', '', value).strip()
    return re.sub(r'[-\s]+', '_', value)


def get_project_name():
    if os.environ.get('MXDC_DEBUG'):
        os.environ.get('MXDC_DEBUG_USER', pwd.getpwuid(os.geteuid())[0])
        return os.environ.get('MXDC_DEBUG_USER', pwd.getpwuid(os.geteuid())[0])
    else:
        return pwd.getpwuid(os.geteuid())[0]

def get_group_name():
    if os.environ.get('MXDC_DEBUG'):
        os.environ.get('MXDC_DEBUG_USER', pwd.getpwuid(os.geteuid())[0])
        return os.environ.get('MXDC_DEBUG_USER', pwd.getpwuid(os.geteuid())[0])
    else:
        return get_project_name()

def get_project_home():
    if os.environ.get('MXDC_DEBUG'):
        return os.environ.get('MXDC_DEBUG_HOME', os.environ['HOME'])
    else:
        return os.environ['HOME']


def get_project_id():
    return os.geteuid()


def multi_count(exposure, *counters):
    """
    Count multiple devices asynchronously
    :param exposure: count time
    :param counters: list of counters to count
    :return: tuple of floats corresponding to count results, multi-element counters will have multiple entries in this tuple
    """

    if len(counters) == 1:
        return counters[0].count(exposure),
    else:
        counts = [0.0] * len(counters)

        def count(device, exposure, i):
            ca.threads_init()
            counts[i] = device.count(exposure)

        threads = []
        for i, device in enumerate(counters):
            threads.append(threading.Thread(target=count, args=(device, exposure, i,)))
        [th.start() for th in threads]
        [th.join() for th in threads]
        return tuple(counts)


# def slugify(s, empty=""):
#     valid_chars = "-_.()%s%s" % (string.ascii_letters, string.digits)
#     ns = ''.join([c for c in s if c in valid_chars])
#     if ns == "":
#         ns = empty
#     return ns


def slugify(value, empty="", allow_unicode=False):
    """
    Convert to ASCII if 'allow_unicode' is False. Convert spaces to hyphens.
    Remove characters that aren't alphanumerics, underscores, or hyphens.
    Convert to lowercase. Also strip leading and trailing whitespace.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')

    value = re.sub(r'[^\w\s-]', '', value).strip()
    return re.sub(r'[-\s]+', '-', value)


def format_partial(fmt, *args, **kwargs):
    class SafeDict(dict):
        def __missing__(self, key):
            return '{' + key + '}'

    return string.Formatter().vformat(fmt, args, SafeDict(**kwargs))


_COLOR_PATTERN = re.compile('#([0-9A-F]{2})([0-9A-F]{2})([0-9A-F]{2}).*')


def short_hash(w):
    h = hashlib.new('md5')
    h.update(w.encode())
    return h.hexdigest()[:9]


def logistic_score(x, best=1, fair=0.5):
    t = 3 * (x - fair) / (best - fair)
    return 1 / (1 + numpy.exp(-t))


def save_metadata(metadata, filename, backup=False):
    """
    Save meta-data to a file, optionally backing up the existing file
    :param metadata:
    :param filename:
    :param backup:
    :return:
    """
    path = Path(filename)
    try:
        if path.exists() and not metadata.get('id'):
            old_metadata = load_metadata(path)
            metadata['id'] = old_metadata.get('id')
    except ValueError as e:
        logger.error('Existing meta-data corrupted. Overwriting ...')

    if path.exists() and backup:
        shutil.move(path, path.with_suffix('.bak'))
    path.unlink(missing_ok=True)

    with open(path, 'w') as handle:
        json.dump(metadata, handle, indent=2, separators=(',', ':'), sort_keys=True)

    return metadata


def save_pickle(data, filename):
    with open(filename, 'wb') as handle:
        pickle.dump(data, handle, protocol=pickle.HIGHEST_PROTOCOL)


def load_pickle(filename):
    with open(filename, 'rb') as handle:
        data = pickle.load(handle)
    return data


def load_metadata(filename):
    with open(filename, 'r') as handle:
        metadata = json.load(handle)
    return metadata

def load_grid_data(filename):
    data = numpy.load(filelname)
    return {
        'grid_scores': data['scores'],
        'grid_index': data['indices'],
        'grid_frames': data['frames'],
        'grid': data['grid']
    }

def load_json(filename):
    with open(filename, 'r') as handle:
        info = json.load(handle)
    return info


def load_chkpt(filename):
    with gzip.open(filename, 'rb') as handle:
        info = msgpack.load(handle)
    return info

def get_data_ids(report_file):
    report = Path(report_file)
    if report.exists() and report.is_file():
        folder = report.parent
    elif report.exists() and report.is_dir():
        folder = report
    else:
        return []

    file_path = folder.joinpath('process.chkpt')
    checkpoint = misc.load_chkpt(file_path)
    datasets = [d['parameters']['dataset'] for d in checkpoint['datasets']]
    data_ids = []
    for dset in datasets:
        meta_path = Path(dset['directory']).joinpath(f'{dset["label"]}.meta')
        meta = misc.load_json(meta_path)
        data_ids.append(meta.get('id'))

    return data_ids


def _get_gateway():
    """Read the default gateway directly from /proc."""
    with open("/proc/net/route") as handle:
        for line in handle:
            fields = line.strip().split()
            if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                continue
            return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))


def _get_address(gateway, port=22):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((gateway, port))
    address = (s.getsockname()[0])
    s.close()
    return address


def get_address():
    return ipaddress.ip_address('{}'.format(_get_address(_get_gateway())))


def get_free_tcp_port():
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.bind(('localhost', 0))
    addr, port = tcp.getsockname()
    tcp.close()
    return port


def frame_score(info):
    try:
        return info['bragg_spots']*info['signal_avg']
    except KeyError:
        return 0.0


class ContextMessenger(object):
    def __init__(self, device, msg1, msg2):
        self.device = device
        self.enter_message = msg1
        self.exit_message = msg2

    def __enter__(self):
        GLib.idle_add(self.device.emit, 'message', self.enter_message)
        return self

    def __exit__(self, type, value, traceback):
        GLib.idle_add(self.device.emit, 'message', self.exit_message)
        return False


# class DotDict(dict):
#     """dot.notation access to dictionary attributes"""
#     __getattr__ = dict.get
#     __setattr__ = dict.__setitem__
#     __delattr__ = dict.__delitem__


class Call(object):
    def __init__(self, func, *args):
        self.func = func
        self.args = args

    def __call__(self):
        self.func(*self.args)


class Chain(object):
    def __init__(self, timeout, *calls):
        self.timeout = timeout
        self.calls = [Call(*call) for call in calls]
        GLib.timeout_add(self.timeout, self.run)

    def run(self):
        if self.calls:
            call = self.calls.pop(0)
            call()
            return True

    def wait(self, timeout=3):
        poll = 0.05
        time_left = timeout
        while len(self.calls) and time_left > 0:
            time.sleep(poll)
            time_left -= poll


def wait_for_file(file_path: PathLike, timeout=10):
    path = Path(file_path)
    poll = 0.05
    time_left = timeout
    while not path.exists() and time_left > 0:
        time.sleep(poll)
        timeout -= poll
    return time_left > 0


def load_binary_data(filename):
    with open(filename, 'rb') as handle:
        data = handle.read()
    return data


class RecordArray(object):
    """
    Record Array Manager for numpy structured arrays.

    :param dtype: numpy dtype dictionary
    :param size: default allocation size of record array
    :param loop: whether to use ring buffer
    :param grid: whether to use grid mode processing
    :param data: optional record array to initialize to, dtype ignored
    """

    def __init__(self, dtype, size=10, loop=False, data=None):
        self.dtype = numpy.dtype(dtype)
        self.lock = threading.Lock()
        self.loop = loop
        self.length = 0
        self.size = size
        self.funcs = {}

        if data is None:
            self._data = numpy.empty(self.size, dtype=self.dtype)
        else:
            self._data = data
            self.dtype = data.dtype
            self.length = data.shape[0]
            self.size = self.length
            self.update_funcs()

    def __len__(self):
        return self.length

    def update_funcs(self):
        """
        Update interpolation functions
        """
        if self.length > 1:
            names = tuple(self.dtype.fields.keys())
            x_name = names[0]
            for name in names[1:]:
                self.add_func(name, self.data[x_name], self.data[name])

    def add_func(self, name, x, y):
        """
        Add interpolated function to functions

        :param name: column name
        :param x: x-axis data
        :param y: y-axis data
        """
        self.funcs[name] = interpolate.interp1d(x, y, copy=False, fill_value="extrapolate")

    def __call__(self, name, x):
        """
        Get interpolated value for named column at given position

        :param name: column name
        :param x: x-axis value
        :return: y-axis value or 0 if function does not exist
        """
        if name in self.funcs:
            return self.funcs[name](x)
        else:
            return 0

    def resize(self):
        """
        Increase the size of the storage by 50%
        """
        self.size = int(1.5 * self.size)
        self._data.resize((self.size,), refcheck=False)

    def append(self, rec):
        """
        Append a tuple of values to the record array. Cycle the array around if ring buffer option is set
        and the array has reached max size
        :param rec: sequence of values to add to array
        """

        with self.lock:
            if self.length == self.size:
                if self.loop:
                    self._data[:-1] = self._data[1:]
                    self.length = self.size - 1
                else:
                    self.resize()

            self._data[self.length] = tuple(rec)
            self.length += 1
            self.update_funcs()

    def extend(self, recs):
        for rec in recs:
            self.append(rec)

    @property
    def data(self):
        return self._data[:self.length]


def normalize_name(name):
    """
    Slugify and then Normalize a string into an attribute name converting camel-case to snake-case
    :param name: string
    :return:
    """
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', slugify(name))
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()


def check_call(f):
    """
    Log all calls to the function or method
    :param f: function or method
    """

    def new_f(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as err:
            params = ['{}'.format(reprlib.repr(a)) for a in args[1:]]
            params.extend(['{}={}'.format(p[0], reprlib.repr(p[1])) for p in list(kwargs.items())])
            params = ', '.join(params)
            logger.info('{} : <{}({})>'.format(f, f.__name__, params))
            print(err)
            raise

    new_f.__name__ = f.__name__
    return new_f


def import_string(dotted_path):
    """
    Import a dotted module path and return the attribute/class designated by the
    last name in the path. Raise ImportError if the import failed.
    """
    try:
        module_path, class_name = dotted_path.rsplit('.', 1)
    except ValueError as err:
        raise ImportError("{} doesn't look like a module path".format(dotted_path)) from err

    module = import_module(module_path)

    try:
        return getattr(module, class_name)
    except AttributeError as err:
        raise ImportError(
            'Module "{}" does not define a "{}" attribute/class'.format(module_path, class_name)
        ) from err


def set_settings(settings, debug=False, **kwargs):
    """
    Apply keyword values to PVs in a dictionary if available
    :param settings: dictionary of process variables to set
    :param kwargs: key value pairs for the process variables, keys with value None are ignored if key points to a tuple
    of process variables, then the value should be a list or tuple of values to put to each.
    :return: list of keys actually set
    """
    changed = []
    for key, value in kwargs.items():
        if key in settings and value is not None:
            if isinstance(settings[key], tuple):
                for p, v in zip(settings[key], value):
                    p.put(v, wait=True)
                    if debug:
                        logger.debug(f'SETTING: {p.name} = {v}')
            else:
                settings[key].put(kwargs[key], wait=True)
                if debug:
                    logger.debug(f'SETTING: {settings[key].name} = {kwargs[key]}')
            changed.append(key)
    return changed


class HTMLFilter(HTMLParser, ABC):
    """
    A simple no deps HTML -> TEXT converter.
    @see https://stackoverflow.com/a/55825140
    """
    text = ''

    def handle_data(self, data):
        self.text += data


def html2text(data):
    """
    Convert HTML to plain text.

    :param data: HTML data
    :return: text str
    """
    f = HTMLFilter()
    f.feed(data)
    return f.text


def grid_from_bounds(bbox, step_size, **kwargs):
    """
    Make a grid from a bounding box array
    :param bbox: array of two points representing a 2D bounding box [(left, top), (right, bottom)]
    :param step_size: step size
    :param kwargs: extra args
    :return: array of points on the grid in order
    """

    grid_shape = calc_grid_size(bbox, step_size)
    grid_size = grid_shape * step_size

    grid_center = (bbox[1] + bbox[0])/2.
    grid_origin = grid_center - grid_size/2. + step_size/2

    nX, nY = grid_shape
    xi = numpy.arange(0, nX)*step_size + grid_origin[0]
    yi = numpy.arange(0, nY)*step_size + grid_origin[1]

    return calc_grid_coords(xi, yi, **kwargs)


def grid_from_size(size: tuple, step: float, center: tuple, **kwargs):
    """
    Make a grid from shape
    :param size: tuple (width, height) number of points in x and y directions
    :param step: step size
    :param center: center of grid in same units as step
    :param kwargs: Extra args
    :return: array of points on the grid in order
    """

    cX, cY = center
    nX, nY = size
    radius = step / 2

    xi = (numpy.arange(0, nX) - (nX - 1) / 2) * step + cX
    yi = (numpy.arange(0, nY) - (nY - 1) / 2) * step + cY

    return calc_grid_coords(xi, yi, **kwargs)


def calc_grid_coords(xi, yi, snake=False, vertical=False, buggy=False):
    """
    Calculate the grid coordinates and return a properly ordered sequence based on device traversal
    :param xi: array of x coordinates
    :param yi: array of y coordinates
    :param snake: invert alternate rows/columns
    :param vertical: traverse verticaly
    :param buggy:  Fix buggy indexing for power-pmac
    :return: 3xN array of coordinates for each grid point, and a 2xN array for the corresponding
    index positions in the 2D grid, and the corresponding frame numbers for each position
    """
    x_ij, y_ij = numpy.meshgrid(xi[::-1], yi, sparse=False)
    nX, nY = len(xi), len(yi)
    ix = numpy.arange(nX).astype(int)
    jy = numpy.arange(nY).astype(int)
    i_xy, j_xy =  numpy.meshgrid(ix[::-1], jy, sparse=False)

    if not vertical or nX >= nY:
        if snake:
            x_ij[1::2, :] = x_ij[1::2, ::-1]  # flip even rows
            i_xy[1::2, :] = i_xy[1::2, ::-1]  # flip even rows
        grid = numpy.array([
            (x_ij[j, i], y_ij[j, i], 0.0)
            for j in jy for i in ix  # fast axis is x
        ])
        index = [
            (j_xy[j, i], i_xy[j, i])
            for j in jy for i in ix
        ]

    else:
        if snake:
            y_ij[:, 1::2] = y_ij[::-1, 1::2]  # flip even columns
            j_xy[:, 1::2] = j_xy[::-1, 1::2]  # flip even columns
        grid = numpy.array([
            (x_ij[j, i], y_ij[j, i], 0.0)
            for i in ix for j in jy  # fast axis is y
        ])
        index = [
            (j_xy[j, i], i_xy[j, i])
            for i in ix for j in jy
        ]

    size = len(index)
    frames = numpy.arange(size)

    # some MD2s produce an extra frame every new line
    if buggy:
        frames = (frames + numpy.divmod(frames, nX)[0] + 1)
        frames[frames>=size] = size-1

    return grid, index, frames + 1

def calc_grid_shape(width, height, aperture):
    """
    Calculate the size of the grid

    :param width: width
    :param height: height
    :param aperture: step size
    :param tight: bool, true if close fitting required
    :return: tuple (x-size, y-size)
    """
    size = numpy.array([width, height])
    nX, nY = numpy.round(size / aperture).astype(int)
    nX = max(1, nX)
    nY = max(2, nY)
    return nX, nY


def calc_grid_size(bbox, step_size):
    """
    Calculate the size of the grid

    :param bbox: bounding_box coordinates in pixels
    :param step_size: step size in pixels
    :return: tuple (x-size, y-size)
    """

    grid_shape = numpy.ceil(numpy.abs(bbox[1] - bbox[0])/step_size).astype(int)
    return grid_shape

def natural_keys(text):
    """
    Convert a text string into a tuple for natural sorting
    :param text: text string
    :return: tuple of tokens with numbers separated out
    """
    return tuple([int(token) if token.isdigit() else token for token in re.split(r'(\d+)', f'{text}')])


def factorize(n, minimum=None, maximum=None):
    """
    Return all factors of the given number between the given range.
    :param n: number to factorize
    :param minimum: minimum factor or None for no minimum
    :param maximum: maximum factor or None for a maximum of n/2
    :return: numpy array of factors
    """
    minimum = 1 if minimum is None else minimum
    maximum = n//2 if maximum is None else maximum
    candidates = numpy.arange(minimum, maximum + 1)
    return candidates[(n % candidates) == 0]

def load_hkl(filename):
    data = numpy.loadtxt(filename, comments='!')
    spots = numpy.empty((data.shape[0], 4), dtype=numpy.uint16)
    spots[:, :3] = numpy.round(data[:,5:8]).astype(numpy.uint16)
    spots[:, 3] = data[:,4] > 0
    return spots

def load_spots(filename):
    data = numpy.loadtxt(filename, comments='!')
    spots = numpy.empty((data.shape[0], 4), dtype=numpy.uint16)
    spots[:, :3] = numpy.round(data[:,:3]).astype(numpy.uint16)
    if data.shape[1] > 4:
        spots[:, 3] = numpy.abs(data[:,4:]).sum(axis=1) > 0
    else:
        spots[:, 3] = 1
    return spots


def get_dict_field(d: dict, key: str, default=None) -> Any:
    """
    Obtain and return a field from a dictionary using dot notation, return the default if not found.
    :param d: target dictionary
    :param key: field specification using dot separator notation
    :param default: default value if field is not found
    """

    if key in d:
        return d[key]
    elif "." in key:
        first, rest = key.split(".", 1)
        if first in d and isinstance(d[first], dict):
            return get_dict_field(d[first], rest, default)
    return default


def set_dict_field(d: dict, key: str, value: Any):
    """
    Set a nested dictionary value using dot notation, return modified dictionary

    :param d: target dictionary
    :param key: field specification using dot separator notation
    :param value: Value to set
    """

    if not "." in key:
        d[key] = value
    else:
        first, rest = key.split(".", 1)
        if first in d and isinstance(d[first], dict):
            set_dict_field(d[first], rest, value)
        else:
            d[first] = {}
            set_dict_field(d[first], rest, value)


class DotDict:
    """dot.notation access to dictionary attributes"""

    def __init__(self, details):
        self.details = details

    def __repr__(self):
        return self.details.__repr__()

    def __str__(self):
        return self.details.__str__()

    def __getitem__(self, item):
        return self.details.__getitem__(item)

    def __setitem__(self, key, value):
        self.details.__setitem__(key, value)

    def update(self, *args, **kwargs):
        for arg in args + (kwargs,):
            if isinstance(arg, dict):
                for key, value in arg.items():
                    self.set(key, value)

    def keys(self):
        return self.details.keys()

    def values(self):
        return self.details.values()

    def items(self):
        return self.details.items()

    def __iter__(self):
        return self.details.__iter__()

    def __getattr__(self, item):
        if hasattr(self, 'details'):
            if item in self.details:
                value = self.details[item]
                if isinstance(value, DotDict):
                    return value
                elif isinstance(value, dict):
                    return DotDict(value)
                else:
                    return value
            else:
                raise KeyError(f'Invalid Attribute "{item}"')

    def __setattr__(self, key, value):
        if not 'details' in self.__dict__:
            return super().__setattr__(key, value)
        elif key in self.__dict__:
            super().__setattr__(key, value)
        else:
            self.details.__setitem__(key, value)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Obtain and return a field from the details dictionary using dot notation, return the default if not found.
        :param key: field specification using dot separator notation
        :param default: default value if field is not found
        """
        return get_dict_field(self.details, key, default)

    def set(self, key: str, value: Any):
        """
        Set a key value
        :param key: key obeying dot-notation
        :param value: value to set
        """
        set_dict_field(self.details, key, value)
