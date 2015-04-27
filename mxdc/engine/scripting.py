import sys
import time
import threading
from gi.repository import GObject
import logging

from zope.interface import Interface, Attribute
from zope.interface import implements, classProvides
from twisted.python.components import globalRegistry
from twisted.plugin import IPlugin, getPlugins
from mxdc.com import ca
from mxdc.interface.beamlines import IBeamline
from mxdc.utils.log import get_module_logger
from mxdc import ibcm


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class ScriptError(Exception):
    """Exceptioins for Scripting Engine."""


class Script(GObject.GObject):
    
    implements(IPlugin, ibcm.IScript)
    __gsignals__ = {}
    __gsignals__['done'] = (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT,))
    __gsignals__['started'] = (GObject.SignalFlags.RUN_LAST, None, [])
    __gsignals__['enabled'] = (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_BOOLEAN,))
    __gsignals__['error'] = (GObject.SignalFlags.RUN_LAST, None, [])
    description = 'A Script'
    progress = None
    
    def __init__(self):
        GObject.GObject.__init__(self)
        self.name = self.__class__.__name__
        self._active = False
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
            _logger.warning('No registered beamline found. Beamline will be unavailable "%s"' % (self,))
        self.enable()
        
    def __repr__(self):
        return '<Script:%s>' % self.name
    
    def start(self, *args, **kwargs):
        if self._enabled:
            self._active = True
            worker_thread = threading.Thread(target=self._thread_run, args=args, kwargs=kwargs)
            worker_thread.setDaemon(True)
            self.output = None
            worker_thread.start()
        else:
            _logger.warning('Script "%s" disabled.' % (self,))
        
    def _thread_run(self, *args, **kwargs):
        try:
            ca.threads_init()
            GObject.idle_add(self.emit, "started")
            self.output = self.run(*args, **kwargs)
            _logger.info('Script `%s` terminated successfully' % (self.name) )
        finally:
            GObject.idle_add(self.emit, "done", self.output)
            self.run_after(*args, **kwargs)
            self._active = False
                
    def run(self, *args, **kwargs):
        raise ScriptError('`run()` not implemented!')

    def enable(self):
        self._enabled = True
        _logger.debug('Script "%s" enabled.' % (self,))
        GObject.idle_add(self.emit, "enabled", self._enabled)

    def disable(self):
        self._enabled = False
        _logger.debug('Script "%s" disabled.' % (self,))
        GObject.idle_add(self.emit, "enabled", self._enabled)
        
    def run_after(self, *args, **kwargs):
        pass

    def wait(self):
        while self._active:
            time.sleep(0.05)
    
    def is_active(self):
        return self._active

    def is_enabled(self):
        return self._enabled


def get_scripts():
    import mxdc.scripts
    scripts = {}
    for script in list(getPlugins(ibcm.IScript, mxdc.scripts)):
        scripts[script.name] = script
    return scripts
        
