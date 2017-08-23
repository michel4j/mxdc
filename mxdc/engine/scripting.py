
import time
import threading
from collections import OrderedDict
from gi.repository import GObject

from zope.interface import Interface, Attribute
from zope.interface import implements
from twisted.python.components import globalRegistry
from mxdc.com import ca
from mxdc.interface.beamlines import IBeamline
from mxdc.utils.log import get_module_logger


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class IScript(Interface):
    description = Attribute("""Short description of the script.""")
    progress = Attribute("""Progress Level of Script.""")

    def start(self):
        """Start the script in asynchronous mode. It returns immediately."""

    def run(self):
        """Start the script in synchronous mode. It blocks.
        This is where the functionality of the script is defined.
        """

    def is_active(self):
        """Returns true if the script is currently running."""

    def wait(self):
        """Wait for script to finish running."""


class ScriptError(Exception):
    """Exceptioins for Scripting Engine."""


class Script(GObject.GObject):
    implements(IScript)
    __gsignals__ = {}
    __gsignals__['done'] = (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT,))
    __gsignals__['busy'] = (GObject.SignalFlags.RUN_LAST, None, (bool,))
    __gsignals__['message'] = (GObject.SignalFlags.RUN_LAST, None, (str,))
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
        if self._enabled and not self._active:
            self._active = True
            worker_thread = threading.Thread(target=self._thread_run, args=args, kwargs=kwargs)
            worker_thread.setDaemon(True)
            self.output = None
            worker_thread.start()
        else:
            _logger.warning('Script "%s" disabled or busy.' % (self,))
        
    def _thread_run(self, *args, **kwargs):

        try:
            ca.threads_init()
            GObject.idle_add(self.emit, "busy", True)
            GObject.idle_add(self.emit, "message", self.description)
            self.output = self.run(*args, **kwargs)
            _logger.info('Script `%s` terminated successfully' % (self.name) )
        finally:
            GObject.idle_add(self.emit, "done", self.output)
            GObject.idle_add(self.emit, "busy", False)
            GObject.idle_add(self.emit, "message", 'Done.')
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

    def is_busy(self):
        return self.is_active()

    def is_enabled(self):
        return self._enabled

_SCRIPTS = {}

def get_scripts():
    from mxdc import scripts
    _logger.debug('Available Scripts: {}'.format(scripts.__all__))
    for script in Script.__subclasses__():
        name = script.__name__
        if not name in _SCRIPTS:
            _SCRIPTS[name] = script()
    return _SCRIPTS

__all__ = ['Script', 'get_scripts', 'IScript', 'ScriptError']