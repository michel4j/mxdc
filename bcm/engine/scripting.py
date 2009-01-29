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
    
    def __init__(self, script, *args, **kw):
        gobject.GObject.__init__(self)
        self._script = script
        self._args = args
        self._kw = kw
    
    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.start()
                 
    def run(self):
        ca.threads_init()
        self._script(*self._args, **self._kw)
        gobject.idle_add(self.emit, "done")
        
gobject.type_register(Script)
