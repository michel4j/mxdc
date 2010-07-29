import time
import logging
import re
import warnings
import gobject

warnings.simplefilter("ignore")

from zope.interface import implements
from bcm.device.interfaces import IGoniometer
from bcm.protocol.ca import flush
from bcm.device.motor import VMEMotor, SimMotor
from bcm.utils.log import get_module_logger
from bcm.utils.decorators import async
from bcm.device.base import BaseDevice

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

# Goniometer state constants
(GONIO_IDLE, GONIO_ACTIVE) = range(2)

GONIO_MODE_INVALID = -1
GONIO_MODE_INIT  = 0
GONIO_MODE_MOUNT = 1
GONIO_MODE_CENTER = 2
GONIO_MODE_BEAM = 3
GONIO_MODE_ALIGN = 4
GONIO_MODE_COLLECT = 5
GONIO_MODE_UNKNOWN = 6

_MODE_MAP = {
             'MOUNTING':GONIO_MODE_MOUNT, 
             'CENTERING': GONIO_MODE_CENTER,
             'COLLECT': GONIO_MODE_COLLECT,
             'BEAM': GONIO_MODE_BEAM,
}
_MODE_MAP_REV = {
             GONIO_MODE_INIT: 'INIT',
             GONIO_MODE_ALIGN: 'ALIGNMENT',
             GONIO_MODE_MOUNT: 'MOUNTING', 
             GONIO_MODE_CENTER: 'CENTERING',
             GONIO_MODE_COLLECT: 'COLLECT',
             GONIO_MODE_BEAM: 'BEAM',
             GONIO_MODE_UNKNOWN: 'MOVING',
}

_STATE_PATTERNS = {
    GONIO_MODE_MOUNT: re.compile('^Waiting sample transfer\s.+$'),
    GONIO_MODE_CENTER: re.compile('^Click one of the Centring\s.+$'),
    GONIO_MODE_COLLECT: re.compile('^Waiting for scan\s.+$'),
    GONIO_MODE_BEAM: re.compile('^Drag the beam mark\s.+$'),

}
class GoniometerError(Exception):

    """Base class for errors in the goniometer module."""


class GoniometerBase(BaseDevice):
    """Base class for goniometer."""
    implements(IGoniometer)

    # Motor signals
    __gsignals__ =  { 
        "mode": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        }  

    def __init__(self, name):
        BaseDevice.__init__(self)
        self.name = name
        self.mode = -1
    
    def __repr__(self):
        s = "<%s:'%s', mode:%s>" % (self.__class__.__name__,
                                               self.name, self.mode)
        return s
        
    def get_state(self):
        return True
    
    def _set_and_notify_mode(self, mode):
        if mode != self.mode:
            self.mode = mode
            _mode_str = _MODE_MAP_REV.get(mode, 'MOVING')
            gobject.idle_add(self.emit, 'mode', _mode_str)
            if _mode_str not in ['MOVING', 'UNKNOWN']:
                _logger.info( "(%s) mode changed to `%s`" % (self.name, _mode_str))

    def wait(self, start=True, stop=True, poll=0.05, timeout=20):
        if (start):
            time_left = 2
            _logger.debug('Waiting for goniometer to start scanning')
            while not self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
            if time_left <= 0:
                _logger.warn('Timed out waiting for goniometer to start scanning')
        if (stop):
            time_left = timeout
            _logger.debug('Waiting for goniometer to finish scanning')
            while self.get_state() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
            if time_left <= 0:
                _logger.warn('Timed out waiting for goniometer to stop scanning')
    
    def stop(self):
        pass
    
class Goniometer(GoniometerBase):
    def __init__(self, name):
        GoniometerBase.__init__(self, name)
        pv_root = name.split(':')[0]
        # initialize process variables
        self._scan_cmd = self.add_pv("%s:scanFrame.PROC" % pv_root, monitor=False)
        self._state = self.add_pv("%s:scanFrame:status" % pv_root)
        self._shutter_state = self.add_pv("%s:outp1:fbk" % pv_root)
        
        self.omega = VMEMotor('%s:deg' % name)
                
        #parameters
        self._settings = {
            'time' : self.add_pv("%s:expTime" % pv_root, monitor=False),
            'delta' : self.add_pv("%s:deltaOmega" % pv_root, monitor=False),
            'angle': self.add_pv("%s:openSHPos" % pv_root, monitor=False),
        }
        gobject.idle_add(self.emit, 'mode', 'MOVING')
        
                
    def configure(self, **kwargs):
        for key in kwargs.keys():
            self._settings[key].put(kwargs[key])
    
    def set_mode(self, mode, wait=False):
        if isinstance(mode, int):
            mode = _MODE_MAP_REV.get(mode, 'MOVING')
        self._set_and_notify_mode(_MODE_MAP.get(mode))
    
    def scan(self, wait=True):
        self._scan_cmd.set('\x01')
        if wait:
            t = 180
            self.wait(start=True, stop=True, timeout=t)

    def get_state(self):
        return self._state.get() != 0   
                        

