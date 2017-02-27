
from mxdc.com import ca
from gi.repository import GObject
import numpy
import os
import pwd
import re
import string
import threading
import time
import uuid

    
def get_short_uuid():
    return str(uuid.uuid1()).split('-')[0]


def same_value(a, b, prec, deg=False):
    if deg:
        a = a % 360.0
        b = b % 360.0
    return abs(round(a-b, prec)) <= 10**-prec
        
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

def get_project_name():
    if os.environ.get('MXDC_DEBUG'):
        return os.environ.get('MXDC_DEBUG_USER')
    else:
        return pwd.getpwuid(os.geteuid())[0]

def multi_count(*args):
    counts = [0.0]*(len(args)-1)
    
    def count(device, t, i):
        ca.threads_init()
        counts[i] = device.count(t)
    
    threads = []    
    for i, device in enumerate(args[:-1]):
        threads.append(threading.Thread(target=count, args=(device, args[-1],i,)))
    [th.start() for th in threads]
    [th.join() for th in threads]
    return tuple(counts)


def slugify(s, empty=""):
    valid_chars = "-_.()%s%s" % (string.ascii_letters, string.digits)
    ns = ''.join([c for c in s if c in valid_chars])
    if ns == "":
        ns = empty
    return ns

_COLOR_PATTERN = re.compile('#([0-9A-F]{2})([0-9A-F]{2})([0-9A-F]{2}).*')
def lighten_color(s, step=51):    
    R,G,B = [min(max(int('0x'+v,0)+step,0),255) for v in _COLOR_PATTERN.match(s.upper()).groups()]
    return "#%02x%02x%02x" % (R,G,B)

def darken_color(s, step=51):
    return lighten_color(s, step=-step)

def logistic_score(x, best=1, fair=0.5):
    t = 3*(x - fair)/(best - fair)
    return 1/(1+numpy.exp(-t))
