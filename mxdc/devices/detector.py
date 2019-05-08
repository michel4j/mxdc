import copy
import os
import fnmatch
import random
import shutil
import time
from datetime import datetime


from gi.repository import GObject
from zope.interface import implementer

from mxdc.com import ca
from mxdc.utils import decorators
from mxdc.devices.base import BaseDevice
from mxdc.utils.log import get_module_logger

from .interfaces import IImagingDetector

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)

TEST_IMAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'test')


@implementer(IImagingDetector)
class SimDetector(BaseDevice):
    __gsignals__ = {
        'new-image': (GObject.SIGNAL_RUN_LAST, None, (str,)),
    }

    def __init__(self, name, size, pixel_size=0.073242, images='/archive/staff/school', detector_type="MX300"):
        BaseDevice.__init__(self)
        self.size = int(size), int(size)
        self.resolution = pixel_size
        self.mm_size = self.resolution * min(self.size)
        self.name = name
        self.detector_type = detector_type
        self.shutterless = False
        self.file_extension = 'img'
        self.set_state(active=True, health=(0, ''))
        self.sim_images_src = images
        self._datasets = {}
        self._powders = {}
        self._state = 'idle'
        self._bg_taken = False
        self._stopped = False
        self.prepare_datasets()

    @decorators.async_call
    def prepare_datasets(self):
        self._datasets = {}
        for root, dir, files in os.walk(self.sim_images_src):
            if self._stopped: break
            for file in fnmatch.filter(files, '*_001.img'):
                if self._stopped: break
                key = os.path.join(root, file.replace('_001.', '_{:03d}.'))
                data_root = file.replace('_001.', '_???.')
                data_files = fnmatch.filter(files, data_root)
                if len(data_files) >= 60:
                    self._datasets[key] = len(data_files)
        self._select_dir()

    def initialize(self, wait=True):
        logger.debug('(%s) Initializing CCD ...' % (self.name,))
        time.sleep(0.1)
        logger.debug('(%s) CCD Initialization complete.' % (self.name,))

    def start(self, first=False):
        if first:
            self.initialize(True)
        time.sleep(0.1)

    def stop(self):
        logger.debug('(%s) Stopping CCD ...' % (self.name,))
        time.sleep(0.1)

    def get_origin(self):
        return self.size[0] // 2, self.size[0] // 2

    def _select_dir(self, name='junk'):
        import hashlib
        # always select the same dataset for the same name and date
        name_int  = int(hashlib.sha1(name).hexdigest(), 16) % (10 ** 8)
        chosen = (datetime.today().day + name_int) % len(self._datasets.keys())
        if 'pow' in name:
            chosen = (datetime.today().day + name_int) % len(self._powders.keys())
            self._src_template, self._num_frames = self._powders.items()[chosen]
        else:
            chosen = (datetime.today().day + name_int) % len(self._datasets.keys())
            self._src_template, self._num_frames = self._datasets.items()[chosen]
        if not os.path.exists(self._src_template.format(1)):
            self._src_template = os.path.join(TEST_IMAGES, 'sim_{:04d}.img')
            self._num_frames = 2

    def _copy_frame(self):
        file_parms = copy.deepcopy(self.parameters)
        logger.debug('Saving frame: %s' % datetime.now().isoformat())
        src_img = self._src_template.format(1 + (file_parms['start_frame'] % self._num_frames))
        file_name = '{}_{:04d}.img'.format(file_parms['file_prefix'], file_parms['start_frame'])
        file_path = os.path.join(file_parms['directory'], file_name)
        shutil.copyfile(src_img, file_path)
        logger.debug('Frame saved: %s' % datetime.now().isoformat())
        GObject.idle_add(self.emit, 'new-image', file_path)

    def save(self, wait=False):
        self._copy_frame()

    def delete(self, directory, *frame_list):
        for frame_name in frame_list:
            frame_path = os.path.join(directory, '{}.{}'.format(frame_name, self.file_extension))
            if os.path.exists(frame_path):
                try:
                    os.remove(frame_path)
                except OSError:
                    logger.error('Unable to remove existing frame: {}'.format(frame_name))

    def wait(self, *states):
        time.sleep(0.1)

    def set_parameters(self, data):
        self.parameters = copy.deepcopy(data)
        self._select_dir(name=self.parameters['file_prefix'])

    def cleanup(self):
        self._stopped = True

