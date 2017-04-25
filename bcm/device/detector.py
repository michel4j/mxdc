import os
import re
import glob
import random
import shutil
import time
from datetime import datetime
import gobject
from bcm.device.base import BaseDevice
from bcm.device.interfaces import IImagingDetector
from bcm.protocol import ca
from bcm.utils.log import get_module_logger
from zope.interface import implements
from bcm.utils import runlists

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

DELETE_SUFFIX = '.DELETE'


class MXCCDImager(BaseDevice):
    """MX Detector object for EPICS based Rayonix CCD detectors at the CLS."""
    implements(IImagingDetector)
    __gsignals__ = {
        'new-image': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
    }

    def __init__(self, name, size, resolution, detector_type='MX300'):
        """
        Args:
            `name` (str): Root name of the EPICS record Process Variables.
            `size` (int): The size in pixels of the detector. Assumes square 
            detectors.
            `resolueion` (float): The pixel size in 
        
        Kwargs:
            `detector_type` (str): The dialog_type of detector. e.g. "MX300" for Rayonix
            MX CCD 300.
        """

        BaseDevice.__init__(self)
        self.size = int(size), int(size)
        self.resolution = float(resolution)
        self.detector_type = detector_type
        self.name = '%s Detector' % detector_type
        self.shutterless = False
        self.file_extension = 'img'

        self._start_cmd = self.add_pv("%s:start:cmd" % name, monitor=False)
        self._abort_cmd = self.add_pv("%s:abort:cmd" % name, monitor=False)
        self._readout_cmd = self.add_pv("%s:readout:cmd" % name, monitor=False)
        self._reset_cmd = self.add_pv("%s:resetStates:cmd" % name, monitor=False)
        self._writefile_cmd = self.add_pv("%s:writefile:cmd" % name, monitor=False)
        self._background_cmd = self.add_pv("%s:dezFrm:cmd" % name, monitor=False)
        self._save_cmd = self.add_pv("%s:rdwrOut:cmd" % name, monitor=False)
        self._collect_cmd = self.add_pv("%s:frameCollect:cmd" % name, monitor=False)
        self._header_cmd = self.add_pv("%s:header:cmd" % name, monitor=False)
        self._readout_flag = self.add_pv("%s:readout:flag" % name, monitor=False)
        self._dezinger_flag = self.add_pv("%s:dez:flag" % name, monitor=False)
        self._dezinger_cmd = self.add_pv("%s:dezinger:cmd" % name, monitor=False)
        self._connection_state = self.add_pv('%s:sock:state' % name)

        # Header parameters
        self.settings = {
            'filename': self.add_pv("%s:img:filename" % name, monitor=True),
            'directory': self.add_pv("%s:img:dirname" % name, monitor=False),
            'beam_x': self.add_pv("%s:beam:x" % name, monitor=False),
            'beam_y': self.add_pv("%s:beam:y" % name, monitor=False),
            'distance': self.add_pv("%s:distance" % name, monitor=False),
            'exposure_time': self.add_pv("%s:exposureTime" % name, monitor=False),
            'axis': self.add_pv("%s:rot:axis" % name, monitor=False),
            'wavelength': self.add_pv("%s:src:wavelgth" % name, monitor=False),
            'delta_angle': self.add_pv("%s:omega:incr" % name, monitor=False),
            'frame_number': self.add_pv("%s:startFrame" % name, monitor=False),
            'frame_name': self.add_pv("%s:img:prefix" % name, monitor=False),
            'start_angle': self.add_pv("%s:start:omega" % name, monitor=False),
            'energy': self.add_pv("%s:runEnergy" % name, monitor=False),
            'comments': self.add_pv('%s:dataset:cmnts' % name, monitor=False),
        }

        # Status parameters
        self._state_string = '00000000'
        self._state = self.add_pv("%s:rawState" % name)
        self._state_bits = ['None', 'queue', 'exec', 'queue+exec', 'err', 'queue+err', 'exec+err', 'queue+exec+err',
                            'unused']
        self._state_names = ['unused', 'unused', 'dezinger', 'write', 'correct', 'read', 'acquire', 'state']
        self._bg_taken = False
        self._state_list = []

        self._state.connect('changed', self.on_state_change)
        self._connection_state.connect('changed', self.on_connection_changed)
        self.settings['filename'].connect('changed', self.on_new_frame)

    def initialize(self, wait=True):
        """Initialize the detector and take background images if necessary. This
        method does not do anything if the device is already initialized.
        
        Kwargs:
            `wait` (bool): If true, the call will block until initialization is
            complete.
        """
        if not self._bg_taken:
            _logger.debug('(%s) Initializing CCD ...' % (self.name,))
            self.take_background()
            self._bg_taken = True

    def start(self, first=False):
        """Start acquiring.
        
        Kwargs:
            `first` (bool): Specifies whether this is the first of a series of
            acquisitions. This is used to customize the behaviour for the first.
        """
        self.initialize(True)
        if not first:
            self.wait_in_state('acquire:queue')
            self.wait_in_state('acquire:exec')
            # self.wait_for_state('correct:exec')
        _logger.debug('(%s) Starting CCD acquire ...' % (self.name,))
        self._start_cmd.put(1)
        self.wait_for_state('acquire:exec')

    def stop(self):
        """Stop and Abort the current acquisition."""
        _logger.debug('(%s) Stopping CCD ...' % (self.name,))
        self._abort_cmd.put(1)
        #self.wait_for_state('idle')

    def save(self, wait=False):
        """Save the current buffers according to the current parameters.
        
        Kwargs:
            `wait` (bool): If true, the call will block until the save operation
            is complete.
        """

        _logger.debug('(%s) Starting CCD readout ...' % (self.name,))
        self._readout_flag.put(0)
        ca.flush()
        self._save_cmd.put(1)
        if wait:
            self.wait_for_state('read:exec')

    def delete(self, directory, *frame_list):
        for frame_name in frame_list:
            frame_path = os.path.join(directory, '{}.{}'.format(frame_name, self.file_extension))
            if os.path.exists(frame_path):
                try:
                    os.rename(frame_path, frame_path + DELETE_SUFFIX)
                except OSError:
                    _logger.error('Unable to remove existing frame: {}'.format(frame_name))

    def get_origin(self):
        """Obtain the detector origin/beam position in pixels.
        
        Returns:
            tuple(x, y) corresponding to the beam-x and beam-y coordinates.
        """
        return self.settings['beam_x'].get(), self.settings['beam_y'].get()

    def wait(self, state='idle'):
        """Wait until the detector reaches a given state.
        
        Kwargs:
            `state` (str): The state to wait for. Default 'idle'.
        """
        self.wait_for_state(state, timeout=10.0)

    def set_parameters(self, data):
        """Set the detector parameters for the image header and file names.
        
        Args:
            `data` (info): A dictionary of key value pairs for the parameters.
            supported parameters are:
            
                - `filename` (str), Output file name of the image.
                - `directory` (str), Directory name to store image.  
                - `beam_x` (int), Detector X-origin in pixels.  
                - `beam_y` (int), Detector Y-origin in pixels.
                - `distance` (float), Detector distance in mm.
                - `exposure_time` , Exposure time in seconds.
                - `axis` (str), Spindle rotation axis.
                - `wavelength` (float),  Wavelength of radiation in Angstroms.
                - `delta_angle` (float), Delta oscillation angle in deg.
                - `frame_number` (int), Frame number.
                - `name` (str), File name prefix for the image.
                - `start_angle` (float), Starting spindle position of image in deg.
                - `energy` (float), Wavelength of radiation in KeV.
                - `comments` (str), File comments.
                         
        """
        data['filename'] = '{}.{}'.format(data['frame_name'], self.file_extension)
        for key in data.keys():
            if key in self.settings:
                self.settings[key].set(data[key])

        self._header_cmd.put(1)

    def take_background(self):
        _logger.debug('(%s) Taking a dezingered bias frame ...' % (self.name,))
        self.stop()
        self._start_cmd.put(1)
        self._readout_flag.put(2)
        time.sleep(1.0)
        self._readout_cmd.put(1)
        self.wait_for_state('read:exec')
        self.wait_in_state('read:exec')
        self._start_cmd.put(1)
        self._readout_flag.put(1)
        time.sleep(1.0)
        self._readout_cmd.put(1)
        self._dezinger_flag.put(1)
        self.wait_for_state('read:exec')
        self.wait_in_state('read:exec')
        self._dezinger_cmd.put(1)
        self.wait_for_state('dezinger:queue')

    def on_connection_changed(self, obj, state):
        if state == 0:
            self._bg_taken = False
            self.set_state(health=(4, 'socket', 'Connection to server lost!'))
        else:
            self.set_state(health=(0, 'socket'))

    def on_state_change(self, pv, val):
        _state_string = "%08x" % val
        states = []
        for i in range(8):
            state_val = int(_state_string[i])
            if state_val != 0:
                state_unit = "%s:%s" % (self._state_names[i], self._state_bits[state_val])
                states.append(state_unit)
        if len(states) == 0:
            states.append('idle')
        self._state_list = states
        _logger.debug('(%s) state changed to: %s' % (self.name, states,))
        return True

    def on_new_frame(self, obj, frame_name):
        file_path = os.path.join(self.settings['directory'].get(), frame_name)
        gobject.idle_add(self.emit, 'new-image', file_path)

        # Remove any .DELETE frames from this sequence
        old_file = file_path + DELETE_SUFFIX
        if os.path.exists(old_file):
            try:
                os.remove(old_file)
            except OSError:
                _logger.error('Unable to delete: {}{}'.format(frame_name, DELETE_SUFFIX))

    def wait_for_state(self, state, timeout=10.0):
        _logger.debug('(%s) Waiting for state: %s' % (self.name, state,))
        while (not self.is_in_state(state)) and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0:
            _logger.debug('(%s) state %s attained after: %0.1f sec' % (self.name, state, 10 - timeout))
            return True
        else:
            _logger.warning('(%s) Timed out waiting for state: %s' % (self.name, state,))
            return False

    def wait_in_state(self, state):
        _logger.debug('(%s) Waiting for state "%s" to expire.' % (self.name, state,))
        t = time.time()
        while self.is_in_state(state):
            time.sleep(0.05)
        _logger.debug('(%s) state %s expired after: %0.1f sec' % (self.name, state, time.time() - t))
        return True

    def is_in_state(self, state):
        if state in self._state_list[:]:
            return True
        else:
            return False


