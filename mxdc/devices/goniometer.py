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
    TRIGGERING = 0  # Gonio sends one trigger for the full series of frames
    SCAN4D = 1
    RASTER4D = 2
    KAPPA = 3
    GATING = 4      # Gonio sends individual trigger signals for each frame


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

    def grid_settings(self):
        """
        Return a dictionary of grid settings supported by this goniometer
        """
        return {"snake": True, "vertical": False, "buggy": False}

    def save_centering(self):
        """
        Save current sample position. Goniometer should return to the saved position during centering.
        """
        pass

    def wait_start(self, timeout=5):
        """
        Wait for device to start
        :param timeout: maximum time in seconds to wait before failing.
        :return: bool, False if timeout
        """

        end_time = time.time() + timeout
        success = False
        self.stopped = False
        logger.debug(f'{self.name}: Waiting to start ...')
        while time.time() < end_time:
            if self.stopped or self.is_busy():
                logger.debug(f'{self.name}: started ...')
                success = True
                break
            time.sleep(0.01)
        else:
            logger.warn(f'{self.name}: Timed-out waiting to stop after {timeout} sec')
        return success

    def wait_stop(self, timeout=None):
        """
        Wait for device to start
        :param timeout: maximum time in seconds to wait before failing.
        :return: bool, False if timeout
        """
        success = False
        self.stopped = False
        logger.debug(f'{self.name}: Waiting to stop ...')
        if timeout is None:
            while self.is_busy() and not self.stopped:
                time.sleep(0.01)
            else:
                logger.debug(f'{self.name}: stopped ...')
                success = True
        else:
            end_time = time.time() + timeout
            while time.time() < end_time:
                if self.stopped or not self.is_busy():
                    logger.debug(f'{self.name}: stopped ...')
                    success = True
                    break
                time.sleep(0.01)
            else:
                logger.warn(f'{self.name}: Timed-out waiting to stop after {timeout} sec')
        return success


    def wait(self, start=True, stop=True, timeout=None):
        """
        Wait for the goniometer busy state to change.

        :param start: (bool), Wait for the goniometer to become busy.
        :param stop: (bool), Wait for the goniometer to become idle.
        :param timeout: maximum time in seconds to wait before failing.
        :return: (bool), False if wait timed-out
        """
        timeout = self.default_timeout if timeout is None else timeout

        self.stopped = False
        success_start = True
        success_stop = True
        if start:
            success_start = self.wait_start()
        if stop:
            success_stop = self.wait_stop(timeout)

        return success_start and success_stop

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

    def __init__(self, root, xname, y1name, y2name, yname, zname):
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
        self.support_y = motor.VMEMotor(yname)
        self.support_z = motor.VMEMotor(zname)

        self.add_components(self.omega, self.sample_x, self.sample_y1, self.sample_y2)
        self.stage = stages.SampleStage(
            self.sample_x, self.sample_y1, self.sample_y2, self.omega, linked=False
        )
        self.support = stages.XYZStage(self.samlple_x, self.support_y, self.support_z)

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

    NULL_VALUE = '__EMPTY__'
    BUSY_STATES = [5, 6, 7, 8]
    ERROR_STATES = [11, 12, 13, 14]
    MAX_RASTER_SPEED = 0.8

    def __init__(self, root, kappa=False, scan4d=True, raster4d=True, triggering=True, power=False, gating=False):
        """
        MD2-type BaseGoniometer. New Arinax Java Interface

        :param root: Server PV name
        :keyword kappa: enable Kappa
        :keyword scan4d: enable 4D scan capability
        :keyword raster4d: enable 4D rastering capability
        :keyword triggering: enable detector triggering capability
        :keyword power: boolean, PowerPMAC architecture, False for TurboPMAC
        :keyword gating: boolean, enable Goniometer gating
        """
        super().__init__('MD2 Diffractometer')
        if kappa:
            self.add_features(GonioFeatures.KAPPA)
        if scan4d:
            self.add_features(GonioFeatures.SCAN4D)
        if raster4d:
            self.add_features(GonioFeatures.RASTER4D)
        if triggering:
            self.add_features(GonioFeatures.TRIGGERING)
        if gating:
            self.add_features(GonioFeatures.GATING)

        self.power_pmac = power

        # initialize process variables
        self.scan_cmd = self.add_pv(f"{root}:startScan")
        self.abort_cmd = self.add_pv(f"{root}:abort")
        self.fluor_cmd = self.add_pv(f"{root}:FluoDetectorIsBack")
        self.save_pos_cmd = self.add_pv(f"{root}:saveCentringPositions")
        self.front_light_cmd = self.add_pv(f"{root}:FrontLightIsOn")

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
        self.support_y = motor.PseudoMotor(f'{root}:PMTR:gonY:mm')
        self.support_z = motor.PseudoMotor(f'{root}:PMTR:gonZ:mm')

        self.add_components(self.omega, self.sample_x, self.sample_y1, self.sample_y2, self.support_y, self.support_z)

        if self.supports(GonioFeatures.KAPPA):
            self.phi = motor.PseudoMotor(f'{root}:PMTR:phi:deg')
            self.chi = motor.PseudoMotor(f'{root}:PMTR:chi:deg')
            self.kappa = motor.PseudoMotor(f'{root}:PMTR:kappa:deg')
            self.add_components(self.phi, self.chi, self.kappa)
        self.stage = stages.SampleStage(
            self.sample_x, self.sample_y1, self.sample_y2, self.omega,
            invert_x=True, invert_omega=True,
        )
        self.support = stages.XYZStage(self.sample_x, self.support_y, self.support_z)

        # config parameters
        self.settings = {
            'time': self.add_pv(f"{root}:ScanExposureTime"),
            'range': self.add_pv(f"{root}:ScanRange"),
            'angle': self.add_pv(f"{root}:ScanStartAngle"),
            'passes': self.add_pv(f"{root}:ScanNumberOfPasses"),
            'frames': self.add_pv(f'{root}:ScanNumberOfFrames'),
        }

        # self.helix_cmd = self.add_pv(f"{root}:startScan4D")
        # self.helix_settings = {
        #     'time': self.add_pv(f"{root}:ScanExposureTime"),
        #     'range': self.add_pv(f"{root}:ScanRange"),
        #     'angle': self.add_pv(f"{root}:ScanStartAngle"),
        #     'frames': self.add_pv(f'{root}:ScanNumberOfFrames'),
        #     'start': self.add_pv(f'{root}:setStartScan4D'),
        #     'stop': self.add_pv(f'{root}:setStopScan4D'),
        # }

        self.helix_cmd = self.add_pv(f"{root}:startScan4DEx")
        self.helix_settings = {
            'time': self.add_pv(f"{root}:startScan4DEx:exposure_time"),
            'range': self.add_pv(f"{root}:startScan4DEx:scan_range"),
            'angle': self.add_pv(f"{root}:startScan4DEx:start_angle"),
            'frames': self.add_pv(f'{root}:ScanNumberOfFrames'),

            # Start position
            'start': (
                self.add_pv(f'{root}:startScan4DEx:start_y'),
                self.add_pv(f'{root}:startScan4DEx:start_z'),
                self.add_pv(f'{root}:startScan4DEx:start_cx'),
                self.add_pv(f'{root}:startScan4DEx:start_cy'),
            ),

            # Stop position
            'stop': (
                self.add_pv(f'{root}:startScan4DEx:stop_y'),
                self.add_pv(f'{root}:startScan4DEx:stop_z'),
                self.add_pv(f'{root}:startScan4DEx:stop_cx'),
                self.add_pv(f'{root}:startScan4DEx:stop_cy'),
            ),
        }

        self.raster_cmd = self.add_pv(f"{root}:startRasterScanEx")
        self.raster_settings = {
            'time': self.add_pv(f"{root}:startRasterScanEx:exposure_time"),
            'range': self.add_pv(f"{root}:startRasterScanEx:omega_range"),
            'angle': self.add_pv(f"{root}:startRasterScanEx:start_omega"),

            'frames': self.add_pv(f"{root}:startRasterScanEx:frames_per_lines"),
            'lines': self.add_pv(f"{root}:startRasterScanEx:number_of_lines"),
            'width': self.add_pv(f"{root}:startRasterScanEx:horizontal_range"),
            'height': self.add_pv(f"{root}:startRasterScanEx:vertical_range"),
            'snake': self.add_pv(f"{root}:startRasterScanEx:invert_direction"),
            'use_table': self.add_pv(f"{root}:startRasterScanEx:use_centring_table"),
            'shutterless': self.add_pv(f'{root}:startRasterScanEx:shutterless'),
            'start': (
                self.add_pv(f'{root}:startRasterScanEx:start_y'),
                self.add_pv(f'{root}:startRasterScanEx:start_z'),
                self.add_pv(f'{root}:startRasterScanEx:start_cx'),
                self.add_pv(f'{root}:startRasterScanEx:start_cy'),
            ),
        }

    def grid_settings(self):
        return {
            "snake": True,
            "vertical": not self.power_pmac,
            "buggy": False,
        }

    def save_centering(self):
        self.save_pos_cmd.put(self.NULL_VALUE)

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
            self.save_centering()
        self.prev_state = state

    @log_call
    def scan(self, **kwargs):
        wait = kwargs.pop('wait', True)
        timeout = kwargs.pop('timeout', None)
        kind = kwargs.get('kind', 'simple')

        # switch to helical if shutterless and points given
        is_helical = all((
            kind == 'shutterless', kwargs.get('start_pos'), kwargs.get('end_pos'), self.supports(GonioFeatures.SCAN4D)
        ))
        if is_helical:
            kind = 'helical'

        if kind not in ['helical', 'raster'] and kwargs.get('start_pos') is not None:
            self.stage.move_xyz(*kwargs['start_pos'], wait=True)
            logger.warn('Moving sample stage to starting position')

        if not self.wait(stop=True, start=False, timeout=10):
            logger.error('Goniometer is busy. Aborting ')
            return

        # Turn on Front Light
        self.front_light_cmd.put(1)

        # configure device and start scan
        self.set_state(message=f'"{kind}" Scanning ...')
        if kind in ['simple', 'shutterless']:
            kwargs['frames'] = kwargs['frames'] if self.supports(GonioFeatures.GATING) else 1
            misc.set_settings(self.settings, **kwargs)
            self.scan_cmd.put(self.NULL_VALUE)
        elif kind == 'helical':
            start_y, start_cy, start_cx = kwargs.pop('start_pos')
            stop_y, stop_cy, stop_cx = kwargs.pop('end_pos')
            start_z = stop_z = self.gon_z_fbk.get()
            if self.helix_cmd.name.endswith('Ex'):
                kwargs['start'] = (start_y, start_z, start_cx, start_cy)
                kwargs['stop'] = (stop_y, stop_z, stop_cx, stop_cy)
            else:
                kwargs['start'] = f"{start_y:0.5f},{start_z:0.5f},{start_cx:0.5f},{start_cy}:0.5f"
                kwargs['stop'] = f"{stop_y:0.5f},{stop_z:0.5f},{stop_cx:0.5f}, {stop_cy:0.5f}"

            kwargs['frames'] = kwargs['frames'] if self.supports(GonioFeatures.GATING) else 1
            misc.set_settings(self.helix_settings, **kwargs)
            self.helix_cmd.put(self.NULL_VALUE)
        elif kind == 'raster':
            kwargs['snake'] = int(self.grid_settings()['snake'])

            # Scale and convert um to mm
            # MD2 appears to need correction of scan size by -1 in each direction

            w_adj = 1
            #h_adj = 1

            #w_adj = (kwargs['hsteps'] - 0.5)/kwargs['hsteps']
            h_adj = (kwargs['vsteps'] - 1)/kwargs['vsteps']

            kwargs['width'] *= w_adj * 1e-3
            kwargs['height'] *= h_adj * 1e-3
            if self.power_pmac:
                kwargs['time'] *= h_adj
            kwargs['use_table'] = int(self.power_pmac)
            kwargs['shutterless'] = 1

            start_y, start_cy, start_cx = kwargs.pop('start_pos')
            start_z = self.gon_z_fbk.get()
            kwargs['start'] = (start_y, start_z, start_cx, start_cy)

            frames, lines = kwargs.get('hsteps', 1), kwargs.get('vsteps', 1)
            line_size = kwargs['width']

            # frames and lines are inverted for vertical scans on non-powerpmac systems
            if kwargs['width'] < kwargs['height'] and not self.power_pmac:
                frames, lines = kwargs.get('vsteps', 1), kwargs.get('hsteps',1)
                y_offset = kwargs['height']/2
                self.stage.move_screen_by(0, y_offset, 0.0, wait=True)


            if self.power_pmac and self.supports(GonioFeatures.GATING):
                frames, lines = kwargs.get('hsteps', 1) - 1, kwargs.get('vsteps', 1)

            frames = max(frames, 1)
            lines = max(lines, 2)

            # Vertical line on Power is Helical scan instead
            if self.power_pmac and frames == 1:
                origin_x, origin_y, origin_z = self.stage.get_xyz()
                y_offset = kwargs['height']/2
                x_dev, y_dev, z_dev = self.stage.screen_to_xyz(0.0, y_offset, 0.0)
                end_pos = origin_x + x_dev, origin_y + y_dev, origin_z + z_dev
                start_pos = origin_x - x_dev, origin_y - y_dev, origin_z - z_dev

                exposure_time = kwargs['time'] * lines
                scan_range = kwargs['range'] * lines
                frames = 1 if self.supports(GonioFeatures.GATING) else lines
                self.scan(
                    kind='shutterless',
                    time=exposure_time,
                    range=scan_range,
                    angle=self.omega.get_position(),
                    frames=frames,
                    wait=True,
                    start_pos=start_pos,
                    end_pos=end_pos,
                )
                return
            else:
                kwargs['frames'] = frames if self.supports(GonioFeatures.GATING) else 1
                kwargs['lines'] = lines
                kwargs['time'] *= frames
                kwargs['range'] *= frames

                misc.set_settings(self.raster_settings, debug=True, **kwargs)
                self.wait_stop(timeout=60)
                self.raster_cmd.put(self.NULL_VALUE)

        timeout = timeout or (10 + 2 * kwargs['time'])
        msg = f'"{kind}" scan failed!'
        if self.wait(start=True, stop=wait, timeout=timeout):
            msg = f'"{kind}" scan complete!'

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

    def __init__(self, kappa=False, trigger=None):
        super().__init__('SIM Diffractometer')
        if kappa:
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
        self.sample_x = motor.SimMotor('Sample X', 0.0, limits=(-5, 5), units='mm', speed=0.6)
        self.sample_y1 = motor.SimMotor('Sample Y', 0.0, limits=(-2, 2), units='mm', speed=0.6)
        self.sample_y2 = motor.SimMotor('Sample Y', 0.0, limits=(-2, 2), units='mm', speed=0.6)
        self.support_y = motor.SimMotor('Support Y', 0.0, limits=(-5, 5), units='mm', speed=0.6)
        self.support_z = motor.SimMotor('Support Y', 0.0, limits=(-5, 5), units='mm', speed=0.6)

        self.stage = stages.SampleStage(self.sample_x, self.sample_y1, self.sample_y2, self.omega)
        self.support = stages.XYZStage(self.sample_x, self.support_y, self.support_y)

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
            ).tolist()
            if self.supports(GonioFeatures.TRIGGERING):
                logger.debug('starting {} triggers'.format(len(self.trigger_positions)))
                #GLib.timeout_add(int(self._frame_exposure*1000), self.send_triggers)
                GLib.idle_add(self.send_triggers)
            self.omega.move_to(self.settings['angle'] + self.settings['range'] + 0.05, wait=True)
            bl.fast_shutter.close()
            self.omega.configure(speed=config['speed'])
            logger.debug('Scan done at: %s' % datetime.now().isoformat())
            self.set_state(message='Scan complete!', busy=False)
            self._scanning = False

    def send_triggers(self):
        if len(self.trigger_positions):
            self.trigger_positions.pop(0)
            self.trigger.on(self._frame_exposure * 0.5)
        return self._scanning

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
