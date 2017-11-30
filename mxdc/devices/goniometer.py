import re
import time
import warnings
from threading import Lock

from enum import Enum
from gi.repository import GObject

warnings.simplefilter("ignore")
from datetime import datetime
from zope.interface import implements
from interfaces import IGoniometer
from twisted.python.components import globalRegistry
from mxdc.beamlines.interfaces import IBeamline
from mxdc.utils.log import get_module_logger
from mxdc.utils.decorators import async_call
from mxdc.devices.base import BaseDevice

# setup module logger with a default handler
logger = get_module_logger(__name__)

# Goniometer state constants
(GONIO_IDLE, GONIO_ACTIVE) = range(2)

GONIO_MODE_INVALID = -1
GONIO_MODE_INIT = 0
GONIO_MODE_MOUNT = 1
GONIO_MODE_CENTER = 2
GONIO_MODE_BEAM = 3
GONIO_MODE_ALIGN = 4
GONIO_MODE_COLLECT = 5
GONIO_MODE_UNKNOWN = 6

_MODE_MAP = {
    'MOUNTING': GONIO_MODE_MOUNT,
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
    GONIO_MODE_COLLECT: ['COLLECT', 'SCANNING'],
    GONIO_MODE_BEAM: ['BEAM'],
    GONIO_MODE_UNKNOWN: ['MOVING'],
}

_STATE_PATTERNS = {
    'MOUNTING': re.compile('^Waiting sample transfer\s.+$'),
    'CENTERING': re.compile('^Click one of the Centring\s.+$'),
    'COLLECT': re.compile('^Waiting for scan\s.+$'),
    'BEAM': re.compile('^Drag the beam mark\s.+$'),
}


class Goniometer(BaseDevice):
    """Base class for goniometer."""
    implements(IGoniometer)
    __gsignals__ = {
        "mode": (GObject.SIGNAL_RUN_FIRST, None, (object,)),
    }

    class ModeType(Enum):
        INIT, MOUNTING, CENTERING, BEAM, ALIGNMENT, COLLECT, UNKNOWN, SCANNING = range(8)

    mode = GObject.property(type=object)

    def __init__(self, name):
        BaseDevice.__init__(self)
        self.name = name
        self.mode = self.ModeType.INIT
        self.stopped = True
        self.default_timeout = 180
        self.mode_names = {m.name for m in self.ModeType}

    def wait_for_modes(self, modes=set(), timeout=30):
        mode_set = {m if isinstance(m, self.ModeType) else self.ModeType[m] for m in modes}
        time_remaining = timeout
        poll = 0.05
        if mode_set:
            logger.debug('Waiting for {}: {}'.format(self.name, mode_set))
            while time_remaining > 0 and not self.mode in mode_set:
                time_remaining -= poll
                time.sleep(poll)
        else:
            logger.debug('Waiting for {} to stop moving'.format(self.name))
            while time_remaining > 0 and not self.is_busy():
                time_remaining -= poll
                time.sleep(poll)

        if time_remaining <= 0:
            logger.warning('Timed out waiting for {}'.format(self.name))
            return False

        return True

    def set_mode(self, mode, wait=True):
        raise NotImplementedError('Sub-classes must implement "set_mode"')

    def get_mode(self):
        return self.props.mode

    def wait(self, start=True, stop=True, timeout=None):
        """Wait for the goniometer busy state to change.

        Kwargs:
            - `start` (bool): Wait for the goniometer to become busy.
            - `stop` (bool): Wait for the goniometer to become idle.
            - `poll` (float): time in seconds to wait between checks.
            - `timeout` (float): Maximum time to wait for.
        """
        timeout = timeout or self.default_timeout
        poll = 0.05
        self.stopped = False
        if (start):
            time_left = timeout
            logger.debug('Waiting for goniometer to start moving')
            while not self.is_busy() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
                if self.stopped: break
            if time_left <= 0:
                logger.warn('Timed out waiting for goniometer to start moving')
        if (stop):
            time_left = timeout
            logger.debug('Waiting for goniometer to stop')
            while self.is_busy() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
                if self.stopped: break
            if time_left <= 0:
                logger.warn('Timed out waiting for goniometer to stop')

    def stop(self):
        """Stop and abort the current scan if any."""
        self.stopped = True


