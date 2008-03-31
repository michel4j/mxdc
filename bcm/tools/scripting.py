import sys, time
import threading
import gtk, gobject
from bcm.protocols import ca

class Error(Exception):
    def __init__(self, msg):
        self.message = msg
                
class ScriptThread(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    def __init__(self, func=None, *args, **kw):
        gobject.GObject.__init__(self)
        self.func = func
        self.args = args
        self.kw = kw
    
    def start(self):
        self.worker_thread = threading.Thread(target=self._run)
        self.worker_thread.start()
                 
    def _run(self):
        ca.thread_init()
        try:
            if self.func:
                self.func(*self.args, **self.kw)
            gobject.idle_add(self.emit, "done")
        except:
            raise Error("Script '%s' failed!" % str(self.func).split()[1] )
            gobject.idle_add(self.emit, "error")
        
gobject.type_register(ScriptThread)
