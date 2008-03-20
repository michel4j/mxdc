#!/usr/bin/env python

import gtk, gobject, time

class LogServerClass(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['log'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))

    def __init__(self):
        gobject.GObject.__init__(self)
        
    def log(self, text):
        gobject.idle_add(self.emit, 'log', text)
    
gobject.type_register(LogServerClass)
LogServer = LogServerClass()
LogServerClass = None