class ParkerGonio(Goniometer):
    """EPICS based Parker-type Goniometer at the CLS 08ID-1."""

    def __init__(self, root, mode_root, beam_root):
        """
        Args:
            - `name` (str): PV name of goniometer EPICS record.
            - `blname` (str): PV name for Beamline PV.
        """
        Goniometer.__init__(self, 'Parker Goniometer')

        # initialize process variables
        self.scan_cmd = self.add_pv("{}:scanFrame.PROC".format(root))
        self.stop_cmd = self.add_pv("{}:stop".format(root))

        self.scan_fbk = self.add_pv("{}:scanFrame:status".format(root))
        self.busy_fbk = self.add_pv("{}:moving:fbk".format(mode_root))
        self.calibrated_fbk = self.add_pv("{}:calibrated:fbk".format(mode_root))

        self.mode_fbks = {
            self.ModeType.MOUNTING: self.add_pv("{}:mounting:fbk".format(mode_root)),
            self.ModeType.CENTERING: self.add_pv("{}:centering:fbk".format(mode_root)),
            self.ModeType.COLLECT: self.add_pv("{}:collect:fbk".format(mode_root)),
            self.ModeType.BEAM: self.add_pv("{}:out".format(beam_root)),
        }
        self.mode_cmds = {
            self.ModeType.MOUNTING: self.add_pv("{}:mounting.PROC".format(mode_root)),
            self.ModeType.CENTERING: self.add_pv("{}:centering.PROC".format(mode_root)),
            self.ModeType.COLLECT: self.add_pv("{}:collect.PROC".format(mode_root)),
            self.ModeType.BEAM: self.add_pv("{}:opr:ctl".format(beam_root)),
        }

        # mode change feedback
        for mode, dev in self.mode_fbks.items():
            dev.connect('changed', self.check_state)

        self.busy_fbk.connect('changed', self.check_state)
        self.calibrated_fbk.connect('changed', self.check_state)
        self.busy_fbk.connect('changed', self.on_busy)
        self.scan_fbk.connect('changed', self.on_busy)

        # parameters
        self.settings = {
            'time': self.add_pv("{}:expTime".format(root), monitor=False),
            'delta': self.add_pv("{}:deltaOmega".format(root), monitor=False),
            'angle': self.add_pv("{}:openSHPos".format(root), monitor=False),
        }
        self.requested_mode = None

    def change_mode(self, mode):
        self.props.mode = mode
        self.set_state(mode=mode)

    def check_state(self, *args, **kwargs):
        if (self.busy_fbk.get() == 1) or (self.scan_fbk.get() == 1):
            self.set_state(busy=True)
        if self.mode_fbks[self.ModeType.CENTERING].get() == 1:
            self.change_mode(self.ModeType.CENTERING)
        elif self.mode_fbks[self.ModeType.MOUNTING].get() == 1 and self.calibrated_fbk.get() == 1:
            self.change_mode(self.ModeType.MOUNTING)
        elif self.mode_fbks[self.ModeType.BEAM].get() == 0:
            self.change_mode(self.ModeType.BEAM)
        elif self.mode_fbks[self.ModeType.COLLECT].get() == 1:
            if self.requested_mode in [self.ModeType.COLLECT, self.ModeType.SCANNING]:
                self.change_mode(self.requested_mode)
            else:
                self.change_mode(self.ModeType.COLLECT)
        else:
            self.change_mode(self.ModeType.UNKNOWN)

    def on_busy(self, obj, st):
        if self.scan_fbk.get() == 1 or self.busy_fbk.get() == 1:
            self.set_state(busy=True)
        else:
            self.set_state(busy=False)
        self.check_state()

    def configure(self, **kwargs):
        for key in kwargs.keys():
            self.settings[key].put(kwargs[key])

    def set_mode(self, mode, wait=False):
        # convert strings to ModeType
        mode = mode if isinstance(mode, self.ModeType) else self.ModeType[mode]

        if self.is_busy():
            self.wait(start=False, stop=True)

        message = 'Switching mode to: {}'.format(mode.name.title())
        self.set_state(message=message)

        target_mode = mode if mode != self.ModeType.SCANNING else self.ModeType.COLLECT
        self.mode_cmds[target_mode].put(1)
        self.requested_mode = mode

        if wait:
            self.wait_for_modes({target_mode})

    def scan(self, wait=True, timeout=None):
        self.set_state(message='Scanning ...')
        self.wait(start=False, stop=True, timeout=timeout)
        self.scan_cmd.put(1)
        self.wait(start=True, stop=wait, timeout=timeout)

        if wait:
            self.set_state(message='Scan complete!')

    def stop(self):
        logger.debug('Stopping goniometer ...')
        self.stopped = True
        self.stop_cmd.put(1)


