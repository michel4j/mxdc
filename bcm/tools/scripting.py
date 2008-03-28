import sys, time
import threading
import gtk, gobject
import numpy
from Plotter import Plotter
from LogServer import LogServer
from bcm.protocols import ca

class Error(Exception):
    def __init__(self, msg):
        self.message = msg
    
    def __str__(self):
        return self.message
            
class Script(threading.Thread, gobject.GObject):
    __gsignals__ = {}
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    def __init__(self, func=None, *args, **kw):
        threading.Thread.__init__(self)
        gobject.GObject.__init__(self)
        self.func = func
        self.args = args
        self.kw = kw
        
    def __call__(self):        
        try:
            if self.func:
                self.func(*self.args, **self.kw)
            gobject.idle_add(self.emit, "done")
        except KeyboardInterrupt:
            gobject.idle_add(self.emit, "error")
            
    def run(self):
        ca.thread_init()
        try:
            if self.func:
                self.func(*self.args, **self.kw)
            gobject.idle_add(self.emit, "done")
        except KeyboardInterrupt:
            gobject.idle_add(self.emit, "error")

    def on_activate(self, widget=None, event=None):
        self.start()
        
gobject.type_register(Script)
