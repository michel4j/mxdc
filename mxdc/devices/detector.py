import copy
import fnmatch
import glob
import os
import re
import shutil
import time
from datetime import datetime
from enum import Enum

from mxio import read_header
from zope.interface import implementer

from gi.repository import GLib

from mxdc import Signal, Device, Object
from mxdc.utils import decorators
from mxdc.utils import frames
from mxdc.utils.log import get_module_logger
from .interfaces import IImagingDetector

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class States(Enum):
    """
    Detector State Flags
    """
    INITIALIZING = 0  # initializing the detector
    IDLE = 1  # idle and ready to acquire
    ARMED = 2  # Armed and ready for triggers
    ACQUIRING = 3  # Triggered and acquiring images
    STANDBY = 4  # Misc processing in progress eg, readout, corrections, saving etc
    ERROR = 5  # Detector error


class DetectorFeatures(Enum):
    SHUTTERLESS, TRIGGERING = range(2)


class Trigger(Object):
    class Signals:
        high = Signal('high', arg_types=(bool,))

    def is_high(self):
        """
        Check if trigger is in high state
        """
        return self.get_state('high')

    def on(self, duration=-1):
        """
        Activate trigger for given duration

        :keyword duration: duration in milliseconds if negative or zero, stay on indefinitely
        """
        if not self.is_high():
            self.set_state(high=True)
            if duration > 0:
                GLib.timeout_add(duration, self.off)

    def off(self):
        """
        Turn off the trigger
        """
        self.set_state(high=False)


@implementer(IImagingDetector)
class BaseDetector(Device):
    """
    Base class for all imaging detector classes

    Signals:
        - **state**: (object,), Detector state
        - **new-image**: (object,), New image recorded
        - **progress**:  (float, str), Progress fraction and message

    """
    FRAME_DIGITS = 4
    BUSY_STATES = (States.ACQUIRING, States.STANDBY,)  # list of states representing the busy state

    class Signals:
        state = Signal("state", arg_types=(object,))
        new_image = Signal("new-image", arg_types=(object,))
        progress = Signal("progress", arg_types=(float, str))

    def __init__(self):
        super().__init__()
        self.file_extension = 'img'

    def initialize(self, wait=True):
        """
        Initialize the detector
        :param wait: if True, wait for the detector to complete initialization
        """

    def process_frame(self, data):
        """
        Process the frame data from a monitor helper

        :param data: Dataset object to be processed
        """
        self.emit("new-image", data)

    def get_template(self, prefix):
        """
        Given a file name prefix, generate the file name template for the dataset.  This should be
        a format string specification which takes a single parameter `number` representing the file number, or
        no parameter at all, for archive formats like hdf5

        :param prefix: file name prefix
        :return: format string
        """

        return f'{prefix}_{{:0{self.FRAME_DIGITS}d}}.{self.file_extension}'

    def set_state(self, *args, **kwargs):
        # make sure device busy signal is consistent with busy states
        if "state" in kwargs and "busy" not in kwargs:
            kwargs["busy"] = kwargs["state"] in self.BUSY_STATES
        super().set_state(*args, **kwargs)

    def wait_until(self, *states, timeout=20.0):
        """
        Wait for a maximum amount of time until the detector state is one of the specified states, or busy
        if no states are specified.

        :param states: states to check for. Attaining any of the states will terminate the wait
        :param timeout: Maximum time in seconds to wait
        :return: True if state was attained, False if timeout was reached.
        """

        states = states if len(states) else self.BUSY_STATES
        states_text = "|".join((str(s) for s in states))

        logger.debug('"{}" Waiting for {}'.format(self.name, states_text))
        elapsed = 0

        while elapsed <= timeout and self.get_state("state") not in states:
            elapsed += 0.05
            time.sleep(0.05)

        if elapsed <= timeout:
            logger.debug('"{}": {} attained after {:0.2f}s'.format(self.name, self.get_state("state"), elapsed))
            return True
        else:
            logger.warning('"{}" timed-out waiting for "{}"'.format(self.name, states_text))
            return False

    def wait_while(self, *states, timeout=20.0):
        """
        Wait for a maximum amount of time while the detector state is one of the specified states, or not busy
        if no states are specified.

        :param state: states to check for. Attaining a state other than any of the states will terminate the wait
        :param timeout: Maximum time in seconds to wait
        :return: True if state was attained, False if timeout was reached.
        """

        states = states if len(states) else self.BUSY_STATES
        states_text = "|".join([str(state) for state in states])

        logger.debug('"{}" Waiting for {}'.format(self.name, states_text))
        elapsed = 0

        while elapsed <= timeout and self.get_state("state") in states:
            elapsed += 0.05
            time.sleep(0.05)

        if elapsed <= timeout:
            logger.debug('"{}": {} attained after {:0.2f}s'.format(self.name, self.get_state("state"), elapsed))
            return True
        else:
            logger.warning('"{}" timed-out waiting in "{}"'.format(self.name, states_text))
            return False

    def wait(self):
        """
        Wait while the detector is busy.

        :return: True if detector became idle or False if wait timed-out.
        """
        return self.wait_while()

    def delete(self, directory, prefix, frames=()):
        """
        Delete dataset frames given a file name prefix and directory

        :param directory: Directory in which to delete files
        :param prefix:  file name prefix
        :param frames: list of frame numbers.
        """
        template = self.get_template(prefix)
        for frame in frames:
            frame_path = os.path.join(directory, template.format(frame))
            if os.path.exists(frame_path):
                try:
                    os.remove(frame_path)
                except OSError:
                    logger.error('Unable to remove existing frame: {}'.format(frame_path))

    def check(self, directory, prefix, first=1):
        """
        Check the dataset in a given directory and prefix.

        :param directory: Directory in which to check files
        :param prefix:  file name prefix
        :param first: first frame number, defaults to 1
        :return: tuple with the following sequence of values (list, bool), list of existing frame numbers
            True if dataset can be resumed, False otherwise
        """

        file_path = os.path.join(directory, self.get_template(prefix).format(first))

        if os.path.exists(file_path):
            header = read_header(file_path)
            return header.get('dataset', {}).get('sequence', []), True
        return [], False


