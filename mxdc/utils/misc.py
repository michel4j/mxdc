import os
import pwd
import re
import string
import threading
import time

import numpy
import uuid
from gi.repository import GObject
from mxdc.com import ca


def get_short_uuid():
    return str(uuid.uuid1()).split('-')[0]


def get_min_max(values, ldev=10, rdev=10):
    a = numpy.array(values)
    a = a[(numpy.isnan(a) == False)]
    if len(a) == 0:
        return -0.1, 0.1
    _std = a.std()
    if _std < 1e-10:  _std = 0.1
    mn, mx = a.min() - ldev * _std, a.max() + rdev * _std
    return mn, mx


def same_value(a, b, prec, deg=False):
    if deg:
        a = a % 360.0
        b = b % 360.0
    return abs(round(a - b, prec)) <= 10 ** -prec


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
    GObject.source_remove(_id)
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


def multi_count(*args):
    counts = [0.0] * (len(args) - 1)

    def count(device, t, i):
        ca.threads_init()
        counts[i] = device.count(t)

    threads = []
    for i, device in enumerate(args[:-1]):
        threads.append(threading.Thread(target=count, args=(device, args[-1], i,)))
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


def lighten_color(s, step=51):
    R, G, B = [min(max(int('0x' + v, 0) + step, 0), 255) for v in _COLOR_PATTERN.match(s.upper()).groups()]
    return "#%02x%02x%02x" % (R, G, B)


def darken_color(s, step=51):
    return lighten_color(s, step=-step)


def logistic_score(x, best=1, fair=0.5):
    t = 3 * (x - fair) / (best - fair)
    return 1 / (1 + numpy.exp(-t))
