import sys
import time
import threading
import gobject
import logging

from zope.interface import Interface, Attribute
from zope.interface import implements, classProvides
from zope.component import globalSiteManager as gsm
from twisted.plugin import IPlugin, getPlugins
from bcm.engine import iengine
from bcm.protocol import ca
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class ScriptError(Exception):
    """Exceptioins for Scripting Engine."""


class Script(gobject.GObject):
    
    classProvides(IPlugin, iengine.IScript)
    __gsignals__ = {}
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    def __init__(self):
        gobject.GObject.__init__(self)
        self.name = self.__class__.__name__
        try:
            self.beamline = gsm.getUtility(IBeamline, 'bcm.beamline')
        except:
            self.beamline = None
            _logger.warning('Beamline will not be available to this script')

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
        _logger.info('Script `%s` terminated successfully' %s (self.name) )
                
    def run(self):
        raise ScriptError('`run()` not implemented!')


def get_scripts():
    scripts = {}
    for script in list(getPlugins(IScript)):
        print script.name, script
    
        
gobject.type_register(Script)
    