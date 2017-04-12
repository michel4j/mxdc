import os
import re
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

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

WAIT_DELAY = 0.02


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
        self.current_file = ''

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
        self._header = {
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
        ca.flush()
        self.wait_for_state('idle')

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
        self.set_state(new_image=self.current_file)

    def get_origin(self):
        """Obtain the detector origin/beam position in pixels.
        
        Returns:
            tuple(x, y) corresponding to the beam-x and beam-y coordinates.
        """
        return self._header['beam_x'].get(), self._header['beam_y'].get()

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
        for key in data.keys():
            if key in self._header:
                self._header[key].set(data[key])
        self.current_file = data['filename']
        if os.path.exists(data['filename']):
            os.remove(data['filename'])
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
        num = 1 + (self.parameters['frame_number'] - 1) % self._num_frames
        src_img = os.path.join(self._src_dir, '_%04d.img.gz' % num)
        dst_img = os.path.join(self.parameters['directory'], '%s.gz' % self.parameters['filename'])
        file_path = os.path.join(self.parameters['directory'], self.parameters['filename'])

        dst_parts = dst_img.split('/')
        if dst_parts[1] == 'data':
            dst_parts[1] = 'users'
        dst_img = '/'.join(dst_parts)
        shutil.copyfile(src_img, dst_img)
        self.set_state(new_image=file_path)
        os.system('/usr/bin/gunzip -f %s' % dst_img)
        _logger.debug('Frame saved: %s' % datetime.now().isoformat())

    def save(self, wait=False):
        self._copy_frame()


    def wait(self, state='idle'):
        time.sleep(0.1)

    def set_parameters(self, data):
        self.parameters = data
        if self.parameters['frame_number'] == 1:
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
        # self.file_list = []
        # self._notifier_id = None
        # self._notifier_period = 1000

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
        self.file_name = self.add_pv('{}:FileName_RBV'.format(name))
        self.file_name.connect('changed', self.on_new_frame)

        # Data Parameters
        self.settings = {
            'first_frame': self.add_pv("{}:FileTemplate".format(name), monitor=True),
            'directory': self.add_pv("{}:FilePath".format(name), monitor=False),

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

            'num_frames': self.add_pv('{}:NumImages'.format(name), monitor=False),
            'start_angle': self.add_pv("{}:StartAngle".format(name), monitor=False),
            'delta_angle': self.add_pv("{}:AngleIncr".format(name), monitor=False),
            'exposure_time': self.add_pv("{}:AcquireTime".format(name), monitor=False),
            'exposure_period': self.add_pv("{}:AcquirePeriod".format(name), monitor=False),

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
        ca.flush()
        self.wait('idle')

    def get_origin(self):
        return self.size[0] // 2, self.size[1] // 2

    def save(self, wait=False):
        return

    def on_new_frame(self, obj, frame_name):
        file_path = os.path.join(self.settings['directory'].get(), frame_name)
        gobject.idle_add(self.emit, 'new-image', file_path)

    # def monitor_frames(self):
    #     if self._notifier_id:
    #         gobject.source_remove(self._notifier_id)
    #     self._notifier_id = gobject.timeout_add(self._notifier_period, self._notify_frame)
    #
    # def _notify_frame(self):
    #     if self.file_list:
    #         gobject.idle_add(self.emit, 'new-image', self.file_list.pop(0))
    #         return True

    def wait(self, state='idle'):
        return self.wait_for_state(state)

    def set_parameters(self, data):
        params = {}
        params.update(data)

        if not (0.5*params['energy'] < self.energy_threshold.get() < 0.75*params['energy']):
            params['threshold_energy'] = round(0.6*params['energy'], 2)

        # default directory if camserver fails to save frames
        self.settings['directory'].put('/data/images/', flush=True)
        params['file_template'] = '{}.{}'.format(params['file_template'], self.file_extension)
        params['beam_x'] = self.settings['beam_x'].get()
        params['beam_y'] = self.settings['beam_y'].get()
        params['polarization'] = self.settings['polarization'].get()
        params['exposure_period'] = params['exposure_time']
        params['exposure_time'] -= 0.002
        params['first_frame'] = params['file_template'].format(params['start_frame'])

        self.mode_cmd.put(0)
        for k, v in params.items():
            if k in self.settings:
                time.sleep(0.05)
                self.settings[k].put(v, flush=True)

        # cleanup existing files
        file_list =  [
            os.path.join(params['directory'], params['file_template'].format(i + params['start_frame']))
            for i in range(params['num_frames'])
        ]
        for file_path in file_list:
            if os.path.exists(file_path) and os.access(file_path, os.W_OK):
                try:
                    os.remove(file_path)
                except OSError:
                    _logger.error('Unable to remove existing frame: {}'.format(file_path))
            time.sleep(0)

        # self._notifier_period = int(1000 * params['exposure_period'])

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


__all__ = ['MXCCDImager', 'SimCCDImager', 'PIL6MImager']
