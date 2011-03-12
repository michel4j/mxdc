import os
import sys
import math, time
#import gtk
import gobject
import pwd

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
    #return pwd.getpwuid(os.geteuid())[0]
    return 'fodje'