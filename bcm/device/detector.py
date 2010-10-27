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

class DetectorError(Exception):

    """Base class for errors in the detector module."""
            
     
class MXCCDImager(BaseDevice):
    
    implements(IImagingDetector)
    
    def __init__(self, name, size, resolution):
        BaseDevice.__init__(self)
        self.size = int(size)
        self.resolution = float(resolution)
        self.name = 'MXCCD Detector'
        
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
        self._connection_state = self.add_pv('%s:sock:state'% name)
        
        #Header parameters
        self._header = {
            'filename' : self.add_pv("%s:img:filename" % name, monitor=False),
            'directory': self.add_pv("%s:img:dirname" % name, monitor=False),
            'beam_x' : self.add_pv("%s:beam:x" % name, monitor=False),
            'beam_y' : self.add_pv("%s:beam:y" % name, monitor=False),
            'distance' : self.add_pv("%s:distance" % name, monitor=False),
            'time' : self.add_pv("%s:exposureTime" % name, monitor=False),
            'axis' : self.add_pv("%s:rot:axis" % name, monitor=False),
            'wavelength':  self.add_pv("%s:src:wavelgth" % name, monitor=False),
            'delta' : self.add_pv("%s:omega:incr" % name, monitor=False),
            'frame_number': self.add_pv("%s:startFrame" % name, monitor=False),
            'prefix' : self.add_pv("%s:img:prefix" % name, monitor=False),
            'start_angle': self.add_pv("%s:start:omega" % name, monitor=False),
            'energy': self.add_pv("%s:runEnergy" % name, monitor=False),            
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

    def __repr__(self):
        return "<%s:'%s', state:'%s'>" % (self.__class__.__name__, self.name, self.get_state() )
    
    def initialize(self, wait=True):
        if not self._bg_taken:
            _logger.debug('(%s) Initializing CCD ...' % (self.name,))
            self.take_background()
            self._bg_taken = True
    
    def take_background(self):
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
             
    def start(self, first=False):
        self.initialize(True)
        if not first:
            self._wait_in_state('acquire:queue')
            self._wait_in_state('acquire:exec')
            #self._wait_for_state('correct:exec')
        else:
            pass
            #self.take_background()
        _logger.debug('(%s) Starting CCD acquire ...' % (self.name,))
        self._start_cmd.put(1)
        self._wait_for_state('acquire:exec')

    def stop(self):
        _logger.debug('(%s) Stopping CCD ...' % (self.name,))
        self._abort_cmd.put(1)
        ca.flush()
        self._wait_for_state('idle')
        
    def save(self, wait=False):
        _logger.debug('(%s) Starting CCD readout ...' % (self.name,))
        self._readout_flag.put(0)
        ca.flush()
        self._save_cmd.put(1)
        if wait:
            self._wait_for_state('read:exec')
    
    def get_state(self):
        return self._state_list[:]
    
    def wait(self, state='idle'):
        self._wait_for_state(state,timeout=10.0)
                
    def _update_background(self, obj, state):
        if state == 1:
            self._bg_taken = False
                      
    def set_parameters(self, data):
        for key in data.keys():
            #print key, data[key], self._header[key]
            self._header[key].set(data[key])        
        self._header_cmd.put(1)
    
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
        if state in self.get_state():
            return True
        else:
            return False
    


class SimCCDImager(BaseDevice):
    
    implements(IImagingDetector)

    def __init__(self, name, size, resolution):
        self.size = int(size)
        self.resolution = float(resolution)
        self.name = name
        self._state = 'idle'
        self._bg_taken = False
        self._src_dir = os.path.join(os.environ['BCM_PATH'], 'test','images')
    
    def __repr__(self):
        return "<%s:'%s', state:'%s'>" % (self.__class__.__name__, self.name, self.get_state() )
    
    def initialize(self, wait=True):
        _logger.debug('(%s) Initializing CCD ...' % (self.name,)) 
        time.sleep(1)
        _logger.debug('(%s) CCD Initialization complete.' % (self.name,))
                        
    def start(self, first=False):
        self.initialize(True)
        time.sleep(1)
        
    def stop(self):
        _logger.debug('(%s) Stopping CCD ...' % (self.name,))
        time.sleep(1)
    
    @async
    def _copy_frame(self):
        num = 1 + self.parameters['frame_number'] % 2
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
        time.sleep(0.1)
        
    def get_state(self):
        return ['idle']
    
    def wait(self, state='idle'):
        time.sleep(3)
                                      
    def set_parameters(self, data):
        self.parameters = data

__all__ = ['MXCCDImager', 'SimCCDImager']  
