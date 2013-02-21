import time
import re
import warnings
import gobject

warnings.simplefilter("ignore")
from datetime import datetime
from zope.interface import implements
from bcm.device.interfaces import IGoniometer
from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from bcm.protocol import ca
from bcm.device.motor import PseudoMotor
from bcm.device.misc import Positioner, BasicShutter
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
             'SCANNING': GONIO_MODE_COLLECT,
             'BEAM': GONIO_MODE_BEAM,
}
_MODE_MAP_REV = {
             GONIO_MODE_INIT: ['INIT'],
             GONIO_MODE_ALIGN: ['ALIGNMENT'],
             GONIO_MODE_MOUNT: ['MOUNTING'], 
             GONIO_MODE_CENTER: ['CENTERING'],
             GONIO_MODE_COLLECT: ['COLLECT','SCANNING'],
             GONIO_MODE_BEAM: ['BEAM'],
             GONIO_MODE_UNKNOWN: ['MOVING'],
}

_STATE_PATTERNS = {
    'MOUNTING': re.compile('^Waiting sample transfer\s.+$'),
    'CENTERING': re.compile('^Click one of the Centring\s.+$'),
    'COLLECT': re.compile('^Waiting for scan\s.+$'),
    'BEAM': re.compile('^Drag the beam mark\s.+$'),

}

class BackLight(BasicShutter):
    """A specialized in-out actuator for pneumatic OAV backlight at the CLS."""
    def __init__(self, name):
        """
        Args:
            -`name` (str): Root PV name of EPICS record.
        """
        open_name = "%s:opr:open" % name
        close_name = "%s:opr:close" % name
        state_name = "%s:out" % name
        BasicShutter.__init__(self, open_name, close_name, state_name)
        self._messages = ['Moving in', 'Moving out']
        self._name = 'Backlight'

    def _signal_change(self, obj, value):
        if value == 1:
            self.set_state(changed=False)
        else:
            self.set_state(changed=True)


class GoniometerBase(BaseDevice):
    """Base class for goniometer."""
    implements(IGoniometer)
    __gsignals__ =  { 
        "mode": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        } 

    def __init__(self, name):
        BaseDevice.__init__(self)
        self.name = name
        self.mode = -1
                
    def _set_and_notify_mode(self, mode_str):
        mode = _MODE_MAP.get(mode_str, 6)
        #if mode_str in ['MOVING', 'UNKNOWN']:
        #    return 
        if mode not in [self.mode, 'MOVING', 'UNKNOWN']:
            _logger.info( "Mode changed to `%s`" % (mode_str))
        gobject.idle_add(self.emit, 'mode', mode_str)
        self.mode = mode   

    def wait(self, start=True, stop=True, poll=0.05, timeout=20):
        """Wait for the goniometer busy state to change. 
        
        Kwargs:
            - `start` (bool): Wait for the goniometer to become busy.
            - `stop` (bool): Wait for the goniometer to become idle.
            - `poll` (float): time in seconds to wait between checks.
            - `timeout` (float): Maximum time to wait for.                  
        """
        if (start):
            time_left = timeout
            _logger.debug('Waiting for goniometer to start moving')
            while not self.is_busy() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
            if time_left <= 0:
                _logger.warn('Timed out waiting for goniometer to start moving')
        if (stop):
            time_left = timeout
            _logger.debug('Waiting for goniometer to stop')
            while self.is_busy() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
            if time_left <= 0:
                _logger.warn('Timed out waiting for goniometer to stop')
    
    def stop(self):
        """Stop and abort the current scan if any."""
        pass
    
