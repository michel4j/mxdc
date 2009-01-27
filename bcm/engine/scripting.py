import sys, time
import threading
import gtk, gobject
from bcm.protocols import ca

class Error(Exception):
    def __init__(self, msg):
        self.message = msg

    def __str__(self):
        return self.message
                
class Script(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    def __init__(self, func=None, *args, **kw):
        gobject.GObject.__init__(self)
        self.func = func
        self.args = args
        self.kw = kw
    
    def start(self, wait=False):
        if not wait:
            self.worker_thread = threading.Thread(target=self._run)
            self.worker_thread.start()
        else:
            self._run()
                 
    def _run(self):
        ca.thread_init()
#        try:
        if self.func:
            self.func(*self.args, **self.kw)
        gobject.idle_add(self.emit, "done")
#        except:
#            raise Error("Script failed!" )
#            gobject.idle_add(self.emit, "error")
        
gobject.type_register(Script)