@implementer(IImagingDetector)
class PilatusDetector(BaseDevice):
    __gsignals__ = {
        'new-image': (GObject.SIGNAL_RUN_LAST, None, (str,)),
    }
    STATES = {
        'acquiring': [1],
        'idle': [0]
    }

    def __init__(self, name, size=(2463, 2527), detector_type='PILATUS 6M', description='PILATUS Detector'):
        super(PilatusDetector, self).__init__()
        self.size = size
        self.resolution = 0.172
        self.mm_size = self.resolution * min(self.size)
        self.name = description
        self.detector_type = detector_type
        self.shutterless = True
        self.file_extension = 'cbf'

        self.acquire_cmd = self.add_pv('{}:Acquire'.format(name), monitor=False)
        self.mode_cmd = self.add_pv('{}:TriggerMode'.format(name), monitor=False)

        self.connected_status = self.add_pv('{}:AsynIO.CNCT'.format(name))
        self.armed_status = self.add_pv("{}:Armed".format(name))
        self.acquire_status = self.add_pv("{}:Acquire".format(name))
        self.energy_threshold = self.add_pv('{}:ThresholdEnergy_RBV'.format(name), monitor=False)
        self.state_value = self.add_pv('{}:DetectorState_RBV'.format(name))
        self.state_msg = self.add_pv('{}:StatusMessage_RBV'.format(name))
        self.command_string = self.add_pv('{}:StringToServer_RBV'.format(name))
        self.response_string = self.add_pv('{}:StringFromServer_RBV'.format(name))
        self.file_format = self.add_pv("{}:FileTemplate".format(name))

        self.saved_frame_num = self.add_pv('{}:ArrayCounter_RBV'.format(name))
        self.saved_frame_num.connect('changed', self.on_new_frame)

        # Data Parameters
        self.settings = {
            'start_frame': self.add_pv("{}:FileNumber".format(name), monitor=False),
            'num_frames': self.add_pv('{}:NumImages'.format(name), monitor=False),
            'file_prefix': self.add_pv("{}:FileName".format(name), monitor=True),
            'directory': self.add_pv("{}:FilePath".format(name), monitor=False),

            'start_angle': self.add_pv("{}:StartAngle".format(name), monitor=False),
            'delta_angle': self.add_pv("{}:AngleIncr".format(name), monitor=False),
            'exposure_time': self.add_pv("{}:AcquireTime".format(name), monitor=False),
            'exposure_period': self.add_pv("{}:AcquirePeriod".format(name), monitor=False),

            'wavelength': self.add_pv("{}:Wavelength".format(name), monitor=False),
            'beam_x': self.add_pv("{}:BeamX".format(name), monitor=False),
            'beam_y': self.add_pv("{}:BeamY".format(name), monitor=False),
            'distance': self.add_pv("{}:DetDist".format(name), monitor=False),
            'axis': self.add_pv("{}:OscillAxis".format(name), monitor=False),
            'two_theta': self.add_pv("{}:Det2theta".format(name), monitor=False),
            'alpha': self.add_pv("{}:Alpha".format(name), monitor=False),
            'kappa': self.add_pv("{}:Kappa".format(name), monitor=False),
            'phi': self.add_pv("{}:Phi".format(name), monitor=False),
            'chi': self.add_pv("{}:Chi".format(name), monitor=False),
            'polarization': self.add_pv("{}:Polarization".format(name), monitor=False),
            'threshold_energy': self.add_pv('{}:ThresholdEnergy'.format(name), monitor=False),

            'comments': self.add_pv('{}:HeaderString'.format(name), monitor=False),
        }

        self.connected_status.connect('changed', self.on_connection_changed)

    def initialize(self, wait=True):
        logger.debug('({}) Initializing Detector ...'.format(self.name))

    def start(self, first=False):
        logger.debug('({}) Starting Acquisition ...'.format(self.name))
        self.wait('idle')
        self.acquire_cmd.put(1, wait=True)
        self.wait('acquiring')

    def stop(self):
        logger.debug('({}) Stopping Detector ...'.format(self.name))
        self.acquire_cmd.put(0)
        self.wait('idle')

    def get_origin(self):
        return self.size[0] // 2, self.size[1] // 2

    def save(self, wait=False):
        return

    def delete(self, directory, *frame_list):
        for frame_name in frame_list:
            frame_path = os.path.join(directory, '{}.{}'.format(frame_name, self.file_extension))
            if os.path.exists(frame_path):
                try:
                    os.remove(frame_path)
                except OSError:
                    logger.error('Unable to remove existing frame: {}'.format(frame_name))

    def on_new_frame(self, obj, frame_number):
        template = self.file_format.get()
        directory = self.settings['directory'].get()
        directory += os.sep if not directory.endswith(os.sep) else ''
        file_path = template % (
            directory,
            self.settings['file_prefix'].get(),
            frame_number
        )
        GObject.idle_add(self.emit, 'new-image', file_path)

    def wait(self, state='idle'):
        return self.wait_for_state(state)

    def set_parameters(self, data):
        params = {}
        params.update(data)

        if not (0.5 * params['energy'] < self.energy_threshold.get() < 0.75 * params['energy']):
            params['threshold_energy'] = round(0.6 * params['energy'], 2)

        params['beam_x'] = self.settings['beam_x'].get()
        params['beam_y'] = self.settings['beam_y'].get()
        params['polarization'] = self.settings['polarization'].get()
        params['exposure_period'] = params['exposure_time']
        params['exposure_time'] -= 0.002

        self.mode_cmd.put(2)  # External Trigger Mode
        for k, v in params.items():
            if k in self.settings:
                time.sleep(0.05)
                self.settings[k].put(v, wait=True)

    def wait_for_state(self, state, timeout=20.0):
        logger.debug('({}) Waiting for state: {}'.format(self.name, state, ))
        while timeout > 0 and not self.is_in_state(state):
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0:
            logger.debug('({}) state {} attained after: {:0.1f} sec'.format(self.name, state, 10 - timeout))
            return True
        else:
            logger.warning('({}) Timed out waiting for state: {}'.format(self.name, state, ))
            return False

    def on_connection_changed(self, obj, state):
        if state == 0:
            self.set_state(health=(4, 'socket', 'Detector disconnected!'))
        else:
            self.set_state(health=(0, 'socket'))

    def wait_in_state(self, state, timeout=60):
        logger.debug('({}) Waiting for state "{}" to expire.'.format(self.name, state, ))
        while self.is_in_state(state) and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0:
            logger.debug('({}) state "{}" expired after: {:0.1f} sec'.format(self.name, state, 10 - timeout))
            return True
        else:
            logger.warning('({}) Timed out waiting for state "{}" to expire'.format(self.name, state, ))
            return False

    def is_in_state(self, state):
        return self.acquire_status.get() in self.STATES.get(state, [])