class SimCCDImager(BaseDevice):
    implements(IImagingDetector)
    __gsignals__ = {
        'new-image': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
    }

    def __init__(self, name, size, resolution, detector_type="MX300"):
        BaseDevice.__init__(self)
        self.size = int(size), int(size)
        self.resolution = float(resolution)
        self.name = name
        self.detector_type = detector_type
        self.shutterless = False
        self.file_extension = 'img'
        self.set_state(active=True, health=(0, ''))
        self._select_dir()
        self._state = 'idle'
        self._bg_taken = False

    def initialize(self, wait=True):
        _logger.debug('(%s) Initializing CCD ...' % (self.name,))
        time.sleep(0.1)
        _logger.debug('(%s) CCD Initialization complete.' % (self.name,))

    def start(self, first=False):
        self.initialize(True)
        time.sleep(0.1)

    def stop(self):
        _logger.debug('(%s) Stopping CCD ...' % (self.name,))
        time.sleep(0.1)

    def get_origin(self):
        return self.size[0] // 2, self.size[0] // 2

    def _select_dir(self):
        dirlist = []
        for i in range(5):
            src_dir = '/archive/staff/reference/CLS/SIM-%d' % i
            if os.path.exists(src_dir):
                dirlist.append(src_dir)
        dirlist.append(os.path.join(os.environ['BCM_PATH'], 'test', 'images'))
        self._src_dir = random.choice(dirlist)
        self._num_frames = len(
            [name for name in os.listdir(self._src_dir) if os.path.isfile(os.path.join(self._src_dir, name))])

    def _copy_frame(self):
        _logger.debug('Saving frame: %s' % datetime.now().isoformat())
        num = 1 + (self.parameters['start_frame'] - 1) % self._num_frames
        src_img = os.path.join(self._src_dir, '_%04d.img.gz' % num)
        file_name = '{}_{:04d}.img'.format(self.parameters['file_prefix'], self.parameters['start_frame'])
        dst_img = os.path.join(self.parameters['directory'], '{}.gz'.format(file_name))
        file_path = os.path.join(self.parameters['directory'], file_name)

        shutil.copyfile(src_img, dst_img)
        self.set_state(new_image=file_path)
        os.system('/usr/bin/gunzip -f %s' % dst_img)
        _logger.debug('Frame saved: %s' % datetime.now().isoformat())

        # Remove any .DELETE frames from this sequence
        old_file = file_path + DELETE_SUFFIX
        if os.path.exists(old_file):
            try:
                os.remove(old_file)
            except OSError:
                _logger.error('Unable to delete frame: {}{}'.format(file_name, DELETE_SUFFIX))

    def save(self, wait=False):
        self._copy_frame()

    def delete(self, directory, *frame_list):
        for frame_name in frame_list:
            frame_path = os.path.join(directory, '{}.{}'.format(frame_name, self.file_extension))
            if os.path.exists(frame_path):
                try:
                    os.rename(frame_path, frame_path + DELETE_SUFFIX)
                except OSError:
                    _logger.error('Unable to remove existing frame: {}'.format(frame_name))

    def wait(self, *states):
        time.sleep(0.1)

    def set_parameters(self, data):
        self.parameters = data
        if self.parameters['start_frame'] == 1:
            self._select_dir()