class Goniometer(GoniometerBase):
    """EPICS based Parker-type Goniometer at the CLS 08ID-1."""
    def __init__(self, name, blname, mntname, minibeam):
        """
        Args:
            - `name` (str): PV name of goniometer EPICS record.
            - `blname` (str): PV name for Backlight PV.
            - `mntname` (str): PV root name for mount status mode.
            - `minibeam` (str): PV name for minibeam motor. 
        """
        GoniometerBase.__init__(self, name)
        self.name = 'Goniometer'
        pv_root = name.split(':')[0]
        # initialize process variables
        self._scan_cmd = self.add_pv("%s:scanFrame.PROC" % pv_root, monitor=False)
        self._state = self.add_pv("%s:scanFrame:status" % pv_root)
        self._state.connect('changed', self._on_busy)
        self._shutter_state = self.add_pv("%s:outp1:fbk" % pv_root)
        self._bl_position = BackLight(blname)

        self._goto_mount_cmd = self.add_pv("%s:mnt:gotoMount" % mntname)
        self._goto_mount_state = self.add_pv("%s:mntpos:moving" % mntname)
        self._gonio_state = self.add_pv("%s:goniPos:mntEn" % mntname)
        self._table_state = self.add_pv("%s:tbl:mntEn" % mntname)

        self.minibeam = PseudoMotor(minibeam)
        self.add_devices(self._bl_position, self.minibeam)

        self.minibeam.connect('changed', lambda x,y: self._check_gonio_pos())
        self.minibeam.connect('busy', lambda x,y: self._check_gonio_pos())
        self._bl_position.connect('changed', lambda x,y: self._check_gonio_pos())
        self._gonio_state.connect('changed', lambda x,y: self._check_gonio_pos())
        self._table_state.connect('changed', lambda x,y: self._check_gonio_pos())
        
        #parameters
        self._settings = {
            'time' : self.add_pv("%s:expTime" % pv_root, monitor=False),
            'delta' : self.add_pv("%s:deltaOmega" % pv_root, monitor=False),
            'angle': self.add_pv("%s:openSHPos" % pv_root, monitor=False),
        }
        self._requested_mode = None
        gobject.idle_add(self.emit, 'mode', 'MOVING')
    
    def _check_gonio_pos(self):
        bl = globalRegistry.lookup([], IBeamline)
        out_position = bl.config['misc']['aperture_out_position']
        
        if self._bl_position.changed_state:
            self._set_and_notify_mode("CENTERING")
        elif (self._gonio_state.get() + self._table_state.get()) == 2:
            self._set_and_notify_mode("MOUNTING")
        elif self.minibeam.get_position() < out_position and self._goto_mount_state.get() != 1:
            if self._requested_mode in ['BEAM', 'COLLECT', 'SCANNING']:
                self._set_and_notify_mode(self._requested_mode)
            else:
                self._set_and_notify_mode("UNKNOWN")
        elif self._goto_mount_state.get() == 1:
            self._set_and_notify_mode("MOVING")
        else:
            self._set_and_notify_mode("UNKNOWN")
           
            
    def _on_busy(self, obj, st):
        if st == 0:
            self.set_state(busy=False)
        else:
            self.set_state(busy=True)
                   
    def configure(self, **kwargs):
        """Configure the goniometer to perform an oscillation scan.
        
        Kwargs:
            `time` (float): Exposure time in seconds
            `delta` (float): Delta oscillation range in deg
            `angle` (float): Starting angle of oscillation in deg
        """ 
        for key in kwargs.keys():
            self._settings[key].put(kwargs[key])
    
    def set_mode(self, mode, wait=False):
        """Set the mode of the goniometer environment.
        
        Args:
            - `mode` (str) one of:
                - "CENTERING" : Prepare for centering 
                - "MOUNTING" : Prepare for mounting/dismounting samples
                - "COLLECT" : Prepare for data collection
                - "BEAM" : Inspect the beam
                - "SCANNING" : Prepare for scanning and fluorescence measurements
        
        Kwargs:
            - `wait` (bool): if True, block until the mode is completely changed.
        """
        self._requested_mode = mode
        bl = globalRegistry.lookup([], IBeamline)
        if bl is None:
            _logger.error('Beamline is not available.')
            return 
        
        if mode == 'CENTERING':
            self._bl_position.open()
            in_position = bl.config['misc']['aperture_in_position']
            self.minibeam.move_to(in_position, wait=False)
            #put up backlight
        elif mode in ['MOUNTING']:
            #out_position = bl.config['misc']['aperture_out_position']
            #self.minibeam.move_to(out_position, wait=False)
            self._bl_position.close()
            self._goto_mount_cmd.put(1)

        elif mode in ['COLLECT', 'BEAM', 'SCANNING']:
            self._bl_position.close()
            in_position = bl.config['misc']['aperture_in_position']
            self.minibeam.move_to(in_position, wait=True)

                    
        #self._set_and_notify_mode(mode)
        self._check_gonio_pos()
        if wait:
            timeout = 30
            while mode not in _MODE_MAP_REV.get(self.mode) and timeout > 0:
                time.sleep(0.05)
                timeout -= 0.05
                self._check_gonio_pos()
            if timeout <= 0:
                _logger.warn('Timed out waiting for requested mode `%s`' % mode)

    
    def scan(self, wait=True):
        """Perform an oscillation scan according to the currently set parameters
        
        Kwargs:
            - `wait` (bool): if True, wait until the scan is complete otherwise run
            asynchronously.
        """
        self._scan_cmd.set('\x01')
        if wait:
            t = 180
            self.wait(start=True, stop=True, timeout=t)
                        