class SimDetector(BaseDetector):
    """
    Simulated Detector.

    :param name: device name
    :param size: detector size tuple in pixels
    :param pixel_size: pixel width in microns
    :param images: directory to look for images
    :param trigger: trigger object shared with goniometer

    """
    DETECTOR_TYPES = {
        'img': 'MX300',
        'cbf': 'PILATUS 6M'
    }

    FRAME_DIGITS = 5

    def __init__(self, name, size, pixel_size=0.073242, images='/tmp', extension='cbf', trigger=None):
        super().__init__()
        self.monitor = frames.FileMonitor(self)

        self.size = size
        self.resolution = pixel_size
        self.mm_size = self.resolution * min(self.size)
        self.name = name
        self.detector_type = self.DETECTOR_TYPES.get(extension, 'MX300')
        self.file_extension = extension
        self.set_state(active=True, health=(0, '', ''), state=States.IDLE)
        self.sim_images_src = images
        self._datasets = {}
        self.parameters = {}
        self._powders = {}
        self._state = 'idle'
        self._bg_taken = False
        self._stopped = False
        self.trigger = trigger
        self.trigger_count = 0
        self.prepare_datasets()
        if trigger is not None:
            self.add_features(DetectorFeatures.TRIGGERING, DetectorFeatures.SHUTTERLESS)
            self.trigger.connect('high', self.on_trigger )

    def save(self, wait=False):
        if not self.supports(DetectorFeatures.TRIGGERING):
            self._copy_frame()
        self.set_state(state=States.IDLE)

    def configure(self, **kwargs):
        self.parameters = copy.deepcopy(kwargs)
        self._select_dir(name=self.parameters['file_prefix'])

    def cleanup(self):
        self._stopped = True

    def start(self, first=False):
        if first:
            self.initialize(True)
        time.sleep(0.1)
        self.trigger_count = 0
        self.set_state(state=States.ACQUIRING)

    def stop(self):
        logger.debug('(%s) Stopping CCD ...' % (self.name,))
        time.sleep(0.1)

    def get_origin(self):
        return self.size[0] // 2, self.size[0] // 2

    def on_trigger(self, trigger, high):
        if high and self.get_state('state') in [States.ACQUIRING, States.ARMED]:
            self._copy_frame()
        else:
            self.trigger_count += 1
            logger.debug(f'Received trigger for frame: {self.trigger_count}')

    def _select_dir(self, name='junk'):
        import hashlib

        self._num_frames = 2

        # always select the same dataset for the same name
        name_int = int(hashlib.sha1(name.encode('utf8')).hexdigest(), 16) % (10 ** 8)
        if 'pow' in name:
            num_datasets = len(self._powders.keys())
            if num_datasets:
                chosen = (datetime.today().day + name_int) % num_datasets
                self._src_template, self._num_frames = list(self._powders.items())[chosen]
        else:
            num_datasets = len(self._datasets.keys())
            if num_datasets:
                chosen = (datetime.today().day + name_int) % num_datasets
                self._src_template, self._num_frames = list(self._datasets.items())[chosen]

    def _copy_frame(self):
        file_parms = copy.deepcopy(self.parameters)
        logger.debug('Saving frame: {}'.format(datetime.now().isoformat()))
        frame_number = file_parms['start_frame'] + self.trigger_count
        src_img = self._src_template.format(1 + (frame_number % self._num_frames))
        file_name = '{}_{:05d}.{}'.format(file_parms['file_prefix'], frame_number, self.file_extension)
        file_path = os.path.join(file_parms['directory'], file_name)
        shutil.copyfile(src_img, file_path)
        logger.debug('Frame saved: {}'.format(datetime.now().isoformat()))
        self.monitor.add(file_path)

        # progress
        num_frames = self.parameters['num_frames']
        self.set_state(progress=((1 + self.trigger_count)/num_frames, 'frames acquired'))

    @decorators.async_call
    def prepare_datasets(self):
        self._datasets = {}
        for root, dir, files in os.walk(self.sim_images_src):
            if self._stopped: break
            data_files = sorted(fnmatch.filter(files, f'*_*.{self.file_extension}'))
            for file in data_files:
                if self._stopped: break
                key = os.path.join(root, file.replace('_0001.', '_{:04d}.'))
                if len(data_files) >= 60:
                    self._datasets[key] = len(data_files)
        self._select_dir()