class MD2Gonio(Goniometer):
    """
    MD2-type Goniometer at the CLS 08B1-1.
    """

    def __init__(self, root):
        Goniometer.__init__(self, 'MD2 Goniometer')
        self.requested_mode = None
        # initialize process variables
        self.mode_cmd = self.add_pv('{}:S:MDPhasePosition'.format(root))
        self.scan_cmd = self.add_pv("{}:S:StartScan".format(root))
        self.abort_cmd = self.add_pv("{}:S:AbortScan".format(root))
        self.fluor_cmd = self.add_pv("{}:S:MoveFluoDetFront".format(root))

        self.mode_fbk = self.add_pv("{}:G:MDPhasePosition".format(root))
        self.state_fbk = self.add_pv("{}:G:MachAppState".format(root))
        self.connected_fbk = self.add_pv("{}:G:MachAppState:asyn.CNCT".format(root))
        self.enabled_fbk = self.add_pv("{}:usrEnable".format(root))

        self.log_fbk = self.add_pv('%s:G:StatusMsg' % root)

        # parameters
        self.settings = {
            'time': self.add_pv("{}:S:ScanExposureTime".format(root)),
            'delta': self.add_pv("{}:S:ScanRange".format(root)),
            'angle': self.add_pv("{}:S:ScanStartAngle".format(root)),
            'passes': self.add_pv("{}:S:ScanNumOfPasses".format(root)),
        }

        # signal handlers
        self.mode_fbk.connect('changed', self.on_mode_changed)
        self.state_fbk.connect('changed', self.on_state_changed)
        self.connected_fbk.connect('changed', self.on_connection)
        self.enabled_fbk.connect('changed', self.on_enabled)

    def configure(self, **kwargs):
        for key in kwargs.keys():
            self.settings[key].put(kwargs[key])

    def set_mode(self, mode, wait=False):
        # convert strings to ModeType
        mode = mode if isinstance(mode, self.ModeType) else self.ModeType[mode]

        if self.is_busy():
            self.wait(start=False, stop=True)

        message = 'Switching mode to: {}'.format(mode.name.title())
        self.set_state(message=message)

        target_mode = mode if mode != self.ModeType.SCANNING else self.ModeType.COLLECT
        self.mode_cmd.put(target_mode.value)
        self.requested_mode = mode

        if wait:
            self.wait_for_modes({target_mode})

        if mode == self.ModeType.SCANNING:
            self.fluor_cmd.put(1)

    def on_state_changed(self, *args, **kwargs):
        state = self.state_fbk.get()
        if state in [4, 5, 6]:
            self.set_state(health=(0, 'faults'), busy=True)
        elif state in [0, 1, 7]:
            msg = self.log_fbk.get().split('.')[0]
            self.set_state(health=(2, 'faults', msg), busy=False)
        else:
            self.set_state(busy=False, health=(0, 'faults'))

    def on_mode_changed(self, *args, **kwargs):
        mode = self.ModeType(self.mode_fbk.get())
        if mode == self.ModeType.COLLECT and self.requested_mode in [self.ModeType.COLLECT, self.ModeType.SCANNING]:
            mode = self.requested_mode
        self.set_state(mode=mode)
        self.props.mode = mode

    def on_connection(self, pv, val):
        if val == 0:
            self.set_state(health=(4, 'connection', 'Connection to server lost!'))
        else:
            self.set_state(health=(0, 'connection'))

    def on_enabled(self, pv, val):
        if val == 0:
            self.set_state(health=(16, 'enable', 'Disabled by staff.'))
        else:
            self.set_state(health=(0, 'enable'))

    def scan(self, wait=True, timeout=None):
        self.set_state(message='Scanning ...')
        self.wait(stop=True, start=False, timeout=timeout)
        self.scan_cmd.put(1)
        self.wait(start=True, stop=wait, timeout=timeout)
        if wait:
            self.set_state(message='Scan complete!')

    def stop(self):
        """Stop and abort the current scan if any."""
        self.stopped = True
        self.abort_cmd.put(1)


class SimGonio(Goniometer):
    def __init__(self):
        Goniometer.__init__(self, 'Simulated Goniometer')
        self._scanning = False
        self._lock = Lock()
        self.props.mode = self.ModeType.MOUNTING
        self.set_state(active=True, health=(0, ''), mode=self.mode)

    def configure(self, **kwargs):
        self.settings = kwargs

    def set_mode(self, mode, wait=False):
        # convert strings to ModeType
        mode = mode if isinstance(mode, self.ModeType) else self.ModeType[mode]
        if self.is_busy():
            self.wait(start=False, stop=True)

        message = 'Switching mode to: {}'.format(mode.name.title())
        self.set_state(message=message, busy=True)
        GObject.timeout_add(3000, self._sim_mode, mode)

    def _sim_mode(self, mode):
        self.props.mode = mode
        self.set_state(mode=mode, busy=False)

    @async_call
    def _scan_async(self):
        self._scan_sync(wait=False)

    def _scan_sync(self, wait=True):
        self.set_state(message='Scanning ...', busy=True)
        with self._lock:
            self._scanning = True
            bl = globalRegistry.lookup([], IBeamline)
            st = time.time()
            logger.debug('Starting scan at: %s' % datetime.now().isoformat())
            logger.debug('Moving to scan starting position')
            bl.fast_shutter.open()
            bl.omega.move_to(self.settings['angle'] - 0.05, wait=True, speed=bl.omega.default_speed)
            scan_speed = float(self.settings['delta']) / self.settings['time']
            if wait:
                logger.debug('Waiting for scan to complete ...')
            bl.omega.move_to(self.settings['angle'] + self.settings['delta'] + 0.05, wait=True, speed=scan_speed)
            bl.fast_shutter.close()
            bl.omega.configure(speed=bl.omega.default_speed)
            logger.debug('Scan done at: %s' % datetime.now().isoformat())
            self.set_state(message='Scan complete!', busy=False)
            self._scanning = False

    def scan(self, wait=True, timeout=None):
        if wait:
            self._scan_sync()
        else:
            self._scan_async()

    def stop(self):
        self.stopped = True
        self._scanning = False
        bl = globalRegistry.lookup([], IBeamline)
        bl.omega.stop()


__all__ = ['ParkerGonio', 'MD2Gonio', 'SimGonio']