class MD2Goniometer(GoniometerBase):
    """EPICS based MD2-type Goniometer at the CLS 08B1-1."""

    def __init__(self, name):
        """
        Args:
            - `name` (str): Root PV name of the goniometer EPICS record.
        """
        GoniometerBase.__init__(self, name)
        self.name = 'MD2 Goniometer'
        pv_root = name
        
        # initialize process variables
        self._scan_cmd = self.add_pv("%s:S:StartScan" % pv_root, monitor=False)
        self._abort_cmd = self.add_pv("%s:S:AbortScan" % pv_root, monitor=False)
        self._state = self.add_pv("%s:G:MachAppState" % pv_root)
        self._mode_cmd = self.add_pv("%s:S:MDPhasePosition:asyn.AOUT" % pv_root, monitor=False)
        self._dev_cnct = self.add_pv("%s:G:MachAppState:asyn.CNCT" % pv_root)
        self._dev_enabled = self.add_pv("%s:usrEnable" % pv_root)
        
        # FIXME: Does not work reliably yet
        self._mode_mounting_cmd = self.add_pv("%s:S:transfer:phase.PROC" % pv_root, monitor=False)
        self._mode_centering_cmd = self.add_pv("%s:S:centering:phase.PROC" % pv_root, monitor=False)
        self._mode_collect_cmd = self.add_pv("%s:S:scan:phase.PROC" % pv_root, monitor=False)
        self._mode_beam_cmd = self.add_pv("%s:S:locate:phase.PROC" % pv_root, monitor=False)

        self._mode_fbk = self.add_pv("%s:G:MDPhasePosition" % pv_root)
        self._cntr_cmd_start = self.add_pv("%s:S:StartManSampleCent" % pv_root)
        self._cntr_cmd_complete = self.add_pv("%s:S:ManCentCmpltd" % pv_root)
        self._enabled_state = self.add_pv("%s:enabled" % pv_root)
        self._shutter_state = self.add_pv("%s:G:ShutterIsOpen" % pv_root)
        self._log = self.add_pv('%s:G:StatusMsg' % pv_root)
        
                
        #parameters
        self._settings = {
            'time' : self.add_pv("%s:S:ScanExposureTime" % pv_root, monitor=False),
            'delta' : self.add_pv("%s:S:ScanRange" % pv_root, monitor=False),
            'angle': self.add_pv("%s:S:ScanStartAngle" % pv_root, monitor=False),
            'passes': self.add_pv("%s:S:ScanNumOfPasses" % pv_root, monitor=False),
        }
        
        #signal handlers
        self._mode_fbk.connect('changed', self._on_mode_changed)
        self._state.connect('changed', self._on_state_changed)
        self._dev_cnct.connect('changed', self._on_cnct_changed)
        self._dev_enabled.connect('changed', self._on_enabled_changed)
        
        #devices to reset during mount scan mode
        self._tbl_x = Positioner("%s:S:PhiTblXAxPos" % pv_root, "%s:G:PhiTblXAxPos" % pv_root)
        self._tbl_y = Positioner("%s:S:PhiTblYAxPos" % pv_root, "%s:G:PhiTblYAxPos" % pv_root)
        self._tbl_z = Positioner("%s:S:PhiTblZAxPos" % pv_root, "%s:G:PhiTblZAxPos" % pv_root)
        self._cnt_x = Positioner("%s:S:CentTblXAxPos" % pv_root, "%s:G:CentTblXAxPos" % pv_root)
        self._cnt_y = Positioner("%s:S:CentTblYAxPos" % pv_root, "%s:G:CentTblYAxPos" % pv_root)
        self._minibeam = Positioner("%s:S:CapPredefPosn" % pv_root, "%s:G:CapPredefPosn" % pv_root)
        self.add_devices(self._tbl_x, self._tbl_y, self._tbl_z, self._cnt_x, self._cnt_y, self._minibeam)
        
        # device set points for mount mode
        self._mount_setpoints = {
            #self._cnt_x: 0.0,
            #self._cnt_y: 0.0,
        }                    

    def configure(self, **kwargs):
        """Configure the goniometer to perform an oscillation scan.
        
        Kwargs:
            - `time` (float): Exposure time in seconds
            - `delta` (float): Delta oscillation range in deg
            - `angle` (float): Starting angle of oscillation in deg
        """ 
        for key in kwargs.keys():
            self._settings[key].put(kwargs[key])
    
    def set_mode(self, mode, wait=False):
        """Set the mode of the goniometer environment.
        
        Args:
            - `mode` (str) one of:
                - "CENTERING" : Prepare for centering 
                - "MOUNTING" : Prepare for mounting/dismounting samples
                - "COLLECT" : Prepare for data collection
                - "BEAM" : Inspect the beam
                - "SCANNING" : Prepare for scanning and fluorescence measurements
        
        Kwargs:
            - `wait` (bool): if True, block until the mode is completely changed.
        """

        #cmd_template = "SET_CLSMDPhasePosition=%d"
        mode = mode.strip().upper()
        if mode == 'CENTERING':
            self._cntr_cmd_start.toggle(1,0)      
            #self._mode_cmd.put(cmd_template % (2,))
            #self._mode_centering_cmd.put('\x01')
        elif mode == 'MOUNTING':
            self._mode_mounting_cmd.put(1)
            #self._mode_cmd.put(cmd_template % (1,))
            #self._mode_mounting_cmd.put('\x01')
        elif mode in ['COLLECT', 'SCANNING']:
            self._cntr_cmd_complete.toggle(1,0)
            self._mode_collect_cmd.put(1)
            #self._mode_cmd.put(cmd_template % (5,))
            #self._mode_collect_cmd.put('\x01')
        elif mode == 'BEAM':
            self._mode_beam_cmd.put(1)
            #self._mode_cmd.put(cmd_template % (3,))
            #self._mode_beam_cmd.put('\x01')
                    
        if wait:
            timeout = 30
            #self.wait()
            while mode not in _MODE_MAP_REV.get(self.mode)  and timeout > 0:
                time.sleep(0.01)
                timeout -= 0.01
            if timeout <= 0:
                _logger.warn('Timed out waiting for requested mode `%s`' % mode)
            time.sleep(1.0)
        
        #FIXME: compensate for broken presets in mounting mode
        if mode == 'MOUNTING':
            for dev,val in self._mount_setpoints.items():
                if abs(dev.get() - val) > 0.01:              
                    self.wait() 
                    time.sleep(0.5)
                    dev.set(val) 
        elif mode == 'SCANNING': 
            #self._minibeam.set(2) # may not be needed any more
            pass
        
        
    def _on_mode_changed(self, pv, val):
        mode_str = _MODE_MAP_REV.get(val, ['UNKNOWN'])[0]      
        self._set_and_notify_mode(mode_str)

    def _on_cnct_changed(self, pv, val):
        if val == 0:
            self.set_state(health=(4,'connection', 'Connection to server lost!'))
        else:
            self.set_state(health=(0,'connection'))

    def _on_state_changed(self, obj, st):
        if st in [4,5,6]:
            self.set_state(health=(0, 'faults'), busy=True)
        elif st in [0, 1, 7]:
            msg = self._log.get().split('.')[0]
            self.set_state(health=(2, 'faults', msg), busy=False)
        else:
            self.set_state(busy=False, health=(0, 'faults'))

    def _on_enabled_changed(self, pv, val):
        if val == 0:
            self.set_state(health=(16,'enable', 'Disabled by staff.'))
        else:
            self.set_state(health=(0,'enable'))
            
    
    def _on_log_status(self, pv, txt):
        for k,v in _STATE_PATTERNS.items():
            if v.match(txt):
                self._set_and_notify_mode(k)
                   
    def scan(self, wait=True):
        """Perform an oscillation scan according to the currently set parameters
        
        Kwargs:
            - `wait` (bool): if True, wait until the scan is complete otherwise run
              asynchronously.
        """
        self._scan_cmd.set(1)
        ca.flush()
        self._scan_cmd.set(0)
        if wait:
            self.wait(start=True, stop=True, timeout=180)

    def stop(self):
        """Stop and abort the current scan if any."""
        self._abort_cmd.set(1)
        ca.flush()
        self._abort_cmd.set(0)


