import sys
import time
import threading
import gobject

from zope.interface import Interface, Attribute
from zope.interface import implements
from zope.component import globalSiteManager as gsm
from twisted.plugin import IPlugin
from bcm.protocol import ca
from bcm.beamline.interfaces import IBeamline


class ScriptError(Exception):
    """Exceptioins for Scripting Engine."""

class IScript(Interface):
    
    def start():
        """Start the script in asynchronous mode. It returns immediately."""
                 
    def run():
        """Start the script in synchronous mode. It blocks.
        This is where the functionality of the script is defined.
        """

                
class Script(gobject.GObject):
    
    implements(IPlugin, IScript)
    __gsignals__ = {}
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    def __init__(self, *args, **kw):
        gobject.GObject.__init__(self)
        self._args = args
        self._kw = kw
        self.name = self.__class__.__name__
        self.beamline = gsm.getUtility(IBeamline, 'bcm.beamline')

    def __repr__(self):
        return '<Script:%s>' % self.name
    
    def _thread_run(self):
        ca.threads_init()
        self.run()
    
    def start(self):
        worker_thread = threading.Thread(target=self._thread_run)
        worker_thread.setDaemon(True)
        worker_thread.start()
        
    def _thread_run(self):
        ca.threads_init()
        self.run()
        gobject.idle_add(self.emit, "done")
                
    def run(self):
        raise ScriptError('`run()` not implemented!')
        
gobject.type_register(Script)
