import threading
import time
import importlib

from gi.repository import GObject, GLib
from mxdc import Registry, Signal, BaseEngine
from zope.interface import Interface, Attribute, implementer

from mxdc.beamlines.interfaces import IBeamline
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
    def wait(self):
        """Wait for script to finish running."""


class ScriptError(Exception):
    """Exceptioins for Scripting Engine."""


@implementer(IScript)
class Script(BaseEngine):

    # Signals:
    enabled = Signal('enabled', arg_types=(bool,))

    description = 'A Script'
    progress = None

    def __init__(self):
        super().__init__()
        self.name = self.__class__.__name__
        self.enable()
        self._output = None

    def __repr__(self):
        return '<Script:%s>' % self.name

    def is_enabled(self):
        return self.get_state("enabled")

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
        raise ScriptError('`script()` not implemented!')

    def enable(self):
        self.set_state(enabled=True)
        logger.debug('Script "{}" enabled.'.format(self.__class__.__name__, ))

    def disable(self):
        self.set_state(enabled=False)
        logger.debug('Script "{}" disabled.'.format(self.__class__.__name__, ))

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