class ADGenericMixin(object):
    """
    Common methods for AreaDetector type detectors
    """

    def on_state_value(self, obj, value):
        state = {
            0: States.IDLE,
            1: States.ACQUIRING,
            2: States.ACQUIRING,
            3: States.STANDBY,
            4: States.STANDBY,
            5: States.STANDBY,
            6: States.ERROR,
            7: States.STANDBY,
            8: States.INITIALIZING,
            9: States.ERROR,
            10: States.IDLE,
        }.get(value, States.IDLE)
        self.set_state(state=state)


class ADDectrisMixin(object):
    """
    Common methods for Dectris AreaDetector type detectors
    """

    def on_state_value(self, obj, value):
        detector_state = self.state_value.get()
        armed = self.armed_status.get()

        state = {
            0: States.IDLE,
            1: States.ACQUIRING,
            2: States.ACQUIRING,
            3: States.ACQUIRING,
            4: States.ACQUIRING,
            5: States.ACQUIRING,
            6: States.IDLE,
            7: States.ACQUIRING,
            8: States.INITIALIZING,
            9: States.ERROR,
            10: States.IDLE,
        }.get(detector_state, States.IDLE)

        if armed == 1:
            state = States.ARMED
        self.set_state(state=state)


class RayonixDetector(ADGenericMixin, BaseDetector):
    """
    Rayonix Detector devices controlled through the AreaDetector MarCCD EPICS driver.

    :param name: Root process variable name
    :param size: detector size tuple in pixels
    :param detector_type: string representing the detector type, e.g. 'MX300HE'
    :param desc: String description of detector
    """

    def __init__(self, name, size, detector_type='MX300HE', desc='Rayonix Detector'):
        super().__init__()
        self.file_extension = 'img'
        self.monitor = frames.FileMonitor(self)

        self.size = size, size
        self.resolution = 0.073242
        self.mm_size = self.resolution * min(self.size)
        self.name = desc
        self.detector_type = detector_type
        self.initialized = False

        self.connected_status = self.add_pv('{}:AsynIO.CNCT'.format(name))
        self.acquire_cmd = self.add_pv('{}:Acquire'.format(name))
        self.frame_type = self.add_pv('{}:FrameType'.format(name))
        self.trigger_mode = self.add_pv('{}:TriggerMode'.format(name))
        self.acquire_status = self.add_pv("{}:Acquire_RBV".format(name))
        self.state_value = self.add_pv('{}:DetectorState_RBV'.format(name))
        self.write_status = self.add_pv("{}:MarWritingStatus_RBV".format(name))
        self.command_string = self.add_pv('{}:StringToServer_RBV'.format(name))
        self.response_string = self.add_pv('{}:StringFromServer_RBV'.format(name))
        self.file_format = self.add_pv("{}:FileTemplate".format(name))
        self.saved_filename = self.add_pv('{}:FullFileName_RBV'.format(name))

        self.write_status.connect('changed', self.on_new_frame)
        self.state_value.connect('changed', self.on_state_value)
        self.connected_status.connect('changed', self.on_connection_changed)

        # Data Parameters
        self.settings = {
            'start_frame': self.add_pv("{}:FileNumber".format(name)),
            'num_frames': self.add_pv('{}:NumImages'.format(name)),
            'file_prefix': self.add_pv("{}:FileName".format(name)),
            'directory': self.add_pv("{}:FilePath".format(name)),

            'wavelength': self.add_pv("{}:Wavelength".format(name)),
            'beam_x': self.add_pv("{}:BeamX".format(name)),
            'beam_y': self.add_pv("{}:BeamY".format(name)),
            'distance': self.add_pv("{}:DetectorDistance".format(name)),
            'axis': self.add_pv("{}:RotationAxis".format(name)),
            'start_angle': self.add_pv("{}:StartPhi".format(name)),
            'delta_angle': self.add_pv("{}:RotationRange".format(name)),
            'two_theta': self.add_pv("{}:TwoTheta".format(name)),
            'exposure_time': self.add_pv("{}:AcquireTime".format(name)),
            'exposure_period': self.add_pv("{}:AcquirePeriod".format(name)),

            'comments': self.add_pv('{}:DatasetComments'.format(name)),
        }

    def initialize(self, wait=True):
        logger.debug('({}) Initializing Detector ...'.format(self.name))
        self.initialized = True
        self.frame_type.put(1)
        self.trigger_mode.put(0)

        self.start()
        time.sleep(5)
        self.frame_type.put(0)
        self.trigger_mode.put(1)

    def start(self, first=False):
        logger.debug('({}) Starting Acquisition ...'.format(self.name))
        self.wait_until(States.IDLE, States.STANDBY)
        self.acquire_cmd.put(1)
        self.wait_until(States.ACQUIRING)

    def stop(self):
        logger.debug('({}) Stopping Detector ...'.format(self.name))
        self.acquire_cmd.put(0)
        self.wait_until(States.IDLE)

    def get_origin(self):
        return self.size[0] // 2, self.size[1] // 2

    def get_template(self, prefix):
        extension = self.file_format.get().split('.')[-1]
        return f'{prefix}_{{:0{self.FRAME_DIGITS}d}}.{extension}'

    def save(self):
        self.acquire_cmd.put(0)

    def on_connection_changed(self, obj, state):
        if state == 0:
            self.initialized = False
            self.set_state(health=(4, 'socket', 'Detector disconnected!'))
        else:
            self.set_state(health=(0, 'socket', ''))

    def on_new_frame(self, obj, state):
        if state == 2:
            file_path = self.saved_filename.get()
            self.monitor.add(file_path)

    def configure(self, **kwargs):
        if not self.initialized:
            self.initialize(True)
        params = {}
        params.update(kwargs)
        for k, v in list(params.items()):
            if k in self.settings:
                time.sleep(0.05)
                self.settings[k].put(v, wait=True)


