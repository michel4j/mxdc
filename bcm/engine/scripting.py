import sys
import time
import threading
import gobject
from bcm.protocol import ca

class ScriptError(Exception):
    """Exceptioins for Scripting Engine."""
    
                
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
            worker_thread = threading.Thread(target=self._run)
            worker_thread.setDaemon(True)
            worker_thread.start()
        else:
            self._run()
                 
    def _run(self):
        ca.threads_init()
#        try:
        if self.func:
            self.func(*self.args, **self.kw)
        gobject.idle_add(self.emit, "done")
#        except:
#            raise Error("Script failed!" )
#            gobject.idle_add(self.emit, "error")
        
gobject.type_register(Script)
