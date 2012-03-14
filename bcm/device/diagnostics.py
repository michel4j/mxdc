import time
import math
import logging
import gobject
from zope.interface import implements
from bcm.device.interfaces import IDiagnostic
from bcm.utils.log import get_module_logger
from twisted.python.components import globalRegistry
from bcm.device.base import HealthManager

# setup module logger with a default do-nothing handler
_logger = get_module_logger('diagnostics')

(DIAG_STATUS_GOOD, 
 DIAG_STATUS_WARN, 
 DIAG_STATUS_BAD, 
 DIAG_STATUS_UNKNOWN, 
 DIAG_STATUS_DISABLED) = range(5)
DIAG_STATUS_STRINGS = ['OK', 'WARNING', 'ERROR', 'UNKNOWN', 'DISABLED']

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
        self._manager = HealthManager()
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
        
        if self._status['status'] != status and status != DIAG_STATUS_GOOD:
            _logger.warning("%s: %s." % (self.description, msg))

        self._status = data
    
    def get_status(self):
        """Check the state of the diagnostic.
        
        Returns:
            tuple(int, str). The string is a status description while the value 
            of the integer corresponds to one of:
            
                0 - DIAG_STATUS_GOOD
                1 - DIAG_STATUS_WARN
                2 - DIAG_STATUS_BAD
                3 - DIAG_STATUS_UNKNOWN
                4 - DIAG_STATUS_DISABLED
                
        """
        
        return self._status


class DeviceDiag(DiagnosticBase):
    """A diagnostic object for generic devices which emits a warning when the
    device health is not good and an error when it is disconnected or disabled.
    """
    
    def __init__(self, device, descr=None):
        """Args:
            `device` (a class::`device.base.BaseDevice` object) the device to
            monitor.
            
        Kwargs:
            `descr` (str): Short description of the diagnostic.
        """
        if descr is None:
            descr = device.name
        DiagnosticBase.__init__(self, descr)
        self.device = device
        self.device.connect('health', self._on_health)
                
    def _on_health(self, obj, hlth):
        st, descr = hlth
        if st == 0:
            _diag = (DIAG_STATUS_GOOD, 'OK!')
        elif st < 4:
            _diag = (DIAG_STATUS_WARN, descr)
        elif st < 16:
            _diag = (DIAG_STATUS_BAD, descr)
        else:
            _diag = (DIAG_STATUS_DISABLED, descr)    
        self._signal_status(*_diag)


class ServiceDiag(DiagnosticBase):
    """A diagnostic object for generic services which emits an error when it is
    disconnected or disabled.
    """
    
    def __init__(self, service, descr=None):
        """Args:
            `service` (a class::`service.base.BaseService` object) the service to
            monitor.

        Kwargs:
            `descr` (str): Short description of the diagnostic.
        """
        if descr is None:
            descr = service.name
        DiagnosticBase.__init__(self, descr)
        self.service = service
        self.service.connect('active', self._on_active)
        
    def _on_active(self, obj, val):
        if val:
            _diag = (DIAG_STATUS_GOOD,'OK!')
        else:
            _diag = (DIAG_STATUS_BAD,'Service unavailable!')            
        self._signal_status(*_diag)