class ADSCDetector(ADGenericMixin, BaseDetector):
    """
    ADSC Detector devices for the AreaDetector EPICS driver.

    :param name: Root process variable name
    :param size: detector size tuple in pixels
    :param detector_type: detector type string e.g. 'Q315r',
    :param pixel_size': width of a pixel in microns,
    :param desc: String description of detector
    """

    def __init__(self, name, size, detector_type='Q315r', pixel_size=0.073242, desc='ADSC Detector'):
        super().__init__()
        self.file_extension = 'img'
        self.monitor = frames.FileMonitor(self)

        self.size = size, size
        self.resolution = pixel_size
        self.mm_size = self.resolution * min(self.size)
        self.name = desc
        self.detector_type = detector_type
        self.initialized = False

        # commands
        self.connected_status = self.add_pv('{}:AsynIO.CNCT'.format(name))
        self.prepare_cmd = self.add_pv('{}:Acquire'.format(name))
        self.acquire_cmd = self.add_pv("{}:ExSwTrCtl".format(name))
        self.reset_cmd = self.add_pv("{}:ADSCSoftReset".format(name))
        self.save_cmd = self.add_pv("{}:WriteFile".format(name))

        # settings and feedback
        self.armed_staus = self.add_pv("{}:ExSwTrOkToExp".format(name))
        self.dezinger_mode = self.add_pv("{}:ADSCDezingr".format(name))
        self.stored_darks = self.add_pv("{}:ADSCStrDrks".format(name))
        self.reuse_dark = self.add_pv("{}:ADSCReusDrk".format(name))
        self.trigger_mode = self.add_pv('{}:TriggerMode'.format(name))

        self.state_value = self.add_pv('{}:ADSCState'.format(name))
        self.file_format = self.add_pv("{}:FileTemplate".format(name))
        self.saved_filename = self.add_pv('{}:FullFileName_RBV'.format(name))

        self.saved_filename.connect('changed', self.on_new_frame)
        self.state_value.connect('changed', self.on_state_value)
        self.connected_status.connect('changed', self.on_connection_changed)

        # Data Parameters
        self.settings = {
            'start_frame': self.add_pv("{}:FileNumber".format(name)),
            'num_frames': self.add_pv('{}:NumImages'.format(name)),
            'file_prefix': self.add_pv("{}:FileName".format(name)),
            'directory': self.add_pv("{}:FilePath".format(name)),

            'wavelength': self.add_pv("{}:ADSCWavelen".format(name)),
            'beam_x': self.add_pv("{}:ADSCBeamX".format(name)),
            'beam_y': self.add_pv("{}:ADSCBeamY".format(name)),
            'distance': self.add_pv("{}:ADSCDistnce".format(name)),
            'axis': self.add_pv("{}:ADSCAxis".format(name)),
            'start_angle': self.add_pv("{}:ADSCOmega".format(name)),
            'delta_angle': self.add_pv("{}:ADSCImWidth".format(name)),
            'two_theta': self.add_pv("{}:ADSC2Theta".format(name)),
            'kappa': self.add_pv("{}:ADSCKappa".format(name)),
            'phi': self.add_pv("{}:ADSCPhi".format(name)),
            'exposure_time': self.add_pv("{}:AcquireTime".format(name)),
        }

    def initialize(self, wait=True):
        logger.debug('({}) Initializing Detector ...'.format(self.name))
        self.initialized = True
        self.trigger_mode.put(1)  # External
        self.reuse_dark.put(1)  # Reuse dark frames for dezingering
        self.dezinger_mode.put(1)  # Dezinger images

    def start(self, first=False):
        logger.debug('({}) Starting Acquisition ...'.format(self.name))
        self.wait_until(States.IDLE)
        self.prepare_cmd.put(1)
        self.wait_until(States.ARMED)
        self.acquire_cmd.put(1)
        self.wait_until(States.ACQUIRING)

    def stop(self):
        logger.debug('({}) Stopping Detector ...'.format(self.name))
        self.acquire_cmd.put(0)
        self.wait_until(States.IDLE)

    def get_origin(self):
        return self.size[0] // 2, self.size[1] // 2

    def get_template(self, prefix):
        extension = self.file_format.get().split('.')[-1]
        return f'{prefix}_{{:0{self.FRAME_DIGITS}d}}.{extension}'

    def save(self):
        self.acquire_cmd.put(0)

    def on_connection_changed(self, obj, state):
        if state == 0:
            self.initialized = False
            self.set_state(health=(4, 'socket', 'Detector disconnected!'))
        else:
            self.set_state(health=(0, 'socket', ''))

    def on_new_frame(self, obj, path):
        file_path = self.saved_filename.get()
        self.monitor.add(file_path)

    def configure(self, **kwargs):
        if not self.initialized:
            self.initialize(True)
        params = {}
        params.update(kwargs)
        for k, v in list(params.items()):
            if k in self.settings:
                time.sleep(0.05)
                self.settings[k].put(v, wait=True)


