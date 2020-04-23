import time
import warnings
from threading import Lock

warnings.simplefilter("ignore")
from datetime import datetime
from zope.interface import implementer
from mxdc import Registry, Device, IBeamline
from mxdc.utils.log import get_module_logger
from mxdc.utils.decorators import async_call
from mxdc.utils import misc
from .interfaces import IGoniometer
from mxdc.devices import motor, stages

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
        self.omega = None
        self.phi = None
        self.kappa = None
        self.chi = None
        self.stage = None
        self.kappa_enabled = False

    def has_kappa(self):
        """
        Check if Goniometer has Kappa capability
        """
        return self.kappa_enabled

    def configure(self, **kwargs):
        """
        Configure the goniometer in preparation for scanning.

        kwargs:
            - time: exposure time per frame
            - delta: delta angle per frame
            - angle: start angle of data set
            - num_frames: total number of frames

        """
        misc.set_settings(self.settings, **kwargs)

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
        :keyword type: Scan type (str), one of ('simple', 'shutterless', 'helical', 'vector', 'raster')
        :keyword wait:
        :keyword timeout:
        """
        raise NotImplementedError('Sub-classes must implement "scan" method')


class ParkerGonio(BaseGoniometer):
    """
    EPICS based Parker-type BaseGoniometer at the CLS 08ID-1.

    :param root: (str), PV name of goniometer EPICS record.
    """

    def __init__(self, root, xname, y1name, y2name):
        super().__init__()

        # initialize process variables
        self.scan_cmd = self.add_pv(f"{root}:scanFrame.PROC")
        self.stop_cmd = self.add_pv(f"{root}:stop")
        self.scan_fbk = self.add_pv(f"{root}:scanFrame:status")
        self.scan_fbk.connect('changed', self.on_busy)

        # create additional components
        self.omega = motor.VMEMotor(f'{root}:deg')
        self.sample_x = motor.VMEMotor(xname)
        self.sample_y1 = motor.VMEMotor(y1name)
        self.sample_y2 = motor.VMEMotor(y2name)
        self.add_components(self.omega, self.sample_x, self.sample_y1, self.sample_y2)
        self.stage = stages.SampleStage(
            self.sample_x, self.sample_y1, self.sample_y2, self.omega, linked=False
        )

        # parameters
        self.settings = {
            'time': self.add_pv(f"{root}:expTime", monitor=False),
            'delta': self.add_pv(f"{root}:deltaOmega", monitor=False),
            'angle': self.add_pv(f"{root}:openSHPos", monitor=False),
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

    def __init__(self, root, kappa_enabled=False):
        super().__init__('MD2 Diffractometer')
        self.kappa_enabled = kappa_enabled

        # initialize process variables
        self.scan_cmd = self.add_pv(f"{root}:startScan")
        self.abort_cmd = self.add_pv(f"{root}:abort")
        self.fluor_cmd = self.add_pv(f"{root}:FluoDetectorIsBack")
        self.save_pos_cmd = self.add_pv(f"{root}:saveCentringPositions")

        self.state_fbk = self.add_pv(f"{root}:State")
        self.phase_fbk = self.add_pv(f"{root}:CurrentPhase")
        self.log_fbk = self.add_pv(f'{root}:Status')
        self.gon_z_fbk = self.add_pv(f'{root}:AlignmentZPosition')

        # signal handlers
        self.prev_state = 0
        self.state_fbk.connect('changed', self.on_state_changed)

        # create additional components
        self.omega =  motor.PseudoMotor(f'{root}:PMTR:omega:deg')
        self.sample_x = motor.PseudoMotor(f'{root}:PMTR:gonX:mm')
        self.sample_y1 = motor.PseudoMotor(f'{root}:PMTR:smplY:mm')
        self.sample_y2 = motor.PseudoMotor(f'{root}:PMTR:smplZ:mm')
        self.add_components(self.omega, self.sample_x, self.sample_y1, self.sample_y2)
        if self.has_kappa():
            self.phi = motor.PseudoMotor(f'{root}:PMTR:phi:deg')
            self.chi = motor.PseudoMotor(f'{root}:chi:deg')
            self.kappa = motor.PseudoMotor(f'{root}:PMTR:kappa:deg')
            self.add_components(self.phi, self.chi, self.kappa)
        self.stage = stages.SampleStage(self.sample_x, self.sample_y1, self.sample_y2, self.omega, linked=False)

        # config parameters
        self.settings = {
            'time': self.add_pv(f"{root}:ScanExposureTime"),
            'delta': self.add_pv(f"{root}:ScanRange"),
            'angle': self.add_pv(f"{root}:ScanStartAngle"),
            'passes': self.add_pv(f"{root}:ScanNumberOfPasses"),
            'num_frames': self.add_pv(f'{root}:ScanNumberOfFrames'),
        }

        self.helix_settings = {
            'time': self.add_pv(f"{root}:startScan4DEx:exposure_time"),
            'range': self.add_pv(f"{root}:startScan4DEx:scan_range"),
            'angle': self.add_pv(f"{root}:startScan4DEx:start_angle"),
            'frames': self.add_pv(f"{root}startScan4DEx:ScanNumberOfFrames"),

            # Start position
            'x0': self.add_pv(f'{root}:startScan4DEx:start_y'),
            'y0': self.add_pv(f'{root}:startScan4DEx:start_cx'),
            'z0': self.add_pv(f'{root}:startScan4DEx:start_cz'),

            # Stop position
            'x1': self.add_pv(f'{root}:startScan4DEx:stop_y'),
            'y1': self.add_pv(f'{root}:startScan4DEx:stop_cx'),
            'z1': self.add_pv(f'{root}:startScan4DEx:stop_cz'),
        }

        self.raster_settings = {
            'time': self.add_pv(f"{root}:tartRasterScanEx:exposure_time"),
            'angle': self.add_pv(f"{root}:startRasterScanEx:start_omega"),
            'frames': self.add_pv(f"{root}:startRasterScanEx:frames_per_lines"),
            'lines': self.add_pv(f"{root}:startRasterScanEx:number_of_lines"),
            'line_range': self.add_pv(f"{root}:startRasterScanEx:line_range"),
            'turn_range': self.add_pv(f"{root}:startRasterScanEx:total_uturn_range"),
            'x0': self.add_pv(f'{root}:startRasterScanEx:start_y'),
            'y0': self.add_pv(f'{root}:startRasterScanEx:start_cx'),
            'z0': self.add_pv(f'{root}:startRasterScanEx:start_cz'),
        }

        # semi constant but need to be re-applied each scan
        self.extra_settings = {
            'shutterless': self.add_pv(f'{root}:startRasterScanEx:shutterless'),
            'snake': self.add_pv(f"{root}:startRasterScanEx:invert_direction"),
            'use_table': self.add_pv(f"{root}:startRasterScanEx:use_centring_table"),
            'zA': self.add_pv(f'{root}:startScan4DEx:stop_z'),
            'zB': self.add_pv(f'{root}:startScan4DEx:start_z'),
            'zC': self.add_pv(f'{root}:startRasterScanEx:start_z'),
        }
        self.extra_values = {
            'shutterless': 1,
            'snake': 1,
            'use_table': 1,
            'zA': None,
            'zB': None,
            'zC': None,
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

        # configure device
        self.extra_values['zA'] = self.extra_values['zB'] = self.extra_values['zC'] = self.gon_z_fbk.get()
        if type in ['simple', 'shutterless']:
            misc.set_settings(self.settings, **kwargs)
        elif type == 'helical':
            misc.set_settings(self.helix_settings, **kwargs)
            misc.set_settings(self.extra_settings, **self.extra_values)
        elif type == 'raster':
            misc.set_settings(self.raster_settings, **kwargs)
            misc.set_settings(self.extra_settings, **self.extra_values)

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
    Simulated Goniometer.
    """
    def __init__(self, kappa_enabled=False):
        super().__init__('SIM Diffractometer')
        self.kappa_enabled = kappa_enabled
        self.settings = {}
        self._scanning = False
        self._lock = Lock()

        self.omega = motor.SimMotor('Omega', 0.0, 'deg', speed=60.0, precision=3)
        self.sample_x = motor.SimMotor('Sample X', 0.0, limits=(-2, 2), units='mm', speed=0.1)
        self.sample_y1 = motor.SimMotor('Sample Y', 0.0, limits=(-2, 2), units='mm', speed=0.1)
        self.sample_y2 = motor.SimMotor('Sample Y', 0.0, limits=(-2, 2), units='mm', speed=0.2)

        self.stage = stages.SampleStage(self.sample_x, self.sample_y1, self.sample_y2, self.omega, linked=False)

        if self.has_kappa():
            self.kappa = motor.SimMotor('Kappa', 0.0, limits=(-1, 180), units='deg', speed=30)
            self.chi = motor.SimMotor('Chi', 0.0, limits=(-1, 48), units='deg', speed=30)
            self.phi = motor.SimMotor('Phi', 0.0, units='deg', speed=30)

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
            config = self.omega.get_config()
            logger.debug('Starting scan at: %s' % datetime.now().isoformat())
            logger.debug('Moving to scan starting position')
            bl.fast_shutter.open()
            self.omega.move_to(self.settings['angle'] - 0.05, wait=True)
            scan_speed = float(self.settings['delta']) / self.settings['time']
            self.omega.configure(speed=scan_speed)
            self.omega.move_to(self.settings['angle'] + self.settings['delta'] + 0.05, wait=True)
            bl.fast_shutter.close()
            self.omega.configure(speed=config['speed'])
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
        self.omega.stop()


__all__ = ['ParkerGonio', 'MD2Gonio', 'SimGonio']
