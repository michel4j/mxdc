import time
from datetime import datetime
from enum import Enum
from threading import Lock

import numpy
from gi.repository import GLib
from zope.interface import implementer

from mxdc import Registry, Device, IBeamline
from mxdc.devices import motor, stages
from mxdc.utils import misc
from mxdc.utils.decorators import async_call
from mxdc.utils.log import get_module_logger, log_call
from .interfaces import IGoniometer

# setup module logger with a default handler
logger = get_module_logger(__name__)


class GonioFeatures(Enum):
    TRIGGERING, SCAN4D, RASTER4D, KAPPA = range(4)


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

    def configure(self, **kwargs):
        """
        Configure the goniometer in preparation for scanning.

        kwargs:
            - time: exposure time per frame
            - range: angle range
            - angle: start angle of data set
            - frames: total number of frames

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
        timeout = self.default_timeout if timeout is None else timeout
        poll = 0.05
        success = False
        self.stopped = False
        if start:
            time_left = timeout
            logger.debug('Waiting for goniometer to start moving')
            while not self.is_busy() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
                if self.stopped: break

            if self.stopped:
                success = False
            elif time_left <= 0:
                logger.warn('Timed out waiting for goniometer to start moving')
                success = False
            else:
                success = True

        if stop:
            time_left = timeout
            logger.debug('Waiting for goniometer to stop')
            while self.is_busy() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
                if self.stopped: break
            if self.stopped:
                success = False
            elif time_left <= 0:
                logger.warn('Timed out waiting for goniometer to stop')
                success = False
            else:
                success = True

        return success

    def stop(self):
        """
        Stop and abort the current scan if any.
        """
        self.stopped = True

    def scan(self, **kwargs):
        """
        Configure and perform the scan
        :keyword type: Scan type (str), one of ('simple', 'shutterless', 'helical', 'vector', 'raster')
        :keyword wait: boolean whether to wait or not
        :keyword timeout: maximum time to wait for scan.
        :keyword time: exposure time
        :keyword range: scan range in degrees
        :keyword angle: starting angle for scan
        :keyword frames: number of frames to acquire during scan, per line for raster scans
        :keyword start_pos: starting position
        :keyword end_pos: ending position
        :keyword passes:  Number of exposures per frame
        :keyword lines: Number of lines for raster scans
        :keyword width: horizontal size of raster grid
        :keyword height: vertical size of raster grid
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
            'range': self.add_pv(f"{root}:deltaOmega", monitor=False),
            'angle': self.add_pv(f"{root}:openSHPos", monitor=False),
        }

    def on_busy(self, obj, st):
        self.set_state(busy=(self.scan_fbk.get() == 1))

    def scan(self, **kwargs):

        wait = kwargs.pop('wait', True)
        timeout = kwargs.pop('timeout', None)
        start_pos = kwargs.get('start_pos')

        self.configure(**kwargs)

        # move stage to starting point if provided
        if start_pos is not None and len(start_pos) == 3:
            self.stage.move_xyz(*start_pos, wait=True)

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
    :keyword kappa_enabled: enable Kappa
    :keyword scan4d: enable 4D scan capability
    :keyword raster4d: enable 4D rastering capability
    :keyword triggering: enable detector triggering capability
    """
    NULL_VALUE = '__EMPTY__'
    BUSY_STATES = [5, 6, 7, 8]
    ERROR_STATES = [11, 12, 13, 14]

    def __init__(self, root, kappa_enabled=False, scan4d=True, raster4d=True, triggering=True):
        super().__init__('MD2 Diffractometer')
        if kappa_enabled:
            self.add_features(GonioFeatures.KAPPA)
        if scan4d:
            self.add_features(GonioFeatures.SCAN4D)
        if raster4d:
            self.add_features(GonioFeatures.RASTER4D)
        if triggering:
            self.add_features(GonioFeatures.TRIGGERING)

        # initialize process variables
        self.scan_cmd = self.add_pv(f"{root}:startScan")
        self.helix_cmd = self.add_pv(f"{root}:startScan4D")
        self.raster_cmd = self.add_pv(f"{root}:startRasterScan")
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
        self.omega = motor.PseudoMotor(f'{root}:PMTR:omega:deg')
        self.sample_x = motor.PseudoMotor(f'{root}:PMTR:gonX:mm')
        self.sample_y1 = motor.PseudoMotor(f'{root}:PMTR:smplY:mm')
        self.sample_y2 = motor.PseudoMotor(f'{root}:PMTR:smplZ:mm')
        self.add_components(self.omega, self.sample_x, self.sample_y1, self.sample_y2)
        if self.supports(GonioFeatures.KAPPA):
            self.phi = motor.PseudoMotor(f'{root}:PMTR:phi:deg')
            self.chi = motor.PseudoMotor(f'{root}:PMTR:chi:deg')
            self.kappa = motor.PseudoMotor(f'{root}:PMTR:kappa:deg')
            self.add_components(self.phi, self.chi, self.kappa)
        self.stage = stages.SampleStage(
            self.sample_x, self.sample_y1, self.sample_y2, self.omega,
            linked=False, invert_x=True, invert_omega=True,
        )

        # config parameters
        self.settings = {
            'time': self.add_pv(f"{root}:ScanExposureTime"),
            'range': self.add_pv(f"{root}:ScanRange"),
            'angle': self.add_pv(f"{root}:ScanStartAngle"),
            'passes': self.add_pv(f"{root}:ScanNumberOfPasses"),
            'frames': self.add_pv(f'{root}:ScanNumberOfFrames'),
        }

        self.helix_settings = {
            #'time': self.add_pv(f"{root}:startScan4DEx:exposure_time"),
            #'range': self.add_pv(f"{root}:startScan4DEx:scan_range"),
            #'angle': self.add_pv(f"{root}:startScan4DEx:start_angle"),
            'time': self.add_pv(f"{root}:ScanExposureTime"),
            'range': self.add_pv(f"{root}:ScanRange"),
            'angle': self.add_pv(f"{root}:ScanStartAngle"),
            'frames': self.add_pv(f'{root}:ScanNumberOfFrames'),

            # Start position
            'start_pos': (
                self.add_pv(f'{root}:startScan4DEx:start_y'),
                self.add_pv(f'{root}:startScan4DEx:start_cy'),
                self.add_pv(f'{root}:startScan4DEx:start_cx'),
            ),

            # Stop position
            'end_pos': (
                self.add_pv(f'{root}:startScan4DEx:start_y'),
                self.add_pv(f'{root}:startScan4DEx:start_cy'),
                self.add_pv(f'{root}:startScan4DEx:start_cx'),
            ),
        }

        self.raster_settings = {
            'time': self.add_pv(f"{root}:ScanExposureTime"),
            'range': self.add_pv(f"{root}:ScanRange"),
            'angle': self.add_pv(f"{root}:ScanStartAngle"),

            # 'frames': self.add_pv(f"{root}:startRasterScan:frames_per_lines"),
            # 'lines': self.add_pv(f"{root}:startRasterScan:number_of_lines"),
            # 'width': self.add_pv(f"{root}:startRasterScan:horizontal_range"),
            # 'height': self.add_pv(f"{root}:startRasterScan:vertical_range"),
        }

        # semi constant but need to be re-applied each scan
        self.extra_settings = {
            'shutterless': self.add_pv(f'{root}:startRasterScanEx:shutterless'),
            'snake': self.add_pv(f"{root}:startRasterScanEx:invert_direction"),
            'use_table': self.add_pv(f"{root}:startRasterScanEx:use_centring_table"),
            'z_pos': (
                self.add_pv(f'{root}:startScan4DEx:stop_z'),
                self.add_pv(f'{root}:startScan4DEx:start_z'),
                self.add_pv(f'{root}:startRasterScanEx:start_z'),
            )
        }
        self.extra_values = {
            'shutterless': 1,
            'snake': 1,
            'use_table': 1,
            'z_pos': None,
        }

    def on_state_changed(self, *args, **kwargs):
        state = self.state_fbk.get()
        phase = self.phase_fbk.get()
        busy = state in self.BUSY_STATES
        error = state in self.ERROR_STATES
        msg = self.log_fbk.get()
        health = (2, 'faults', msg) if error else (0, 'faults', '')
        logger.debug(f'MD2 State: state={state}, phase={phase}')
        self.set_state(health=health, busy=busy)

        if phase == 0 and self.prev_state == 6 and state == 4:
            self.save_pos_cmd.put(self.NULL_VALUE)
        self.prev_state = state

    @log_call
    def scan(self, **kwargs):
        wait = kwargs.pop('wait', True)
        timeout = kwargs.pop('timeout', None)
        kind = kwargs.get('kind', 'simple')

        # switch to helical if shutterless and points given
        is_helical = all((
            kind == 'shutterless',
            kwargs.get('start_pos'),
            kwargs.get('end_pos'),
            self.supports(GonioFeatures.SCAN4D)
        ))
        if is_helical:
            kind = 'helical'
        elif kwargs.get('start_pos'):
            self.stage.move_xyz(*kwargs['start_pos'], wait=True)

        success = self.wait(stop=True, start=False, timeout=10)

        if not success:
            logger.error('Goniometer is busy. Aborting ')
            return

        self.set_state(message=f'"{kind}" Scanning ...')

        # configure device and start scan
        self.extra_values['z_pos'] = (self.gon_z_fbk.get(),) * 3
        if kind in ['simple', 'shutterless']:
            misc.set_settings(self.settings, **kwargs)
            self.scan_cmd.put(self.NULL_VALUE)
        elif kind == 'helical':
            misc.set_settings(self.helix_settings, **kwargs)
            misc.set_settings(self.extra_settings, **self.extra_values)
            self.helix_cmd.put(self.NULL_VALUE)
        elif kind == 'raster':
            misc.set_settings(self.raster_settings, **kwargs)
            params = [
                kwargs['height'] * 1e-3, kwargs['width'] * 1e-3,  # convert to mm
                kwargs['lines'], kwargs['frames'], 1
            ]
            self.raster_cmd.put(params)

        timeout = timeout or 2 * kwargs['time']

        success = self.wait(start=True, stop=wait, timeout=timeout)
        if wait:
            if success:
                msg = f'"{kind}" scan complete!'
            else:
                msg = f'"{kind}" scan failed!'
            logger.info(msg)
            self.set_state(message=msg)

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

    def __init__(self, kappa_enabled=False, trigger=None):
        super().__init__('SIM Diffractometer')
        if kappa_enabled:
            self.add_features(GonioFeatures.KAPPA)
        if trigger is not None:
            self.add_features(GonioFeatures.TRIGGERING)

        self.trigger = trigger
        self.trigger_positions = []
        self.trigger_index = 0
        self.settings = {}
        self._scanning = False
        self._lock = Lock()

        self.omega = motor.SimMotor('Omega', 0.0, 'deg', speed=60.0, precision=3)
        self.sample_x = motor.SimMotor('Sample X', 0.0, limits=(-2, 2), units='mm', speed=0.5)
        self.sample_y1 = motor.SimMotor('Sample Y', 0.0, limits=(-2, 2), units='mm', speed=0.5)
        self.sample_y2 = motor.SimMotor('Sample Y', 0.0, limits=(-2, 2), units='mm', speed=0.5)

        self.stage = stages.SampleStage(self.sample_x, self.sample_y1, self.sample_y2, self.omega, linked=False)

        if self.supports(GonioFeatures.KAPPA):
            self.kappa = motor.SimMotor('Kappa', 0.0, limits=(-1, 180), units='deg', speed=30)
            self.chi = motor.SimMotor('Chi', 0.0, limits=(-1, 48), units='deg', speed=30)
            self.phi = motor.SimMotor('Phi', 0.0, units='deg', speed=30)

        self.set_state(active=True, health=(0, '', ''))

    def configure(self, **kwargs):
        self.settings = kwargs
        self._frame_exposure = self.settings['time'] / self.settings.get('frames', 1.)

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
            scan_speed = float(self.settings['range']) / self.settings['time']
            self.omega.configure(speed=scan_speed)
            self.trigger_index = 0
            self.trigger_positions = numpy.arange(
                self.settings['angle'],
                self.settings['angle'] + self.settings['range'],
                self.settings['range'] / self.settings.get('frames', 1)
            )
            if self.supports(GonioFeatures.TRIGGERING):
                GLib.idle_add(self.send_triggers)
            self.omega.move_to(self.settings['angle'] + self.settings['range'] + 0.05, wait=True)
            bl.fast_shutter.close()
            self.omega.configure(speed=config['speed'])
            logger.debug('Scan done at: %s' % datetime.now().isoformat())
            self.set_state(message='Scan complete!', busy=False)
            self._scanning = False

    @async_call
    def send_triggers(self):
        logger.debug('starting triggers for {}'.format(self.trigger_positions))
        while self._scanning and self.trigger_index < len(self.trigger_positions):
            if self.omega.get_position() >= self.trigger_positions[self.trigger_index]:
                self.trigger.on(self._frame_exposure * 0.5)
                self.trigger_index += 1
            if self.trigger_index > len(self.trigger_positions):
                break
            time.sleep(0.001)

    def scan(self, **kwargs):
        """
        :keyword kind: type of scan
        :keyword wait: whether to block until scan is complete
        :keyword timeout: maximum wait time
        :keyword time: Exposure time per frame
        :keyword range: angle range per frame
        :keyword start: Start angle for frame
        :keyword start_pos:  Stage position to start from.
        """

        wait = kwargs.pop('wait', True)
        start_pos = kwargs.get('start_pos')

        # settings
        self.configure(**kwargs)

        # move stage to starting point if provided
        if start_pos is not None and len(start_pos) == 3:
            self.stage.move_xyz(*start_pos, wait=True)

        if wait:
            self._scan_sync()
        else:
            self._scan_async()

    def stop(self):
        self.stopped = True
        self._scanning = False
        self.omega.stop()


__all__ = ['ParkerGonio', 'MD2Gonio', 'SimGonio']