class PIL6MImager(BaseDevice):
    implements(IImagingDetector)
    __gsignals__ = {
        'new-image': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
    }
    STATES = {
        'init': [8],
        'acquiring': [1, 2, 3, 4],
        'idle': [0, 6, 10],
        'error': [6, 9],
        'waiting': [7],
        'busy': [1, 2, 3, 4, 5, 7, 8],
    }

    def __init__(self, name, description='PILATUS 6M Detector'):
        super(PIL6MImager, self).__init__()
        self.size = 2463, 2527
        self.resolution = 0.172
        self.name = description
        self.detector_type = 'PILATUS 6M'
        self.shutterless = True
        self.file_extension = 'cbf'

        self.acquire_cmd = self.add_pv('{}:Acquire'.format(name), monitor=False)
        self.mode_cmd = self.add_pv('{}:TriggerMode'.format(name), monitor=False)

        self.connected_status = self.add_pv('{}:AsynIO.CNCT'.format(name))
        self.armed_status = self.add_pv("{}:Armed".format(name))
        self.acquire_status = self.add_pv("{}:Acquire_RBV".format(name))
        self.energy_threshold = self.add_pv('{}:ThresholdEnergy_RBV'.format(name), monitor=False)
        self.state_value = self.add_pv('{}:DetectorState_RBV'.format(name))
        self.state_msg = self.add_pv('{}:StatusMessage_RBV'.format(name))
        self.command_string = self.add_pv('{}:StringToServer_RBV'.format(name))
        self.response_string = self.add_pv('{}:StringFromServer_RBV'.format(name))
        self.file_format = self.add_pv("{}:FileTemplate".format(name)),

        root_name = name.split(':')[0]
        self.saved_filename = self.add_pv('{}:saveData_fullPathName'.format(root_name))
        self.saved_filename.connect('changed', self.on_new_frame)

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

    def initialize(self, wait=True):
        _logger.debug('({}) Initializing Detector ...'.format(self.name))

    def start(self, first=False):
        _logger.debug('({}) Starting Acquisition ...'.format(self.name))
        self.wait('idle')
        self.acquire_cmd.put(1)
        ca.flush()
        self.wait('acquiring')

    def stop(self):
        _logger.debug('({}) Stopping Detector ...'.format(self.name))
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
                    os.rename(frame_path, frame_path + DELETE_SUFFIX)
                except OSError:
                    _logger.error('Unable to remove existing frame: {}'.format(frame_name))

    def on_new_frame(self, obj, frame_name):
        file_path = os.path.join(self.settings['directory'].get(), frame_name)
        gobject.idle_add(self.emit, 'new-image', file_path)

        # Remove any .DELETE frames from this sequence
        old_file = file_path + DELETE_SUFFIX
        if os.path.exists(old_file):
            try:
                os.remove(old_file)
            except OSError:
                _logger.error('Unable to delete: {}{}'.format(frame_name, DELETE_SUFFIX))

    def wait(self, state='idle'):
        return self.wait_for_state(state)

    def set_parameters(self, data):
        params = {}
        params.update(data)

        if not (0.5*params['energy'] < self.energy_threshold.get() < 0.75*params['energy']):
            params['threshold_energy'] = round(0.6*params['energy'], 2)

        # default directory if camserver fails to save frames
        #self.settings['directory'].put('/data/images/', flush=True)
        #params['file_template'] = '%s%s_%{0}.{0}d.{1}'.format(runlists.FRAME_NUMBER_DIGITS, self.file_extension)
        params['beam_x'] = self.settings['beam_x'].get()
        params['beam_y'] = self.settings['beam_y'].get()
        params['polarization'] = self.settings['polarization'].get()
        params['exposure_period'] = params['exposure_time']
        params['exposure_time'] -= 0.002

        self.mode_cmd.put(0)
        for k, v in params.items():
            if k in self.settings:
                time.sleep(0.05)
                self.settings[k].put(v, flush=True)

    def wait_for_state(self, state, timeout=10.0):
        _logger.debug('({}) Waiting for state: {}'.format(self.name, state,))
        while timeout > 0 and not self.is_in_state(state):
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0:
            _logger.debug('({}) state {} attained after: {:0.1f} sec'.format(self.name, state, 10 - timeout))
            return True
        else:
            _logger.warning('({}) Timed out waiting for state: {}'.format(self.name, state,))
            return False

    def wait_in_state(self, state, timeout=60):
        _logger.debug('({}) Waiting for state "{}" to expire.'.format(self.name, state,))
        while self.is_in_state(state) and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0:
            _logger.debug('({}) state "{}" expired after: {:0.1f} sec'.format(self.name, state, 10 - timeout))
            return True
        else:
            _logger.warning('({}) Timed out waiting for state "{}" to expire'.format(self.name, state,))
            return False

    def is_in_state(self, state):
        return self.state_value.get() in self.STATES.get(state, [])