@implementer(IImagingDetector)
class RayonixDetector(BaseDevice):

    __gsignals__ = {
        'new-image': (GObject.SIGNAL_RUN_LAST, None, (str,)),
    }
    STATES = {
        'init': [8],
        'acquiring': [1],
        'reading': [2],
        'correcting': [3],
        'saving': [4],
        'idle': [0, 6, 10],
        'error': [6, 9],
        'waiting': [7],
        'busy': [1, 2, 3, 4, 5, 7, 8],
    }

    def __init__(self, name, size, detector_type='MX300HE', desc='Rayonix Detector'):
        super(RayonixDetector, self).__init__()
        self.size = size, size
        self.resolution = 0.073242
        self.mm_size = self.resolution * min(self.size)
        self.name = desc
        self.detector_type = detector_type
        self.shutterless = False
        self.file_extension = 'img'
        self.initialized = False

        self.connected_status = self.add_pv('{}:AsynIO.CNCT'.format(name))
        self.acquire_cmd = self.add_pv('{}:Acquire'.format(name), monitor=False)
        self.frame_type = self.add_pv('{}:FrameType'.format(name), monitor=False)
        self.trigger_mode = self.add_pv('{}:TriggerMode'.format(name), monitor=False)
        self.acquire_status = self.add_pv("{}:Acquire_RBV".format(name))
        self.state_value = self.add_pv('{}:DetectorState_RBV'.format(name))
        self.write_status = self.add_pv("{}:MarWritingStatus_RBV".format(name))
        self.command_string = self.add_pv('{}:StringToServer_RBV'.format(name))
        self.response_string = self.add_pv('{}:StringFromServer_RBV'.format(name))
        self.file_format = self.add_pv("{}:FileTemplate".format(name))
        self.saved_filename = self.add_pv('{}:FullFileName_RBV'.format(name))
        self.write_status.connect('changed', self.on_new_frame)
        self.file_format.connect('changed', self.on_new_format)

        # Data Parameters
        self.settings = {
            'start_frame': self.add_pv("{}:FileNumber".format(name), monitor=False),
            'num_frames': self.add_pv('{}:NumImages'.format(name), monitor=False),
            'file_prefix': self.add_pv("{}:FileName".format(name), monitor=True),
            'directory': self.add_pv("{}:FilePath".format(name), monitor=False),

            'wavelength': self.add_pv("{}:Wavelength".format(name), monitor=False),
            'beam_x': self.add_pv("{}:BeamX".format(name), monitor=False),
            'beam_y': self.add_pv("{}:BeamY".format(name), monitor=False),
            'distance': self.add_pv("{}:DetectorDistance".format(name), monitor=False),
            'axis': self.add_pv("{}:RotationAxis".format(name), monitor=False),
            'start_angle': self.add_pv("{}:StartPhi".format(name), monitor=False),
            'delta_angle': self.add_pv("{}:RotationRange".format(name), monitor=False),
            'two_theta': self.add_pv("{}:TwoTheta".format(name), monitor=False),
            'exposure_time': self.add_pv("{}:AcquireTime".format(name), monitor=False),
            'exposure_period': self.add_pv("{}:AcquirePeriod".format(name), monitor=False),

            'comments': self.add_pv('{}:DatasetComments'.format(name), monitor=False),
        }

        self.connected_status.connect('changed', self.on_connection_changed)

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
        self.wait('idle', 'correct', 'saving', 'waiting', 'reading')
        self.acquire_cmd.put(1)
        self.wait('acquiring')

    def stop(self):
        logger.debug('({}) Stopping Detector ...'.format(self.name))
        self.acquire_cmd.put(0)
        self.wait('idle')

    def get_origin(self):
        return self.size[0] // 2, self.size[1] // 2

    def save(self):
        self.acquire_cmd.put(0)

    def delete(self, directory, *frame_list):
        for frame_name in frame_list:
            frame_path = os.path.join(directory, '{}.{}'.format(frame_name, self.file_extension))
            if os.path.exists(frame_path):
                try:
                    os.remove(frame_path)
                except OSError:
                    logger.error('Unable to remove existing frame: {}'.format(frame_name))

    def on_connection_changed(self, obj, state):
        if state == 0:
            self.initialized = False
            self.set_state(health=(4, 'socket', 'Detector disconnected!'))
        else:
            self.set_state(health=(0, 'socket'))

    def on_new_frame(self, obj, state):
        if state == 2:
            file_path = self.saved_filename.get()
            GObject.idle_add(self.emit, 'new-image', file_path)

    def on_new_format(self, obj, format):
        self.file_extension = format.split('.')[-1]

    def wait(self, *states):
        states = states or ('idle',)
        return self.wait_for_state(*states)

    def set_parameters(self, data):
        if not self.initialized:
            self.initialize(True)
        params = {}
        params.update(data)
        for k, v in params.items():
            if k in self.settings:
                time.sleep(0.05)
                self.settings[k].put(v, wait=True)

    def wait_for_state(self, *states, **kwargs):
        timeout = kwargs.get('timeout', 10)
        logger.debug('({}) Waiting for state: {}'.format(self.name, '|'.join(states)))
        while timeout > 0 and not self.is_in_state(*states):
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0:
            logger.debug('({}) state {} attained after: {:0.1f} sec'.format(self.name, '|'.join(states), 10 - timeout))
            return True
        else:
            logger.warning('({}) Timed out waiting for state: {}'.format(self.name, '|'.join(states), ))
            return False

    def wait_in_state(self, *states, **kwargs):
        timeout = kwargs.get('timeout', 60)
        logger.debug('({}) Waiting for state "{}" to expire.'.format(self.name, '|'.join(states), ))
        while self.is_in_state(*states) and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0:
            logger.debug(
                '({}) state "{}" expired after: {:0.1f} sec'.format(self.name, '|'.join(states), 10 - timeout))
            return True
        else:
            logger.warning('({}) Timed out waiting for state "{}" to expire'.format(self.name, '|'.join(states), ))
            return False

    def is_in_state(self, *states):
        return any(self.state_value.get() in self.STATES.get(state, []) for state in states)