class SimGoniometer(GoniometerBase):
    def __init__(self):       
        GoniometerBase.__init__(self, 'Simulated Goniometer')
        gobject.idle_add(self.emit, 'mode', 'INIT')
        self._scanning = False
        self.set_state(active=True, health=(0,''))

                
    def configure(self, **kwargs):
        self._settings = kwargs
        
    def set_mode(self, mode, wait=False):
        if isinstance(mode, int):
            mode = _MODE_MAP_REV.get(mode, ['MOVING'])[0]
        self._set_and_notify_mode(mode)
    
    @async
    def _start_scan(self):
        self._scanning = True
        bl = globalRegistry.lookup([], IBeamline)
        st = time.time()
        _logger.debug('Starting scan at: %s' % datetime.now().isoformat())
        bl.omega.move_to(self._settings['angle'] - 0.05, wait=True)
        old_speed = bl.omega._speed
        bl.omega._set_speed(self._settings['delta']/self._settings['time'])
        bl.omega.move_to(self._settings['angle'] + self._settings['delta'] + 0.05, wait=True)
        bl.omega._set_speed(old_speed)
        time.sleep(max(0, self._settings['time'] - (time.time() - st)))
        _logger.debug('Scan done at: %s' % datetime.now().isoformat())
        self._scanning = False
        
    def scan(self, wait=True):
        self._start_scan()
        if wait:
            self.wait(start=True, stop=True)

    def is_busy(self):
        return self._scanning
                        

    def stop(self):
        self._scanning = False
   

__all__ = ['Goniometer', 'MD2Goniometer', 'SimGoniometer']
