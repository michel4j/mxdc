import sys
import time
import threading
import gobject
import logging

from zope.interface import Interface, Attribute
from zope.interface import implements, classProvides
from twisted.python.components import globalRegistry
from twisted.plugin import IPlugin, getPlugins
from bcm.protocol import ca
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger
from bcm import ibcm


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class ScriptError(Exception):
    """Exceptioins for Scripting Engine."""


class Script(gobject.GObject):
    
    implements(IPlugin, ibcm.IScript)
    __gsignals__ = {}
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    description = 'A Script'
    progress = None
    
    def __init__(self):
        gobject.GObject.__init__(self)
        self.name = self.__class__.__name__
        self._active = False
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
            _logger.warning('No registered beamline found. Beamline will be unavailable "%s"' % (self,))

    def __repr__(self):
        return '<Script:%s>' % self.name
        
    def start(self, *args, **kwargs):
        self._active = True
        worker_thread = threading.Thread(target=self._thread_run, args=args, kwargs=kwargs)
        worker_thread.setDaemon(True)
        worker_thread.start()
        
    def _thread_run(self, *args, **kwargs):
        try:
            ca.threads_init()
            self.run(*args, **kwargs)
            _logger.info('Script `%s` terminated successfully' % (self.name) )
        finally:
            gobject.idle_add(self.emit, "done")
            self._active = False
                
    def run(self, *args, **kwargs):
        raise ScriptError('`run()` not implemented!')

    def wait(self):
        while self._active:
            time.sleep(0.05)
    
    def is_active(self):
        return self._active

def get_scripts():
    import bcm.scripts
    scripts = {}
    for script in list(getPlugins(ibcm.IScript, bcm.scripts)):
        scripts[script.name] = script
    return scripts
    
        
gobject.type_register(Script)
    