class ADRayonixImager(BaseDevice):
    implements(IImagingDetector)
    __gsignals__ = {
        'new-image': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
    }
    STATES = {
        'init': [8],
        'acquiring': [1, 2],
        'reading': [2],
        'correcting': [3],
        'saving': [4],
        'idle': [0, 6, 10],
        'error': [6, 9],
        'waiting': [7],
        'busy': [1, 2, 3, 4, 5, 7, 8],
    }

    def __init__(self, name, size, detector_type='MX300HE', desc='Rayonix Detector'):
        super(ADRayonixImager, self).__init__()
        self.size = size, size
        self.resolution = 0.073242
        self.name = desc
        self.detector_type = detector_type
        self.shutterless = False
        self.file_extension = 'img'

        self.connected_status = self.add_pv('{}:AsynIO.CNCT'.format(name))
        self.acquire_cmd = self.add_pv('{}:Acquire'.format(name), monitor=False)
        self.frame_type = self.add_pv('{}:FrameType'.format(name), monitor=False)
        self.acquire_status = self.add_pv("{}:Acquire_RBV".format(name))
        self.state_value = self.add_pv('{}:DetectorState_RBV'.format(name))
        self.command_string = self.add_pv('{}:StringToServer_RBV'.format(name))
        self.response_string = self.add_pv('{}:StringFromServer_RBV'.format(name))
        self.file_format = self.add_pv("{}:FileTemplate".format(name)),
        self.saved_filename = self.add_pv('{}:FullFileName_RBV'.format(name))
        self.saved_filename.connect('changed', self.on_new_frame)

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

    def initialize(self, wait=True):
        _logger.debug('({}) Initializing Detector ...'.format(self.name))

    def start(self, first=False):
        _logger.debug('({}) Starting Acquisition ...'.format(self.name))
        self.wait('idle', 'correct', 'saving', 'waiting')
        self.acquire_cmd.put(1)
        ca.flush()
        self.wait('acquiring')

    def stop(self):
        _logger.debug('({}) Stopping Detector ...'.format(self.name))
        self.acquire_cmd.put(0)
        #self.wait('idle')

    def get_origin(self):
        return self.size[0] // 2, self.size[1] // 2

    def save(self):
        self.acquire_cmd.put(0)

    def delete(self, directory, *frame_list):
        for frame_name in frame_list:
            frame_path = os.path.join(directory, '{}.{}'.format(frame_name, self.file_extension))
            if os.path.exists(frame_path):
                try:
                    os.rename(frame_path, frame_path + DELETE_SUFFIX)
                except OSError:
                    _logger.error('Unable to remove existing frame: {}'.format(frame_name))

    def on_new_frame(self, obj, file_path):
        gobject.idle_add(self.emit, 'new-image', file_path)
        frame_name = os.path.basename(file_path)

        # Remove any .DELETE frames from this sequence
        old_file = file_path + DELETE_SUFFIX
        if os.path.exists(old_file):
            try:
                os.remove(old_file)
            except OSError:
                _logger.error('Unable to delete: {}{}'.format(frame_name, DELETE_SUFFIX))

    def wait(self, *states):
        states = states or ('idle',)
        return self.wait_for_state(*states)

    def set_parameters(self, data):
        params = {}
        params.update(data)
        for k, v in params.items():
            if k in self.settings:
                time.sleep(0.05)
                self.settings[k].put(v, flush=True)

    def wait_for_state(self, *states, **kwargs):
        timeout = kwargs.get('timeout', 10)
        _logger.debug('({}) Waiting for state: {}'.format(self.name, '|'.join(states)))
        while timeout > 0 and not self.is_in_state(*states):
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0:
            _logger.debug('({}) state {} attained after: {:0.1f} sec'.format(self.name, '|'.join(states), 10 - timeout))
            return True
        else:
            _logger.warning('({}) Timed out waiting for state: {}'.format(self.name, '|'.join(states),))
            return False

    def wait_in_state(self, *states, **kwargs):
        timeout = kwargs.get('timeout', 60)
        _logger.debug('({}) Waiting for state "{}" to expire.'.format(self.name, '|'.join(states),))
        while self.is_in_state(*states) and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0:
            _logger.debug('({}) state "{}" expired after: {:0.1f} sec'.format(self.name, '|'.join(states), 10 - timeout))
            return True
        else:
            _logger.warning('({}) Timed out waiting for state "{}" to expire'.format(self.name, '|'.join(states),))
            return False

    def is_in_state(self, *states):
        return any(self.state_value.get() in self.STATES.get(state, []) for state in states)


__all__ = ['MXCCDImager', 'SimCCDImager', 'PIL6MImager', 'ADRayonixImager']