class PilatusDetector(ADDectrisMixin, BaseDetector):
    """
    Pilatus Detector devices from DECTRIS controlled through the AreaDetector Pilaltus EPICS driver.

    :param name: Root process variable name
    :param size: detector size tuple in pixels
    :param detector_type: string representing the detector type, e.g. 'PILATUS 6M'
    :param description: String escription of detector
    """

    READOUT_TIME = 0.0025  # minimum readout time

    def __init__(self, name, size=(2463, 2527), detector_type='PILATUS 6M', description='PILATUS Detector'):
        super().__init__()
        self.detector_type = detector_type
        self.add_features(DetectorFeatures.SHUTTERLESS, DetectorFeatures.TRIGGERING)
        self.monitor = frames.FileMonitor(self)

        self.size = size
        self.resolution = 0.172
        self.mm_size = self.resolution * min(self.size)
        self.name = description

        self.acquire_cmd = self.add_pv('{}:Acquire'.format(name))
        self.mode_cmd = self.add_pv('{}:TriggerMode'.format(name))

        self.connected_status = self.add_pv('{}:AsynIO.CNCT'.format(name))
        self.armed_status = self.add_pv("{}:Armed".format(name))
        self.acquire_status = self.add_pv("{}:Acquire".format(name))
        self.energy_threshold = self.add_pv('{}:ThresholdEnergy_RBV'.format(name))
        self.energy = self.add_pv(f'{name}:Energy_RBV')
        self.state_value = self.add_pv('{}:DetectorState_RBV'.format(name))
        self.state_msg = self.add_pv('{}:StatusMessage_RBV'.format(name))
        self.command_string = self.add_pv('{}:StringToServer_RBV'.format(name))
        self.response_string = self.add_pv('{}:StringFromServer_RBV'.format(name))
        self.file_format = self.add_pv("{}:FileTemplate".format(name))
        self.saved_frame_fbk = self.add_pv('{}:ArrayCounter_RBV'.format(name))
        self.saved_frame = self.add_pv('{}:ArrayCounter'.format(name))

        self.saved_frame_fbk.connect('changed', self.on_new_frame)
        self.state_value.connect('changed', self.on_state_value)
        self.armed_status.connect('changed', self.on_state_value)
        self.connected_status.connect('changed', self.on_connection_changed)

        # Data Parameters
        self.settings = {
            'start_frame': self.add_pv("{}:FileNumber".format(name)),
            'num_frames': self.add_pv('{}:NumImages'.format(name)),
            'file_prefix': self.add_pv("{}:FileName".format(name)),
            'directory': self.add_pv("{}:FilePath".format(name)),

            'start_angle': self.add_pv("{}:StartAngle".format(name)),
            'delta_angle': self.add_pv("{}:AngleIncr".format(name)),
            'exposure_time': self.add_pv("{}:AcquireTime".format(name)),
            'exposure_period': self.add_pv("{}:AcquirePeriod".format(name)),

            'wavelength': self.add_pv("{}:Wavelength".format(name)),
            'beam_x': self.add_pv("{}:BeamX".format(name)),
            'beam_y': self.add_pv("{}:BeamY".format(name)),
            'distance': self.add_pv("{}:DetDist".format(name)),
            'axis': self.add_pv("{}:OscillAxis".format(name)),
            'two_theta': self.add_pv("{}:Det2theta".format(name)),
            'alpha': self.add_pv("{}:Alpha".format(name)),
            'kappa': self.add_pv("{}:Kappa".format(name)),
            'phi': self.add_pv("{}:Phi".format(name)),
            'chi': self.add_pv("{}:Chi".format(name)),
            'polarization': self.add_pv("{}:Polarization".format(name)),
            'threshold_energy': self.add_pv('{}:ThresholdEnergy'.format(name)),
            'energy': self.add_pv(f'{name}:Energy'),
            'comments': self.add_pv('{}:HeaderString'.format(name)),
        }

    def initialize(self, wait=True):
        logger.debug('({}) Initializing Detector ...'.format(self.name))

    def start(self, first=False):
        logger.debug('({}) Starting Acquisition ...'.format(self.name))
        self.acquire_cmd.put(1)
        self.wait_until(States.ARMED)

    def stop(self):
        logger.debug('({}) Stopping Detector ...'.format(self.name))
        self.acquire_cmd.put(0)
        self.wait_until(States.IDLE)

    def get_origin(self):
        return self.size[0] // 2, self.size[1] // 2

    def get_template(self, prefix):
        extension = self.file_format.get().split('.')[-1]
        return f'{prefix}_{{:0{self.FRAME_DIGITS}d}}.{extension}'

    def save(self, wait=False):
        logger.debug('({}) Acquisition completed ...'.format(self.name))
        self.wait_until(States.IDLE)

    def on_new_frame(self, obj, frame_number):
        if frame_number > 0:
            template = self.file_format.get()
            directory = self.settings['directory'].get()
            directory += os.sep if not directory.endswith(os.sep) else ''
            file_path = template % (
                directory,
                self.settings['file_prefix'].get(),
                frame_number
            )
            self.monitor.add(file_path)

            # progress
            num_frames = self.settings['num_frames'].get()
            self.set_state(progress=(frame_number / num_frames, 'frames acquired'))

    def configure(self, **kwargs):
        params = {}
        params.update(kwargs)

        if 'energy' in params and abs(params['energy'] - self.energy.get()) < 0.1:
            del params['energy']  # do not set energy if within 100 eV of current value

        params['beam_x'] = self.settings['beam_x'].get()
        params['beam_y'] = self.settings['beam_y'].get()
        params['polarization'] = self.settings['polarization'].get()
        params['exposure_period'] = params['exposure_time']
        params['exposure_time'] -= self.READOUT_TIME

        for k, v in list(params.items()):
            if k in self.settings:
                time.sleep(0.05)
                self.settings[k].put(v, wait=True)

        self.mode_cmd.put(3)  # External Multi-Trigger Mode
        self.saved_frame.put(0)  # reset frame counter

    def on_connection_changed(self, obj, state):
        if state == 0:
            self.set_state(health=(4, 'socket', 'Detector disconnected!'))
        else:
            self.set_state(health=(0, 'socket', ''))


