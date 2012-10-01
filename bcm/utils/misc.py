import os
import sys
import re
import math, time
import gobject
import string, unicodedata
import pwd
import threading
from bcm.protocol import ca

if sys.version_info[:2] == (2,5):
    import uuid
else:
    from bcm.utils import uuid # for 2.3, 2.4

    
def get_short_uuid():
    return str(uuid.uuid1()).split('-')[0]

    
#def gtk_idle(sleep=None):
#    while gtk.events_pending():
#        gtk.main_iteration()

class SignalWatcher(object):
    def __init__(self):
        self.activated = False
        self.data = None
        
    def __call__(self, obj, *args):
        self.activated = True
        self.data = args
        
def wait_for_signal(obj, signal, timeout=10):
    sw = SignalWatcher()
    id = obj.connect(signal, sw)
    while not sw.activated and timeout > 0:
        time.sleep(0.05)
        timeout -= 0.05
    gobject.source_remove(id)
    return sw.data
    
def all(iterable):
    for element in iterable:
        if not element:
            return False
    return True

def get_project_name():
    if os.environ.get('BCM_DEBUG') is not None:
        return os.environ.get('BCM_DEBUG_USER', 'testuser')
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