@implementer(IImagingDetector)
class ADSCDetector(BaseDevice):
    __gsignals__ = {
        'new-image': (GObject.SIGNAL_RUN_LAST, None, (str,)),
    }
    STATES = {
        'init': [8],
        'acquiring': [1],
        'reading': [2],
        'idle': [0, 4, 5, 6],
        'error': [3],
        'busy': [1, 2],
    }

    def __init__(self, name, size, detector_type='Q315r', pixel_size=0.073242, desc='ADSC Detector'):
        super(ADSCDetector, self).__init__()
        self.size = size, size
        self.resolution = pixel_size
        self.mm_size = self.resolution * min(self.size)
        self.name = desc
        self.detector_type = detector_type
        self.shutterless = False
        self.file_extension = 'img'
        self.initialized = False

        # commands
        self.connected_status = self.add_pv('{}:AsynIO.CNCT'.format(name))
        self.prepare_cmd = self.add_pv('{}:Acquire'.format(name), monitor=False)
        self.acquire_cmd = self.add_pv("{}:ExSwTrCtl".format(name), monitor=True)
        self.reset_cmd = self.add_pv("{}:ADSCSoftReset".format(name), monitor=False)
        self.save_cmd = self.add_pv("{}:WriteFile".format(name), monitor=False)

        # settings and feedback
        self.armed_staus = self.add_pv("{}:ExSwTrOkToExp".format(name))
        self.dezinger_mode = self.add_pv("{}:ADSCDezingr".format(name), monitor=False)
        self.stored_darks = self.add_pv("{}:ADSCStrDrks".format(name), monitor=True)
        self.reuse_dark = self.add_pv("{}:ADSCReusDrk".format(name), monitor=False)
        self.trigger_mode = self.add_pv('{}:TriggerMode'.format(name), monitor=False)

        self.state_value = self.add_pv('{}:ADSCState'.format(name))
        self.file_format = self.add_pv("{}:FileTemplate".format(name))
        self.saved_filename = self.add_pv('{}:FullFileName_RBV'.format(name))

        self.saved_filename.connect('changed', self.on_new_frame)
        self.file_format.connect('changed', self.on_new_format)

        # Data Parameters
        self.settings = {
            'start_frame': self.add_pv("{}:FileNumber".format(name), monitor=False),
            'num_frames': self.add_pv('{}:NumImages'.format(name), monitor=False),
            'file_prefix': self.add_pv("{}:FileName".format(name), monitor=True),
            'directory': self.add_pv("{}:FilePath".format(name), monitor=False),

            'wavelength': self.add_pv("{}:ADSCWavelen".format(name), monitor=False),
            'beam_x': self.add_pv("{}:ADSCBeamX".format(name), monitor=False),
            'beam_y': self.add_pv("{}:ADSCBeamY".format(name), monitor=False),
            'distance': self.add_pv("{}:ADSCDistnce".format(name), monitor=False),
            'axis': self.add_pv("{}:ADSCAxis".format(name), monitor=False),
            'start_angle': self.add_pv("{}:ADSCOmega".format(name), monitor=False),
            'delta_angle': self.add_pv("{}:ADSCImWidth".format(name), monitor=False),
            'two_theta': self.add_pv("{}:ADSC2Theta".format(name), monitor=False),
            'kappa': self.add_pv("{}:ADSCKappa".format(name), monitor=False),
            'phi': self.add_pv("{}:ADSCPhi".format(name), monitor=False),
            'exposure_time': self.add_pv("{}:AcquireTime".format(name), monitor=False),
        }
        self.connected_status.connect('changed', self.on_connection_changed)


    def initialize(self, wait=True):
        logger.debug('({}) Initializing Detector ...'.format(self.name))
        self.initialized = True
        self.trigger_mode.put(1)  # External
        self.reuse_dark.put(1)    # Reuse dark frames for dezingering
        self.dezinger_mode.put(1) # Dezinger images

    def start(self, first=False):
        logger.debug('({}) Starting Acquisition ...'.format(self.name))
        self.wait('idle')
        self.prepare_cmd.put(1)
        self.wait('armed')
        self.acquire_cmd.put(1)
        self.wait('acquiring')

    def stop(self):
        logger.debug('({}) Stopping Detector ...'.format(self.name))
        self.acquire_cmd.put(0)
        self.wait('idle')

    def get_origin(self):
        return self.size[0] // 2, self.size[1] // 2

    def save(self):
        self.acquire_cmd.put(0)

    def delete(self, directory, *frame_list):
        for frame_name in frame_list:
            frame_path = os.path.join(directory, '{}.{}'.format(frame_name, self.file_extension))
            if os.path.exists(frame_path):
                try:
                    os.remove(frame_path)
                except OSError:
                    logger.error('Unable to remove existing frame: {}'.format(frame_name))

    def on_connection_changed(self, obj, state):
        if state == 0:
            self.initialized = False
            self.set_state(health=(4, 'socket', 'Detector disconnected!'))
        else:
            self.set_state(health=(0, 'socket'))

    def on_new_frame(self, obj, path):
        file_path = self.saved_filename.get()
        GObject.idle_add(self.emit, 'new-image', file_path)

    def on_new_format(self, obj, format):
        self.file_extension = format.split('.')[-1]

    def wait(self, *states):
        states = states or ('idle',)
        return self.wait_for_state(*states)

    def set_parameters(self, data):
        if not self.initialized:
            self.initialize(True)
        params = {}
        params.update(data)
        for k, v in params.items():
            if k in self.settings:
                time.sleep(0.05)
                self.settings[k].put(v, wait=True)

    def wait_for_state(self, *states, **kwargs):
        timeout = kwargs.get('timeout', 10)
        logger.debug('({}) Waiting for state: {}'.format(self.name, '|'.join(states)))
        while timeout > 0 and not self.is_in_state(*states):
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0:
            logger.debug('({}) state {} attained after: {:0.1f} sec'.format(self.name, '|'.join(states), 10 - timeout))
            return True
        else:
            logger.warning('({}) Timed out waiting for state: {}'.format(self.name, '|'.join(states), ))
            return False

    def wait_in_state(self, *states, **kwargs):
        timeout = kwargs.get('timeout', 60)
        logger.debug('({}) Waiting for state "{}" to expire.'.format(self.name, '|'.join(states), ))
        while self.is_in_state(*states) and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0:
            logger.debug(
                '({}) state "{}" expired after: {:0.1f} sec'.format(self.name, '|'.join(states), 10 - timeout))
            return True
        else:
            logger.warning('({}) Timed out waiting for state "{}" to expire'.format(self.name, '|'.join(states), ))
            return False

    def is_in_state(self, *states):
        cur_state = self.state_value.get()
        checks = [cur_state in self.STATES.get(state, []) for state in states]
        checks += ['armed' in states and self.armed_staus.get() == 1]  # Armed state is special
        return any(checks)


__all__ = ['SimDetector', 'PilatusDetector', 'RayonixDetector', 'ADSCDetector']
