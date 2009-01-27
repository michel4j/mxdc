"""Utilities for enabling smooth use of consoles."""

import threading
import gobject
import gtk
from bcm.protocol import ca

class _BasicEventLoop(object):
    def __init__(self):
        self.mainloop = gobject.MainLoop()
        self.thread = None
        
    def _run(self):
        ca.threads_init()
        self.mainloop.run()
        
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run)
            self.thread.setDaemon(True)
            self.thread.start()
    
    def stop(self):
        self.mainloop.quit()
        self.thread = None
        


class _GUIEventLoop(object):
    def __init__(self):
        self.thread = None
        
    def _run(self):
        ca.threads_init()
        gtk.gdk.threads_init()
        gtk.main()
        
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run)
            self.thread.setDaemon(True)
            self.thread.start()
    
    def stop(self):
        gobject.idle_add(gtk.main_quit)
        self.thread = None
        

event_loop = _BasicEventLoop()
gui_event_loop = _GUIEventLoop()

del _BasicEventLoop
del _GUIEventLoop
