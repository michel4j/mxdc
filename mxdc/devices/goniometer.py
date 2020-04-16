import time
import warnings
from threading import Lock

warnings.simplefilter("ignore")
from datetime import datetime
from zope.interface import implementer
from mxdc import Registry, Device, IBeamline
from mxdc.utils.log import get_module_logger
from mxdc.utils.decorators import async_call
from .interfaces import IGoniometer

# setup module logger with a default handler
logger = get_module_logger(__name__)


@implementer(IGoniometer)
class BaseGoniometer(Device):
    """
    Base class for all goniometers.
    """

    def __init__(self, name='Diffractometer'):
        super().__init__()
        self.name = name
        self.stopped = True
        self.default_timeout = 180
        self.settings = {}

    def configure(self, **kwargs):
        """
        Configure the goniometer in preparation for scanning.

        kwargs:
            - time: exposure time per frame
            - delta: delta angle per frame
            - angle: start angle of data set
            - num_frames: total number of frames

        """
        for key, value in kwargs.items():
            if key in self.settings and value is not None:
                self.settings[key].put(kwargs[key], wait=True)

    def wait(self, start=True, stop=True, timeout=None):
        """
        Wait for the goniometer busy state to change.

        :param start: (bool), Wait for the goniometer to become busy.
        :param stop: (bool), Wait for the goniometer to become idle.
        :param timeout: maximum time in seconds to wait before failing.
        :return: (bool), False if wait timed-out
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

    def scan(self, type='simple', wait=True, timeout=None, **kwargs):
        """
        Configure and perform the scan
        :keyword type: Scan type (str), one of ('simple', 'shutterless', 'vector', 'raster')
        :keyword wait:
        :keyword timeout:
        """
        raise NotImplementedError('Sub-classes must implement "scan" method')


class ParkerGonio(BaseGoniometer):
    """
    EPICS based Parker-type BaseGoniometer at the CLS 08ID-1.

    :param root: (str), PV name of goniometer EPICS record.
    """

    def __init__(self, root):
        super().__init__()

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

    def on_busy(self, obj, st):
        self.set_state(busy=(self.scan_fbk.get() == 1))

    def scan(self, type='simple', wait=True, timeout=None, **kwargs):
        self.configure(**kwargs)
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


class MD2Gonio(BaseGoniometer):
    """
    MD2-type BaseGoniometer. New Arinax Java Interface

    :param root: Server PV name
    """
    NULL_VALUE = '__EMPTY__'

    def __init__(self, root):
        super().__init__('MD2 Diffractometer')

        # initialize process variables
        self.scan_cmd = self.add_pv("{}:startScan".format(root))
        self.abort_cmd = self.add_pv("{}:abort".format(root))
        self.fluor_cmd = self.add_pv("{}:FluoDetectorIsBack".format(root))
        self.save_pos_cmd = self.add_pv("{}:saveCentringPositions".format(root))

        self.state_fbk = self.add_pv("{}:State".format(root))
        self.phase_fbk = self.add_pv("{}:CurrentPhase".format(root))
        self.log_fbk = self.add_pv('{}:Status'.format(root))
        self.gon_z_fbk = self.add_pv('{}:AlignmentZPosition'.format(root))

        self.prev_state = 0

        # signal handlers
        self.state_fbk.connect('changed', self.on_state_changed)

        # config parameters
        self.settings = {
            # Normal Scans
            'time': self.add_pv("{}:ScanExposureTime".format(root)),
            'delta': self.add_pv("{}:ScanRange".format(root)),
            'angle': self.add_pv("{}:ScanStartAngle".format(root)),
            'passes': self.add_pv("{}:ScanNumberOfPasses".format(root)),
            'num_frames': self.add_pv('{}:ScanNumberOfFrames'.format(root)),
        }

        self.helix_settings = {
            'time': self.add_pv("{}:startScan4DEx:exposure_time".format(root)),
            'range': self.add_pv("{}:startScan4DEx:scan_range".format(root)),
            'angle': self.add_pv("{}:startScan4DEx:start_angle".format(root)),
            'frames': self.add_pv("{}startScan4DEx:ScanNumberOfFrames".format(root)),

            # Start position
            'start_x': self.add_pv('{}:startScan4DEx:start_y'.format(root)),
            'start_y': self.add_pv('{}:startScan4DEx:start_cx'.format(root)),
            'start_z': self.add_pv('{}:startScan4DEx:start_cz'.format(root)),


            # Stop position
            'stop_x': self.add_pv('{}:startScan4DEx:stop_y'.format(root)),
            'stop_y': self.add_pv('{}:startScan4DEx:stop_cx'.format(root)),
            'stop_z': self.add_pv('{}:startScan4DEx:stop_cz'.format(root)),
        }

        self.raster_settings = {
            'time': self.add_pv("{}:tartRasterScanEx:exposure_time".format(root)),
            'angle': self.add_pv("{}:startRasterScanEx:start_omega".format(root)),
            'frames': self.add_pv("{}:startRasterScanEx:frames_per_lines".format(root)),
            'lines': self.add_pv("{}:startRasterScanEx:number_of_lines".format(root)),
            'line_range': self.add_pv("{}:startRasterScanEx:line_range".format(root)),
            'turn_range': self.add_pv("{}:startRasterScanEx:total_uturn_range".format(root)),
            'start_x': self.add_pv('{}:startRasterScanEx:start_y'.format(root)),
            'start_y': self.add_pv('{}:startRasterScanEx:start_cx'.format(root)),
            'start_z': self.add_pv('{}:startRasterScanEx:start_cz'.format(root)),
        }

        # semi constant but need to be re-applied each scan
        self.extra_settings = {
            'shutterless': self.add_pv('{}:startRasterScanEx:shutterless'.format(root)),
            'snake': self.add_pv("{}:startRasterScanEx:invert_direction".format(root)),
            'use_table': self.add_pv("{}:startRasterScanEx:use_centring_table".format(root)),
            'align_z1': self.add_pv('{}:startScan4DEx:stop_z'.format(root)),
            'align_z2': self.add_pv('{}:startScan4DEx:start_z'.format(root)),
            'align_z3': self.add_pv('{}:startRasterScanEx:start_z'.format(root)),
        }
        self.extra_values = {
            'shutterless': 1,
            'snake': 1,
            'use_table': 1,
            'align_z1': 0,
            'align_z2': 0,
            'align_z3': 0,
        }

    def on_state_changed(self, *args, **kwargs):
        state = self.state_fbk.get()
        phase = self.phase_fbk.get()
        if state in [5, 6, 7, 8]:
            self.set_state(health=(0, 'faults', ''), busy=True)
        elif state in [11, 12, 13, 14]:
            msg = self.log_fbk.get()
            self.set_state(health=(2, 'faults', msg), busy=False)
        else:
            self.set_state(busy=False, health=(0, 'faults', ''))

        if phase == 0 and self.prev_state == 6 and state == 4:
            self.save_pos_cmd.put(self.NULL_VALUE)
        self.prev_state = state

    def scan(self, type='simple', wait=True, timeout=None, **kwargs):
        """
        Perform a data collection scan

        :param wait: Whether to wait for scan to complete
        :param timeout: maximum time to wait
        """

        self.configure(**kwargs)
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


class SimGonio(BaseGoniometer):
    """
    Simulated BaseGoniometer.
    """
    def __init__(self):
        super().__init__('SIM Diffractometer')
        self.settings = {}
        self._scanning = False
        self._lock = Lock()
        self.set_state(active=True, health=(0, '', ''))

    def configure(self, **kwargs):
        self.settings = kwargs

    @async_call
    def _scan_async(self):
        self._scan_sync()

    def _scan_sync(self):
        self.set_state(message='Scanning ...', busy=True)
        with self._lock:
            self._scanning = True
            bl = Registry.get_utility(IBeamline)
            config = bl.omega.get_config()
            logger.debug('Starting scan at: %s' % datetime.now().isoformat())
            logger.debug('Moving to scan starting position')
            bl.fast_shutter.open()
            bl.omega.move_to(self.settings['angle'] - 0.05, wait=True)
            scan_speed = float(self.settings['delta']) / self.settings['time']
            bl.omega.configure(speed=scan_speed)
            bl.omega.move_to(self.settings['angle'] + self.settings['delta'] + 0.05, wait=True)
            bl.fast_shutter.close()
            bl.omega.configure(speed=config['speed'])
            logger.debug('Scan done at: %s' % datetime.now().isoformat())
            self.set_state(message='Scan complete!', busy=False)
            self._scanning = False

    def scan(self, type='simple', wait=True, timeout=None, **kwargs):
        """
        :param wait:
        :param timeout:
        :param kwargs:
        :keyword time: Exposure time per frame
        :keyword delta: angle range per frame
        :keyword start: Start angle for frame
        """
        # settings
        self.settings = kwargs

        if wait:
            self._scan_sync()
        else:
            self._scan_async()

    def stop(self):
        self.stopped = True
        self._scanning = False
        bl = Registry.get_utility(IBeamline)
        bl.omega.stop()


class GalilGonio(BaseGoniometer):
    """
    EPICS based Galil BaseGoniometer.

    :param root: (str): PV name of goniometer EPICS record.
    """

    def __init__(self, root):
        super().__init__()

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

    def scan(self, type='simple', wait=True, timeout=180, **kwargs):
        self.configure(**kwargs)
        self.set_state(message='Scanning ...')
        self.wait(start=False, stop=True, timeout=timeout)
        self.scan_cmd.put(1)
        self.wait(start=True, stop=wait, timeout=timeout)

        if wait:
            self.set_state(message='Scan complete!')

    def stop(self):
        logger.debug('Stopping goniometer ...')
        self.stopped = True


__all__ = ['ParkerGonio', 'MD2Gonio', 'SimGonio', 'GalilGonio']
