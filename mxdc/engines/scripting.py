import importlib
import time

from zope.interface import Interface, Attribute, implementer

from mxdc import Signal, Engine
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
class Script(Engine):

    class Signals:
        enabled = Signal('enabled', arg_types=(bool,))
        message = Signal('message', arg_types=(str,))

    description = 'A Script'
    progress = None

    def __init__(self):
        super().__init__()
        self.name = self.__class__.__name__
        self.enable()
        self.output = None

    def __repr__(self):
        return ':{}()'.format(self.name)

    def is_enabled(self):
        return self.get_state("enabled")

    def __engine__(self, *args, **kwargs):
        if self.is_enabled():
            ca.threads_init()
            with self.beamline.lock:
                self.set_state(busy=True, message=self.description)
                self.output = self.run()
                logger.info('Script `{}` terminated successfully'.format(self.name))
                self.set_state(done=self.output, busy=False, message='Done.')
                self.on_complete(*args, **kwargs)
        else:
            logger.warning('Script "{}" disabled or busy.'.format(self, ))

    def run(self, *args, **kwargs):
        raise ScriptError('`script()` not implemented!')

    def enable(self):
        self.set_state(enabled=True)

    def disable(self):
        self.set_state(enabled=False)

    def on_complete(self, *args, **kwargs):
        pass

    def wait(self):
        while self.is_busy():
            time.sleep(0.05)


_SCRIPTS = {}


def get_scripts():
    importlib.import_module('mxdc.engines.scripts')
    for script in Script.__subclasses__():
        name = script.__name__
        if not name in _SCRIPTS:
            _SCRIPTS[name] = script()
    return _SCRIPTS


__all__ = ['Script', 'get_scripts', 'IScript', 'ScriptError']
