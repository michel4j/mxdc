'''
Created on Jun 1, 2010

@author: michel
'''
import time
import math
import logging
import gobject
from zope.interface import implements
from bcm.device.interfaces import IDiagnostic
from bcm.utils.log import get_module_logger
from twisted.python.components import globalRegistry


# setup module logger with a default do-nothing handler
_logger = get_module_logger('diagnostics')

(DIAG_STATUS_GOOD, DIAG_STATUS_WARN, DIAG_STATUS_BAD, DIAG_STATUS_UNKNOWN) = range(4)
DIAG_STATUS_STRINGS = ['OK', 'WARNING', 'ERROR', 'UNKNOWN']

class DiagnosticBase(gobject.GObject):

    """Base class for diagnostics."""
    implements(IDiagnostic)

    # Motor signals
    __gsignals__ =  { 
        "status": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        } 

    def __init__(self, descr):
        gobject.GObject.__init__(self)
        self.description = descr
        self._status = {'status': DIAG_STATUS_UNKNOWN, 'message':''}
        globalRegistry.subscribe([], IDiagnostic, self)
    
    def __repr__(self):
        s = "<%s:'%s', status:%s>" % (self.__class__.__name__,
                                      self.description,
                                      DIAG_STATUS_STRINGS[self._status['status']])
        return s
    
    def _signal_status(self, status, msg):
        data = {'status': status, 'message': msg}
        if self._status['status'] == status and self._status['message'] == msg:
            return
        gobject.idle_add(self.emit,'status', data)
        if status == DIAG_STATUS_GOOD:
            _logger.debug("%s OK." % self.description )
        elif status == DIAG_STATUS_WARN:
            _logger.warning("%s: %s." % (self.description, msg))
        elif status == DIAG_STATUS_BAD:
            _logger.warning("%s: %s." % (self.description, msg))
        else:
            _logger.debug("%s status changed." % self.description )
        self._status = data
    
    def get_status(self):
        return self._status
            

class ShutterStateDiag(DiagnosticBase):
    
    def __init__(self, device, descr=None):
        if descr is None:
            descr = device.name
        DiagnosticBase.__init__(self, descr)
        self.device = device
        self.device.connect('changed', self._on_change)
        self.device.connect('active', self._on_active)

    def _on_change(self, obj, val):
        if self.device.active_state:          
            if val:
                _diag = (DIAG_STATUS_GOOD, 'Open!')
            else:
                _diag = (DIAG_STATUS_WARN,'Not Open!')
        else:
            _diag = (DIAG_STATUS_BAD,'Not connected!')
        self._signal_status(*_diag)

    def _on_active(self, obj, val):
        if val:          
            if self.device.changed_state:
                _diag = (DIAG_STATUS_BAD,'Open!')
            else:
                _diag = (DIAG_STATUS_WARN,'Not Open!')
        else:
            _diag = (DIAG_STATUS_BAD,'Not connected!')
        self._signal_status(*_diag)



class DeviceDiag(DiagnosticBase):
    
    def __init__(self, device, descr=None):
        if descr is None:
            descr = device.name
        DiagnosticBase.__init__(self, descr)
        self.device = device
        self.device.connect('active', self._on_active)
        self.device.connect('health', self._on_health)
        
    def _on_active(self, obj, val):
        if val:
            _diag = (DIAG_STATUS_GOOD,'OK!')
        else:
            _diag = (DIAG_STATUS_BAD,'Not connected!')            
        self._signal_status(*_diag)

    def _on_health(self, obj, hlth):
        st, descr = hlth
        if self.device.active_state:          
            if st == 0:
                _diag = (DIAG_STATUS_GOOD, 'OK!')
            else:
                _diag = (DIAG_STATUS_WARN, descr)
        else:
            _diag = (DIAG_STATUS_BAD, 'Not connected!')
        self._signal_status(*_diag)
