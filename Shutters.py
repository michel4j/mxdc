#!/usr/bin/env python

import sys, time
import gtk, gobject
from EPICS import PV
from LogServer import LogServer

class AbstractShutter(gobject.GObject):
    __gsignals__ =  { 
                    "changed": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)  ),
                    }  
    def __init__(self, name=None):
        gobject.GObject.__init__(self)
        self.state = True
        self.name = name

    def open(self):
        self.state = True
        LogServer.log( "%s opened" % self.name)        
            
    def close(self):
        self.state = False
        LogServer.log( "%s closed" % self.name)        

    def is_open(self):
        return self.state

    def get_name(self):
        return self.name

class EpicsShutter(AbstractShutter):
    def __init__(self, name=None):
        AbstractShutter.__init__(self, name)
        self.open_cmd = PV("%s:opr:open" % name)
        self.close_cmd = PV("%s:opr:close" % name)
        self.state = PV("%s:state" % name)
        self.last_state = self.is_open()
        gobject.timeout_add(250, self._queue_check)
    
    def _check_change(self):
        state = self.is_open()
        if state != self.last_state:
            gobject.idle_add(self.emit,'changed', state)
        self.last_state = state
        return False

    def _queue_check(self):
        gobject.idle_add(self._check_change)
        return True

    def is_open(self):
        if self.state.get() == 1:
            return True
        else:
            return False
    
    def open(self):
        self.open_cmd.put(1)
        gobject.idle_add(self.emit,'changed', True)
        LogServer.log( "%s opened" % self.name)
    
    def close(self):
        self.close_cmd.put(1)
        gobject.idle_add(self.emit,'changed', False)
        LogServer.log( "%s closed" % self.name)        
               
FakeShutter = AbstractShutter
        
# Register objects with signals
gobject.type_register(AbstractShutter)
        
    
