import time
import logging
import re
import warnings
import gobject

warnings.simplefilter("ignore")

from zope.interface import implements
from bcm.device.interfaces import IGoniometer
from bcm.protocol.ca import PV
from bcm.device.motor import VMEMotor
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

# Goniometer state constants
(GONIO_IDLE, GONIO_ACTIVE) = range(2)

GONIO_MODE_INVALID = -1
GONIO_MODE_MOUNT = 0
GONIO_MODE_CENTER = 1
GONIO_MODE_BEAM = 2
GONIO_MODE_COLLECT = 4

_MODE_MAP = { 
             'MOUNTING':GONIO_MODE_MOUNT, 
             'CENTERING': GONIO_MODE_CENTER,
             'COLLECT': GONIO_MODE_COLLECT,
             'BEAM': GONIO_MODE_BEAM,
}
_MODE_MAP_REV = { 
             GONIO_MODE_MOUNT: 'MOUNTING', 
             GONIO_MODE_CENTER: 'CENTERING',
             GONIO_MODE_COLLECT: 'COLLECT',
             GONIO_MODE_BEAM: 'BEAM',
}

_STATE_PATTERNS = {
    GONIO_MODE_MOUNT: re.compile('^Waiting sample transfer\s.+$'),
    GONIO_MODE_CENTER: re.compile('^Click one of the Centring\s.+$'),
    GONIO_MODE_COLLECT: re.compile('^Waiting for scan\s.+$'),
    GONIO_MODE_BEAM: re.compile('^Drag the beam mark\s.+$'),

}
class GoniometerError(Exception):

    """Base class for errors in the goniometer module."""


class GoniometerBase(gobject.GObject):
    """Base class for goniometer."""
    implements(IGoniometer)

    # Motor signals
    __gsignals__ =  { 
        "mode": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        }  

    def __init__(self, name):
        gobject.GObject.__init__(self)
        self.name = name
        self.mode = -1
    
    def __repr__(self):
        s = "<%s:'%s', mode:%s>" % (self.__class__.__name__,
                                               self.name, self.mode)
        return s

    def _set_and_notify_mode(self, mode):
        if mode != self.mode:
            self.mode = mode
            _mode_str = _MODE_MAP_REV.get(mode, 'UNKNOWN')
            gobject.idle_add(self.emit, 'mode', _mode_str)
            _logger.info( "(%s) mode changed to `%s`" % (self.name, _mode_str))

    
class Goniometer(GoniometerBase):
    def __init__(self, name):
        GoniometerBase.__init__(self, name)
        pv_root = name.split(':')[0]
        # initialize process variables
        self._scan_cmd = PV("%s:scanFrame.PROC" % pv_root, monitor=False)
        self._state = PV("%s:scanFrame:status" % pv_root)
        self._shutter_state = PV("%s:outp1:fbk" % pv_root)
        
        self.omega = VMEMotor('%s:deg' % name)
                
        #parameters
        self._settings = {
            'time' : PV("%s:expTime" % pv_root, monitor=False),
            'delta' : PV("%s:deltaOmega" % pv_root, monitor=False),
            'angle': PV("%s:openSHPos" % pv_root, monitor=False),
        }
        
                
    def configure(self, **kwargs):
        for key in kwargs.keys():
            self._settings[key].put(kwargs[key])
    
    def set_mode(self, mode, wait=False):
        self._set_and_notify_mode(mode)
    
    def scan(self, wait=True):
        self._scan_cmd.set('\x01')
        if wait:
            self.wait(start=True, stop=True)

    def get_state(self):
        return self._state.get() != 0   
                        
    def wait(self, start=True, stop=True, poll=0.05, timeout=20):
        if (start):
            time_left = 2
            while not self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
        if (stop):
            time_left = timeout
            while self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll

    def stop(self):
        pass    # FIXME: We need a proper way to stop goniometer scan


class MD2Goniometer(GoniometerBase):

    def __init__(self, name, omega_motor):
        GoniometerBase.__init__(self, name)
        pv_root = name
        # initialize process variables
        self._scan_cmd = PV("%s:S:StartScan" % pv_root, monitor=False)
        self._abort_cmd = PV("%s:S:AbortScan" % pv_root, monitor=False)
        self._state = PV("%s:G:MachAppState" % pv_root)
        self._mode_cmd = PV("%s:S:MDPhasePosition" % pv_root, monitor=False)
        self._mode_fbk = PV("%s:G:MDPhasePosition" % pv_root)
        self._cntr_cmd_start = PV("%s:S:StartManSampleCent" % pv_root)
        self._cntr_cmd_stop = PV("%s:S:ManCentCmpltd" % pv_root)
        self._enabled_state = PV("%s:enabled" % pv_root)
        self._shutter_state = PV("%s:G:ShutterIsOpen" % pv_root)
        self._log = PV('%s:G:StatusMsg' % pv_root)
        
        self.omega = omega_motor
                
        #parameters
        self._settings = {
            'time' : PV("%s:S:ScanExposureTime" % pv_root, monitor=False),
            'delta' : PV("%s:S:ScanRange" % pv_root, monitor=False),
            'angle': PV("%s:S:ScanStartAngle" % pv_root, monitor=False),
            'passes': PV("%s:S:ScanNumOfPasses" % pv_root, monitor=False),
        }
        
        #signal handlers
        self._mode_fbk.connect('changed', self.on_mode_changed)
        self._log.connect('changed', self.on_log_status)
        
                       
    def configure(self, **kwargs):
        for key in kwargs.keys():
            self._settings[key].put(kwargs[key])
    
    def set_mode(self, mode, wait=False):
        if isinstance(mode, int):
            _mode_val = mode
        elif isinstance(mode, str):
            _mode_val = _MODE_MAP.get(mode, 0)
            
        if _mode_val == 1:
            self._cntr_cmd_start.set(1)
            self._cntr_cmd_start.set(0)
        elif _mode_val == 4:
            self._cntr_cmd_stop.set(1)
            self._cntr_cmd_stop.set(0)
        self._mode_cmd.set(_mode_val)
        
        if wait:
            timeout = 30
            while self.mode != _mode_val  and timeout > 0:
                time.sleep(0.05)
                timeout -= 0.05
            if timeout <= 0:
                _logger.warn('Timed out waiting for requested mode `%s`' % mode)
             

    def on_mode_changed(self, pv, val):
        #self._gonio_mode = -2*(val // 6) + val%5
        #_logger.debug('MD2 Current Mode: %d' % self._gonio_mode )
        pass
    
    def on_log_status(self, pv, txt):
        for k,v in _STATE_PATTERNS.items():
            if v.match(txt):
                self._set_and_notify_mode(k)
            
    def scan(self, wait=True):
        self._scan_cmd.set(1)
        self._scan_cmd.set(0)
        if wait:
            self.wait(start=True, stop=True)

    def get_state(self):
        return self._state.get() != 3  
                        
    def wait(self, start=True, stop=True, poll=0.01, timeout=20):
        if (start):
            time_left = 2
            while not self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
        if (stop):
            time_left = timeout
            while self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll

    def stop(self):
        self._abort_cmd.set(1)
        self._abort_cmd.set(0)

