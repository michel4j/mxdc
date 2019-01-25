import time
import warnings
from threading import Lock

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


class Goniometer(BaseDevice):
    """Base class for goniometer."""
    implements(IGoniometer)

    def __init__(self, name='Diffractometer'):
        BaseDevice.__init__(self)
        self.name = name
        self.stopped = True
        self.default_timeout = 180

    def wait(self, start=True, stop=True, timeout=None):
        """
        Wait for the goniometer busy state to change.

        @param start: (bool), Wait for the goniometer to become busy.
        @param stop: (bool), Wait for the goniometer to become idle.
        @param timeout: maximum time in seconds to wait before failing.
        @return: (bool), False if wait timed-out
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
        """
        Stop and abort the current scan if any.
        """
        self.stopped = True

    def scan(self, wait=True, timeout=None):
        """Perform and data collection Scan"""
        raise NotImplementedError('Sub-classes must implement "scan" method')


class ParkerGonio(Goniometer):

    def __init__(self, root):
        """
        EPICS based Parker-type Goniometer at the CLS 08ID-1.

        @param root: (str): PV name of goniometer EPICS record.

        """
        super(ParkerGonio, self).__init__()

        # initialize process variables
        self.scan_cmd = self.add_pv("{}:scanFrame.PROC".format(root))
        self.stop_cmd = self.add_pv("{}:stop".format(root))
        self.scan_fbk = self.add_pv("{}:scanFrame:status".format(root))

        self.scan_fbk.connect('changed', self.on_busy)

        # parameters
        self.settings = {
            'time': self.add_pv("{}:expTime".format(root), monitor=False),
            'delta': self.add_pv("{}:deltaOmega".format(root), monitor=False),
            'angle': self.add_pv("{}:openSHPos".format(root), monitor=False),
        }

    def check_state(self, *args, **kwargs):
        if self.scan_fbk.get() == 1:
            self.set_state(busy=True)

    def on_busy(self, obj, st):
        if self.scan_fbk.get() == 1:
            self.set_state(busy=True)
        else:
            self.set_state(busy=False)
        self.check_state()

    def configure(self, **kwargs):
        for key in kwargs.keys():
            self.settings[key].put(kwargs[key])

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
    NULL_VALUE = '__EMPTY__'

    def __init__(self, root):
        """
        MD2-type Goniometer. New Arinax Java Interface

        @param root: Server PV name
        """
        super(MD2Gonio, self).__init__('MD2 Diffractometer')

        # initialize process variables
        self.scan_cmd = self.add_pv("{}:startScan".format(root))
        self.abort_cmd = self.add_pv("{}:abort".format(root))
        self.fluor_cmd = self.add_pv("{}:FluoDetectorIsBack".format(root))
        self.save_pos_cmd = self.add_pv("{}:saveCentringPositions".format(root))

        self.state_fbk = self.add_pv("{}:State".format(root))
        self.phase_fbk = self.add_pv("{}:CurrentPhase".format(root))
        self.log_fbk = self.add_pv('{}:Status'.format(root))
        self.prev_state = 0

        # parameters
        self.settings = {
            'time': self.add_pv("{}:ScanExposureTime".format(root)),
            'delta': self.add_pv("{}:ScanRange".format(root)),
            'angle': self.add_pv("{}:ScanStartAngle".format(root)),
            'passes': self.add_pv("{}:ScanNumberOfPasses".format(root)),
        }

        # signal handlers
        self.state_fbk.connect('changed', self.on_state_changed)

    def configure(self, **kwargs):
        for key in kwargs.keys():
            self.settings[key].put(kwargs[key])

    def on_state_changed(self, *args, **kwargs):
        state = self.state_fbk.get()
        phase = self.phase_fbk.get()
        if state in [5, 6, 7, 8]:
            self.set_state(health=(0, 'faults'), busy=True)
        elif state in [11, 12, 13, 14]:
            msg = self.log_fbk.get()
            self.set_state(health=(2, 'faults', msg), busy=False)
        else:
            self.set_state(busy=False, health=(0, 'faults'))

        if phase == 0 and self.prev_state == 6 and state == 4:
            self.save_pos_cmd.put(self.NULL_VALUE)
        self.prev_state = state

    def scan(self, wait=True, timeout=None):
        """
        Perform a data collection scan

        @param wait: Whether to wait for scan to complete
        @param timeout: maximum time to wait
        """
        self.set_state(message='Scanning ...')
        self.wait(stop=True, start=False, timeout=timeout)
        self.scan_cmd.put(self.NULL_VALUE)
        self.wait(start=True, stop=wait, timeout=timeout)
        if wait:
            self.set_state(message='Scan complete!')

    def stop(self):
        """
        Stop and abort the current scan if any.
        """
        self.stopped = True
        self.abort_cmd.put(self.NULL_VALUE)


class SimGonio(Goniometer):
    def __init__(self):
        super(SimGonio, self).__init__('SIM Diffractometer')
        self._scanning = False
        self._lock = Lock()
        self.set_state(active=True, health=(0, ''))

    def configure(self, **kwargs):
        self.settings = kwargs

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
            bl.omega.move_to(self.settings['angle'] - 0.05, wait=True, speed=90.0)
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


class GalilGonio(Goniometer):

    def __init__(self, root):
        """
        EPICS based Parker-type Goniometer at the CLS 08ID-1.

        @param root: (str): PV name of goniometer EPICS record.
        """
        super(GalilGonio, self).__init__()

        # initialize process variables
        self.scan_cmd = self.add_pv("{}:OSCEXEC_SP".format(root))
        self.scan_fbk = self.add_pv("{}:OSCSTATE_MONITOR".format(root))

        self.scan_fbk.connect('changed', self.on_busy)

        # parameters
        self.settings = {
            'time': self.add_pv("{}:EXPOSURE_TIME_SP".format(root), monitor=False),
            'delta': self.add_pv("{}:OSC_WDDTH_SP".format(root), monitor=False),
            'angle': self.add_pv("{}:OSC_POS_SP".format(root), monitor=False),
        }

    def on_busy(self, obj, st):
        if self.scan_fbk.get() == 1:
            self.set_state(busy=True)
        else:
            self.set_state(busy=False)

    def configure(self, **kwargs):
        for key in kwargs.keys():
            self.settings[key].put(kwargs[key])

    def scan(self, wait=True, timeout=180):
        self.set_state(message='Scanning ...')
        self.wait(start=False, stop=True, timeout=timeout)
        self.scan_cmd.put(1)
        self.wait(start=True, stop=wait, timeout=timeout)

        if wait:
            self.set_state(message='Scan complete!')

    def stop(self):
        logger.debug('Stopping goniometer ...')
        self.stopped = True


class OldMD2Gonio(Goniometer):
    NULL_VALUE = '__EMPTY__'

    def __init__(self, root):
        """
        MD2-type Goniometer. Old Maatel Socket Interface

        @param root: Server PV name
        """
        super(OldMD2Gonio, self).__init__('MD2 Diffractometer')

        # initialize process variables
        self.scan_cmd = self.add_pv("{}:S:StartScan".format(root), monitor=False)
        self.abort_cmd = self.add_pv("{}:S:AbortScan".format(root), monitor=False)
        self.fluor_cmd = self.add_pv("{}:S:MoveFluoDetFront".format(root), monitor=False)
        self.save_pos_cmd = self.add_pv("{}:S:ManCentCmpltd".format(root), monitor=False)

        self.state_fbk = self.add_pv("{}:G:MachAppState".format(root))
        self.log_fbk = self.add_pv('{}:G:StatusMsg'.format(root))

        # parameters
        self.settings = {
            'time': self.add_pv("{}:S:ScanExposureTime".format(root)),
            'delta': self.add_pv("{}:S:ScanRange".format(root)),
            'angle': self.add_pv("{}:S:ScanStartAngle".format(root)),
            'passes': self.add_pv("{}:S:ScanNumOfPasses".format(root)),
        }

        # signal handlers
        self.state_fbk.connect('changed', self.on_state_changed)

    def configure(self, **kwargs):
        for key in kwargs.keys():
            self.settings[key].put(kwargs[key])

    def on_state_changed(self, *args, **kwargs):
        state = self.state_fbk.get()
        if state in [5, 6, 7, 8]:
            self.set_state(health=(0, 'faults'), busy=True)
        elif state in [11, 12, 13, 14]:
            msg = self.log_fbk.get()
            self.set_state(health=(2, 'faults', msg), busy=False)
        else:
            self.set_state(busy=False, health=(0, 'faults'))

    def scan(self, wait=True, timeout=None):
        """
        Perform a data collection scan

        @param wait: Whether to wait for scan to complete
        @param timeout: maximum time to wait
        """
        self.set_state(message='Scanning ...')
        self.wait(stop=True, start=False, timeout=timeout)
        self.scan_cmd.toggle(1, 0)
        self.wait(start=True, stop=wait, timeout=timeout)
        if wait:
            self.set_state(message='Scan complete!')

    def stop(self):
        """
        Stop and abort the current scan if any.
        """
        self.stopped = True
        self.abort_cmd.toggle(1, 0)


__all__ = ['ParkerGonio', 'MD2Gonio', 'OldMD2Gonio', 'SimGonio', 'GalilGonio']
