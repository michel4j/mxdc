import threading
import time
import importlib

from gi.repository import GObject
from twisted.python.components import globalRegistry
from zope.interface import Interface, Attribute
from zope.interface import implements

from mxdc.beamlines.interfaces import IBeamline
from mxdc.devices.base import BaseDevice
from mxdc.com import ca
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


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


class Script(BaseDevice):
    implements(IScript)
    __gsignals__ = {
        'done': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'enabled': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        'error': (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    description = 'A Script'
    progress = None

    def __init__(self):
        super(Script, self).__init__()
        self.name = self.__class__.__name__
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.enable()
        self._output = None

    def __repr__(self):
        return '<Script:%s>' % self.name

    def start(self, *args, **kwargs):
        if self.is_enabled() and not self.is_busy():
            worker_thread = threading.Thread(target=self._thread_run, args=args, kwargs=kwargs)
            worker_thread.setDaemon(True)
            worker_thread.setName(self.name)
            self._output = None
            worker_thread.start()
        else:
            logger.warning('Script "%s" disabled or busy.' % (self,))

    def _thread_run(self, *args, **kwargs):
        with self.beamline.lock:
            ca.threads_init()
            self.set_state(busy=True, message=self.description)
            self._output = self.run(*args, **kwargs)
            logger.info('Script `%s` terminated successfully' % (self.name))
            self.set_state(done=self._output, busy=False, message='Done.')
            self.on_complete(*args, **kwargs)

    def run(self, *args, **kwargs):
        raise ScriptError('`run()` not implemented!')

    def enable(self):
        self.set_state(enabled=True)
        logger.debug('Script "%s" enabled.' % (self,))

    def disable(self):
        self.set_state(enabled=False)
        logger.debug('Script "%s" disabled.' % (self,))

    def on_complete(self, *args, **kwargs):
        pass

    def wait(self):
        while self.is_busy():
            time.sleep(0.05)


_SCRIPTS = {}


def get_scripts():
    importlib.import_module('mxdc.scripts')
    for script in Script.__subclasses__():
        name = script.__name__
        if not name in _SCRIPTS:
            _SCRIPTS[name] = script()
    return _SCRIPTS


__all__ = ['Script', 'get_scripts', 'IScript', 'ScriptError']