class EigerDetector(ADDectrisMixin, BaseDetector):
    """
    Eiger Detector devices from DECTRIS controlled through the AreaDetector EPICS driver.

    :param name: Root process variable name
    :param stream: address of the ZMQ stream API
    :param size: detector size tuple in pixels
    :param description: String description of detector
    """

    detector_type = 'Eiger'

    def __init__(self, name, stream, size=(3110, 3269), description='Eiger'):
        super().__init__()
        self.add_features(DetectorFeatures.SHUTTERLESS, DetectorFeatures.TRIGGERING)
        self.monitor = frames.StreamMonitor(self, address=stream)
        self.monitor.connect('progress', self.on_data_progress)

        self.size = size
        self.resolution = 0.075
        self.mm_size = self.resolution * min(self.size)
        self.name = description
        self.initialized = False

        self.acquire_cmd = self.add_pv('{}:Acquire'.format(name))
        self.mode_cmd = self.add_pv('{}:TriggerMode'.format(name))

        self.connected_status = self.add_pv('{}:AsynIO.CNCT'.format(name))
        self.armed_status = self.add_pv("{}:Armed".format(name))

        self.energy_threshold = self.add_pv('{}:ThresholdEnergy_RBV'.format(name))
        self.state_value = self.add_pv('{}:DetectorState_RBV'.format(name))
        self.state_msg = self.add_pv('{}:StatusMessage_RBV'.format(name))
        self.command_string = self.add_pv('{}:StringToServer_RBV'.format(name))
        self.response_string = self.add_pv('{}:StringFromServer_RBV'.format(name))
        self.file_format = self.add_pv("{}:FileTemplate".format(name))

        self.saved_frame_num = self.add_pv('{}:NumImagesCounter_RBV'.format(name))
        self.num_images = self.add_pv('{}:NumImages'.format(name))

        self.state_value.connect('changed', self.on_state_value)
        self.armed_status.connect('changed', self.on_state_value)
        self.connected_status.connect('changed', self.on_connection_changed)

        # Data Parameters
        self.settings = {
            'start_frame': self.add_pv("{}:FileNumber".format(name)),
            'num_frames': self.add_pv('{}:NumTriggers'.format(name)),
            'file_prefix': self.add_pv("{}:FWNamePattern".format(name)),
            'batch_size': self.add_pv("{}:FWNImagesPerFile".format(name)),
            'directory': self.add_pv("{}:FilePath".format(name)),

            'start_angle': self.add_pv("{}:OmegaStart".format(name)),
            'delta_angle': self.add_pv("{}:OmegaIncr".format(name)),
            'exposure_time': self.add_pv("{}:AcquireTime".format(name)),
            'acquire_period': self.add_pv("{}:AcquirePeriod".format(name)),

            'wavelength': self.add_pv(f"{name}:Wavelength"),
            'beam_x': self.add_pv(f"{name}:BeamX"),
            'beam_y': self.add_pv(f"{name}:BeamY"),
            'distance': self.add_pv(f"{name}:DetDist"),
            'two_theta': self.add_pv(f"{name}:TwoThetaStart"),
            'kappa': self.add_pv(f"{name}:KappaStart"),
            'phi': self.add_pv(f"{name}:PhiStart"),
            'chi': self.add_pv(f"{name}:ChiStart"),
            # 'energy': self.add_pv('{}:PhotonEnergy'.format(name)),
            # 'threshold_energy': self.add_pv('{}:ThresholdEnergy'.format(name)),
        }

    def start(self, first=False):
        logger.debug(f'"{self.name}" Arming detector ...')
        self.monitor.start()
        self.acquire_cmd.put(1)
        self.wait_until(States.ARMED)

    def stop(self):
        logger.debug('"{}" Disarming detector ...'.format(self.name))
        self.acquire_cmd.put(0)
        self.wait_until(States.IDLE)

    def get_origin(self):
        return self.size[0] // 2, self.size[1] // 2

    def get_template(self, prefix):
        return f'{prefix}_master.h5'

    def save(self, wait=False):
        time.sleep(2)
        self.acquire_cmd.put(0)
        return

    def delete(self, directory, prefix, frames=()):
        master_file = self.get_template(prefix)
        data_glob = re.sub(r'master', 'data_*', master_file)
        dataset_files = [
                            os.path.join(directory, master_file)
                        ] + glob.glob(os.path.join(directory, data_glob))
        for file_path in dataset_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    logger.error('Unable to remove existing frame: {}'.format(file_path))

    def configure(self, **kwargs):
        params = {}
        params.update(kwargs)

        if not (0.5 * params['energy'] < self.energy_threshold.get() < 0.75 * params['energy']):
            params['threshold_energy'] = round(0.5 * params['energy'], 2)

        params['beam_x'] = self.settings['beam_x'].get()
        params['beam_y'] = self.settings['beam_y'].get()
        params['acquire_period'] = params['exposure_time']

        self.mode_cmd.put(3)  # External Trigger Mode
        self.num_images.put(1)

        for k, v in list(params.items()):
            if k in self.settings:
                self.settings[k].put(v, wait=True)

    def on_connection_changed(self, obj, state):
        if state == 0:
            self.set_state(health=(4, 'socket', 'Detector disconnected!'))
        else:
            self.set_state(health=(0, 'socket', ''))

    def on_data_progress(self, monitor, fraction, message):
        """
        Route progress messages from monitor to the device

        :param monitor:  Monitor which triggered the progress
        :param fraction: fraction complete
        :param message:  text message
        """
        self.set_state(progress=(fraction, message))


__all__ = ['SimDetector', 'PilatusDetector', 'RayonixDetector', 'ADSCDetector', 'EigerDetector']
