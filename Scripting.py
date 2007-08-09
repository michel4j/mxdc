#!/usr/bin/env python

import sys, time, copy
import threading
import gtk, gobject
import numpy
from Plotter import Plotter
from LogServer import LogServer
from Fitting import *
from Beamline import beamline
import EPICS as CA

gobject.threads_init()

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
        CA.thread_init()
        try:
            if self.func:
                self.func(*self.args, **self.kw)
            gobject.idle_add(self.emit, "done")
        except KeyboardInterrupt:
            gobject.idle_add(self.emit, "error")

    def on_activate(self, widget=None, event=None):
        self.start()
        
gobject.type_register(Script)
