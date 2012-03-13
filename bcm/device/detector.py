import time
import sys
import os
import logging
import numpy
import gobject
import shutil

from zope.interface import implements
from bcm.device.interfaces import IImagingDetector
from bcm.protocol import ca
from bcm.device.base import BaseDevice
from bcm.utils.decorators import async
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

WAIT_DELAY = 0.02            
     
class MXCCDImager(BaseDevice):
    """MX Detector object for EPICS based Rayonix CCD detectors at the CLS."""
    implements(IImagingDetector)
    
    def __init__(self, name, size, resolution, detector_type='MX300'):
        """
        Args:
            `name` (str): Root name of the EPICS record Process Variables.
            `size` (int): The size in pixels of the detector. Assumes square 
            detectors.
            `resolueion` (float): The pixel size in 
        
        Kwargs:
            `detector_type` (str): The type of detector. e.g. "MX300" for Rayonix
            MX CCD 300.
        """
             
        BaseDevice.__init__(self)
        self.size = int(size)
        self.resolution = float(resolution)
        self.detector_type = detector_type
        self.name = '%s Detector' % detector_type
        
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
        
        #Header parameters
        self._header = {
            'filename' : self.add_pv("%s:img:filename" % name, monitor=False),
            'directory': self.add_pv("%s:img:dirname" % name, monitor=False),
            'beam_x' : self.add_pv("%s:beam:x" % name, monitor=False),
            'beam_y' : self.add_pv("%s:beam:y" % name, monitor=False),
            'distance' : self.add_pv("%s:distance" % name, monitor=False),
            'exposure_time' : self.add_pv("%s:exposureTime" % name, monitor=False),
            'axis' : self.add_pv("%s:rot:axis" % name, monitor=False),
            'wavelength':  self.add_pv("%s:src:wavelgth" % name, monitor=False),
            'delta_angle' : self.add_pv("%s:omega:incr" % name, monitor=False),
            'frame_number': self.add_pv("%s:startFrame" % name, monitor=False),
            'name' : self.add_pv("%s:img:prefix" % name, monitor=False),
            'start_angle': self.add_pv("%s:start:omega" % name, monitor=False),
            'energy': self.add_pv("%s:runEnergy" % name, monitor=False),
            'comments': self.add_pv('%s:dataset:cmnts' % name, monitor=False),
        }
                
        #Status parameters
        self._state_string = '00000000'
        self._state = self.add_pv("%s:rawState" % name)
        self._state_bits = ['None','queue','exec','queue+exec','err','queue+err','exec+err','queue+exec+err','unused']
        self._state_names = ['unused','unused','dezinger','write','correct','read','acquire','state']
        self._bg_taken = False
        self._state_list = []
        
        self._state.connect('changed', self._on_state_change)
        self._connection_state.connect('changed', self._update_background)
    
    def initialize(self, wait=True):
        """Initialize the detector and take background images if necessary. This
        method does not do anything if the device is already initialized.
        
        Kwargs:
            `wait` (bool): If true, the call will block until initialization is
            complete.
        """
        if not self._bg_taken:
            _logger.debug('(%s) Initializing CCD ...' % (self.name,))
            self._take_background()
            self._bg_taken = True
    
    def start(self, first=False):
        """Start acquiring.
        
        Kwargs:
            `first` (bool): Specifies whether this is the first of a series of
            acquisitions. This is used to customize the behaviour for the first.
        """
        self.initialize(True)
        if not first:
            self._wait_in_state('acquire:queue')
            self._wait_in_state('acquire:exec')
            #self._wait_for_state('correct:exec')
        _logger.debug('(%s) Starting CCD acquire ...' % (self.name,))
        self._start_cmd.put(1)
        self._wait_for_state('acquire:exec')

    def stop(self):
        """Stop and Abort the current acquisition."""
        _logger.debug('(%s) Stopping CCD ...' % (self.name,))
        self._abort_cmd.put(1)
        ca.flush()
        self._wait_for_state('idle')
        
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
            self._wait_for_state('read:exec')
            
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
        self._wait_for_state(state,timeout=10.0)
                                     
    def set_parameters(self, data):
        """Set the detector parameters for the image header and file names.
        
        Args:
            `data` (dict): A dictionary of key value pairs for the parameters.
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
            self._header[key].set(data[key])                
        self._header_cmd.put(1)
    
    def _take_background(self):
        _logger.debug('(%s) Taking a dezingered bias frame ...' % (self.name,)) 
        self.stop()
        self._start_cmd.put(1)     
        self._readout_flag.put(2)
        time.sleep(1.0)
        self._readout_cmd.put(1)
        self._wait_for_state('read:exec')
        self._wait_in_state('read:exec')
        self._start_cmd.put(1)
        self._readout_flag.put(1)
        time.sleep(1.0)
        self._readout_cmd.put(1)
        self._dezinger_flag.put(1)
        self._wait_for_state('read:exec')
        self._wait_in_state('read:exec')
        self._dezinger_cmd.put(1)
        self._wait_for_state('dezinger:queue')
             
    def _update_background(self, obj, state):
        if state == 1:
            self._bg_taken = False

    def _on_state_change(self, pv, val):
        _state_string = "%08x" % val
        states = []
        for i in range(8):
            state_val = int(_state_string[i])
            if state_val != 0:
                state_unit = "%s:%s" % (self._state_names[i],self._state_bits[state_val])
                states.append(state_unit)
        if len(states) == 0:
            states.append('idle')
        self._state_list = states
        _logger.debug('(%s) state changed to: %s' % (self.name, states,) ) 
        return True

    def _wait_for_state(self, state, timeout=10.0):
        _logger.debug('(%s) Waiting for state: %s' % (self.name, state,) ) 
        while (not self._is_in_state(state)) and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0: 
            _logger.debug('(%s) state %s attained after: %0.1f sec' % (self.name, state, 10-timeout) ) 
            return True
        else:
            _logger.warning('(%s) Timed out waiting for state: %s' % (self.name, state,) ) 
            return False

    def _wait_in_state(self, state):      
        _logger.debug('(%s) Waiting for state "%s" to expire.' % (self.name, state,) )
        t = time.time() 
        while self._is_in_state(state):
            time.sleep(0.05)
        _logger.debug('(%s) state %s expired after: %0.1f sec' % (self.name, state, time.time()-t) ) 
        return True
        
    def _is_in_state(self, state):
        if state in self._state_list[:]:
            return True
        else:
            return False
    


class SimCCDImager(BaseDevice):
    
    implements(IImagingDetector)

    def __init__(self, name, size, resolution, detector_type="MX300"):
        BaseDevice.__init__(self)
        self.size = int(size)
        self.resolution = float(resolution)
        self.name = name
        self.detector_type = detector_type
        self._state = 'idle'
        self._bg_taken = False
        
        _src_dir1 = os.path.join(os.environ['BCM_PATH'], 'test','images')
        _src_dir2 = '/archive/staff/reference/CLS/SIM'
        if os.path.exists(_src_dir2):
            self._src_dir = _src_dir2
            self._num_frames = 180
        else:
            self._src_dir = _src_dir1
            self._num_frames = 2
        self.set_state(active=True)
        
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
        return self.size//2, self.size//2
    
    def _copy_frame(self):
        num = 1 + (self.parameters['frame_number']-1) % self._num_frames
        src_img = os.path.join(self._src_dir, '_%04d.img.gz' % num)
        dst_img = os.path.join(self.parameters['directory'], 
                               '%s.gz' % self.parameters['filename'])
        dst_parts = dst_img.split('/')
        if dst_parts[1] == 'data':
            dst_parts[1] = 'users'
        dst_img = '/'.join(dst_parts)
        shutil.copyfile(src_img, dst_img)
        os.system('/usr/bin/gunzip -f %s' % dst_img)
        
    def save(self, wait=False):
        self._copy_frame()
            
    def wait(self, state='idle'):
        time.sleep(0.1)
                                      
    def set_parameters(self, data):
        self.parameters = data

__all__ = ['MXCCDImager', 'SimCCDImager']  
