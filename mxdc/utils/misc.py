import hashlib
import json
import os
import pwd
import re
import reprlib
import socket
import string
import struct
import subprocess
import threading
import time
import uuid
import ipaddress
import numpy

from gi.repository import GLib
from scipy import interpolate
from importlib import import_module
from threading import Lock
from mxdc.com import ca
from . import decorators
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
    value = re.sub('[^\w\s-]', '', value).strip()
    return re.sub('[-\s]+', '_', value)


def get_project_name():
    if os.environ.get('MXDC_DEBUG'):
        return os.environ.get('MXDC_DEBUG_USER', pwd.getpwuid(os.geteuid())[0])
    else:
        return pwd.getpwuid(os.geteuid())[0]


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


def slugify(s, empty=""):
    valid_chars = "-_.()%s%s" % (string.ascii_letters, string.digits)
    ns = ''.join([c for c in s if c in valid_chars])
    if ns == "":
        ns = empty
    return ns


def format_partial(fmt, *args, **kwargs):
    import string

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


def open_terminal(directory=None):
    if not directory:
        directory = get_project_home()
    else:
        directory = directory.replace('~', get_project_home())
    commands = [
        'gnome-terminal',
        '--geometry=132x24',
        '--working-directory={}'.format(directory),
    ]
    p = subprocess.Popen(commands)


def save_metadata(metadata, filename):
    try:
        if os.path.exists(filename) and not metadata.get('id'):
            old_metadata = load_metadata(filename)
            metadata['id'] = old_metadata.get('id')
    except ValueError as e:
        logger.error('Existing meta-data corrupted. Overwriting ...')
    with open(filename, 'w') as handle:
        json.dump(metadata, handle, indent=2, separators=(',', ':'), sort_keys=True)
    return metadata


def load_metadata(filename):
    with open(filename, 'r') as handle:
        metadata = json.load(handle)
    return metadata


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


@decorators.memoize
def get_address():
    return ipaddress.ip_address('{}'.format(_get_address(_get_gateway())))


def get_free_tcp_port():
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.bind(('', 0))
    addr, port = tcp.getsockname()
    tcp.close()
    return port


def frame_score(info):
    return info['signal']


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


class DotDict(dict):
    """dot.notation access to dictionary attributes"""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


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


def wait_for_file(file_path, timeout=10):
    poll = 0.05
    time_left = timeout
    while not os.path.exists(file_path) and time_left > 0:
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
        self.lock = Lock()
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


def set_settings(settings, **kwargs):
    """
    Apply keyword values to PVs in a dictionary if available
    :param settings: dictionary of process variables to set
    :param kwargs: key value pairs for the process variables, keys with value None are ignored
    :return: list of keys actually set
    """
    changed = []
    for key, value in kwargs.items():
        if key in settings and value is not None:
            settings[key].put(kwargs[key], wait=True)
            changed.append(key)
    return changed