class MD2Goniometer(GoniometerBase):

    def __init__(self, name, omega_motor):
        GoniometerBase.__init__(self, name)
        pv_root = name
        # initialize process variables
        self._scan_cmd = self.add_pv("%s:S:StartScan" % pv_root, monitor=False)
        self._abort_cmd = self.add_pv("%s:S:AbortScan" % pv_root, monitor=False)
        self._state = self.add_pv("%s:G:MachAppState" % pv_root)
        self._mode_cmd = self.add_pv("%s:S:MDPhasePosition:asyn.AOUT" % pv_root, monitor=False)
        
        # Does not work reliably yet
        #self._mode_mounting_cmd = self.add_pv("%s:S:transfer:phase.PROC" % pv_root, monitor=False)
        #self._mode_centering_cmd = self.add_pv("%s:S:centering:phase.PROC" % pv_root, monitor=False)
        #self._mode_collect_cmd = self.add_pv("%s:S:scan:phase.PROC" % pv_root, monitor=False)
        #self._mode_beam_cmd = self.add_pv("%s:S:locate:phase.PROC" % pv_root, monitor=False)

        self._mode_fbk = self.add_pv("%s:G:MDPhasePosition" % pv_root)
        self._cntr_cmd_start = self.add_pv("%s:S:StartManSampleCent" % pv_root)
        self._cntr_cmd_stop = self.add_pv("%s:S:ManCentCmpltd" % pv_root)
        self._enabled_state = self.add_pv("%s:enabled" % pv_root)
        self._shutter_state = self.add_pv("%s:G:ShutterIsOpen" % pv_root)
        self._log = self.add_pv('%s:G:StatusMsg' % pv_root)
        
        self.omega = omega_motor
                
        #parameters
        self._settings = {
            'time' : self.add_pv("%s:S:ScanExposureTime" % pv_root, monitor=False),
            'delta' : self.add_pv("%s:S:ScanRange" % pv_root, monitor=False),
            'angle': self.add_pv("%s:S:ScanStartAngle" % pv_root, monitor=False),
            'passes': self.add_pv("%s:S:ScanNumOfPasses" % pv_root, monitor=False),
        }
        
        #signal handlers
        self._mode_fbk.connect('changed', self.on_mode_changed)
                       
    def configure(self, **kwargs):
        for key in kwargs.keys():
            self._settings[key].put(kwargs[key])
    
    def set_mode(self, mode, wait=False):
        if isinstance(mode, int):
            mode = _MODE_MAP_REV.get(mode, 'MOVING')
        cmd_template = "SET_CLSMDPhasePosition=%d"
        mode = mode.strip().upper()

        if mode == 'CENTERING':
            self._mode_cmd.put(cmd_template % (2,))
            #self._mode_centering_cmd.put('\x01')
        elif mode == 'MOUNTING':
            self._mode_cmd.put(cmd_template % (1,))
            #self._mode_mounting_cmd.put('\x01')
        elif mode == 'COLLECT':
            self._mode_cmd.put(cmd_template % (5,))
            #self._mode_collect_cmd.put('\x01')
        elif mode == 'BEAM':
            self._mode_cmd.put(cmd_template % (3,))
            #self._mode_beam_cmd.put('\x01')
                    
        if wait:
            timeout = 30
            while _MODE_MAP_REV.get(self.mode) != mode  and timeout > 0:
                time.sleep(0.05)
                timeout -= 0.05
            if timeout <= 0:
                _logger.warn('Timed out waiting for requested mode `%s`' % mode)
             

    def on_mode_changed(self, pv, val):
        self._set_and_notify_mode(val)
    
    def on_log_status(self, pv, txt):
        for k,v in _STATE_PATTERNS.items():
            if v.match(txt):
                self._set_and_notify_mode(k)
                   
    def scan(self, wait=True):
        self._scan_cmd.set(1)
        self._scan_cmd.set(0)
        if wait:
            self.wait(start=True, stop=True, timeout=180)
            #while self._shutter_state.get() != 0:
            #    time.sleep(0.05)

    def get_state(self):
        return self._state.get() != 3  
                        

    def stop(self):
        self._abort_cmd.set(1)
        self._abort_cmd.set(0)


class SimGoniometer(GoniometerBase):
    def __init__(self):
        
        GoniometerBase.__init__(self, 'Simulated Goniometer')
        self.omega = SimMotor('Omega Motor', pos=0, units='deg')
        gobject.idle_add(self.emit, 'mode', 'MOVING')
        self._scanning = False
                
    def configure(self, **kwargs):
        self._settings = kwargs
        
    def set_mode(self, mode, wait=False):
        if isinstance(mode, int):
            mode = _MODE_MAP_REV.get(mode, 'MOVING')
        self._set_and_notify_mode(_MODE_MAP.get(mode))
    
    @async
    def _start_scan(self):
        self._scanning = True
        time.sleep(2)
        self._scanning = False
        
    def scan(self, wait=True):
        self._start_scan()
        if wait:
            self.wait(start=True, stop=True)

    def get_state(self):
        return self._scanning
                        

    def stop(self):
        self._scanning = False
   

__all__ = ['Goniometer', 'MD2Goniometer', 'SimGoniometer']
