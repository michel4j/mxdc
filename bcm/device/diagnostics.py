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


class PVInRange1(DiagnosticBase):
    
    def __init__(self, descr, pv, lo, hi):
        DiagnosticBase.__init__(self, descr)
        self._lo = float(lo)
        self._hi = float(hi)
        self._pv = pv
        self._pv.connect('changed', self.on_change)
    
    def on_change(self, obj, val):
        if self._lo < val < self._hi:
            self._signal_status(DIAG_STATUS_GOOD, 'OK!')
        elif val == self._lo:
            self._signal_status(DIAG_STATUS_WARN, 'Near low limit!')
        elif val == self._hi:
            self._signal_status(DIAG_STATUS_WARN, 'Near high limit!')
        elif val < self._lo:
            self._signal_status(DIAG_STATUS_BAD, 'Below range!')
        elif val > self._hi:
            self._signal_status(DIAG_STATUS_BAD, 'Above range!')
            
class CryojetDiag(DiagnosticBase):
    
    def __init__(self, descr, cryojet, lo, hi):
        DiagnosticBase.__init__(self, descr)
        self._lo = float(lo)
        self._hi = float(hi)
        self._dev = cryojet
        self._statedict = {'temp': (DIAG_STATUS_UNKNOWN,''),
                           'level': (DIAG_STATUS_UNKNOWN,''),
                           'nozzle': (DIAG_STATUS_UNKNOWN,'')}
        self._dev.temperature.connect('changed', self.on_temp_change)
        self._dev.nozzle.connect('changed', self.on_noz_change)
        self._dev.level.connect('changed', self.on_lev_change)
    
    def _notify_status(self):
        sts = [v[0] for v in self._statedict.values() ]
        msgs = [v[1] for v in self._statedict.values() if v[1] not in ['OK', '']]
        msg = ', '.join(msgs)
        if len(msg) > 2:
            msg = msg + '!'
        if DIAG_STATUS_BAD in sts:
            self._signal_status(DIAG_STATUS_BAD, msg)
        elif DIAG_STATUS_WARN in sts:
            self._signal_status(DIAG_STATUS_WARN, msg)
        else:
            self._signal_status(DIAG_STATUS_GOOD, 'OK!')
        
        
    def on_temp_change(self, obj, val):
        _diag = self._statedict['temp']
        if val < 105:
            _diag = (DIAG_STATUS_GOOD,'OK')
        elif val < 110:
            _diag = (DIAG_STATUS_WARN,'temperature high')
        elif val > 110:
            _diag = (DIAG_STATUS_WARN,'temperature too high')
        
        if _diag != self._statedict['temp']:
            self._statedict['temp'] = _diag
            self._notify_status()

    def on_lev_change(self, obj, val):
        _diag = self._statedict['level']
        if  val < 150:
            _diag = (DIAG_STATUS_BAD,'Cryogen level too low')
        elif val < 200:
            _diag = (DIAG_STATUS_WARN,'Cryogen level low')
        elif val < 1000:
            _diag = (DIAG_STATUS_GOOD,'OK')
        elif val > 1000:
            print val
            _diag = (DIAG_STATUS_BAD,'Cryogen level invalid')
        
        if _diag != self._statedict['level']:
            self._statedict['level'] = _diag
            self._notify_status()

    def on_noz_change(self, obj, val):
        _diag = self._statedict['nozzle']
        if not val:
            _diag = (DIAG_STATUS_WARN,'Cryojet nozzle retracted')
        else:
            _diag = (DIAG_STATUS_GOOD,'OK')
       
        if _diag != self._statedict['nozzle']:
            self._statedict['nozzle'] = _diag
            self._notify_status()

class OpenShutterDiag1(DiagnosticBase):
    
    def __init__(self, descr, device):
        DiagnosticBase.__init__(self, descr)
        self.device = device
        self.device.connect('changed', self._on_change)

    def _on_change(self, obj, val):
        if not val:
            _diag = (DIAG_STATUS_WARN,'Closed!')
        else:
            _diag = (DIAG_STATUS_GOOD,'OK!')


class OpenShuttersDiag(DiagnosticBase):
    
    def __init__(self, descr, *args):
        DiagnosticBase.__init__(self, descr)
        self.devices = args
        self._statuses = []
        for i, dev in enumerate(self.devices):
            dev.connect('changed', self._on_change, i)
            self._statuses.append((DIAG_STATUS_GOOD,'OK!'))

    def _on_change(self, obj, val, idx):
        _diag = self._statuses[idx]
        if not val:
            _diag = (DIAG_STATUS_BAD,'Shutter closed!')
        else:
            _diag = (DIAG_STATUS_GOOD,'OK!')
            
        if _diag != self._statuses[idx]:
            self._statuses[idx] = _diag
            self._notify_status()
            
    def _notify_status(self):
        sts = [v[0] for v in self._statuses ]
        if DIAG_STATUS_BAD in sts:
            self._signal_status(DIAG_STATUS_BAD, 'Shutter closed!')
        else:
            self._signal_status(DIAG_STATUS_GOOD, 'OK!')


class DeviceConnectedDiag(DiagnosticBase):
    
    def __init__(self, descr, device, on, off):
        DiagnosticBase.__init__(self, descr)
        self.device = device
        self._good = int(on)
        self._bad = int(off)
        self.device.connect('changed', self._on_change)

    def _on_change(self, obj, val):
        if val == self._good:
            _diag = (DIAG_STATUS_GOOD,'OK!')
        elif val == self._bad:
            _diag = (DIAG_STATUS_BAD,'Not connected!')
        else:
            _diag = (DIAG_STATUS_WARN,'Connection state uncertain!')
            
        self._signal_status(*_diag)