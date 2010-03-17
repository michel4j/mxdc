import time
import sys
import os
import logging
import numpy
import gobject

from zope.interface import implements
from bcm.device.interfaces import IImagingDetector
from bcm.protocol import ca
from bcm.utils.decorators import async
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

WAIT_DELAY = 0.02

class DetectorError(Exception):

    """Base class for errors in the detector module."""
            
     
class MXCCDImager(gobject.GObject):
    
    implements(IImagingDetector)
    
    def __init__(self, name, size, resolution):
        gobject.GObject.__init__(self)
        self.size = int(size)
        self.resolution = float(resolution)
        self.name = name
        
        self._start_cmd = ca.PV("%s:start:cmd" % name, monitor=False)
        self._abort_cmd = ca.PV("%s:abort:cmd" % name, monitor=False)
        self._readout_cmd = ca.PV("%s:readout:cmd" % name, monitor=False)
        self._reset_cmd = ca.PV("%s:resetStates:cmd" % name, monitor=False)
        self._writefile_cmd = ca.PV("%s:writefile:cmd" % name, monitor=False)
        self._background_cmd = ca.PV("%s:dezFrm:cmd" % name, monitor=False)
        self._save_cmd = ca.PV("%s:rdwrOut:cmd" % name, monitor=False)
        self._collect_cmd = ca.PV("%s:frameCollect:cmd" % name, monitor=False)
        self._header_cmd = ca.PV("%s:header:cmd" % name, monitor=False)
        self._readout_flag = ca.PV("%s:readout:flag" % name, monitor=False)
        self._dezinger_flag = ca.PV("%s:dez:flag" % name, monitor=False)
        self._dezinger_cmd = ca.PV("%s:dezinger:cmd" % name, monitor=False)
        self._connection_state = ca.PV('%s:sock:state'% name)
        
        #Header parameters
        self._header = {
            'filename' : ca.PV("%s:img:filename" % name, monitor=False),
            'directory': ca.PV("%s:img:dirname" % name, monitor=False),
            'beam_x' : ca.PV("%s:beam:x" % name, monitor=False),
            'beam_y' : ca.PV("%s:beam:y" % name, monitor=False),
            'distance' : ca.PV("%s:distance" % name, monitor=False),
            'time' : ca.PV("%s:exposureTime" % name, monitor=False),
            'axis' : ca.PV("%s:rot:axis" % name, monitor=False),
            'wavelength':  ca.PV("%s:src:wavelgth" % name, monitor=False),
            'delta' : ca.PV("%s:omega:incr" % name, monitor=False),
            'frame_number': ca.PV("%s:startFrame" % name, monitor=False),
            'prefix' : ca.PV("%s:img:prefix" % name, monitor=False),
            'start_angle': ca.PV("%s:start:omega" % name, monitor=False),
            'energy': ca.PV("%s:runEnergy" % name, monitor=False),            
        }
                
        #Status parameters
        self._state_string = '00000000'
        self._state = ca.PV("%s:rawState" % name)
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
        #self.initialize(True)
        if not first:
            self._wait_in_state('acquire:queue')
            self._wait_in_state('acquire:exec')
            #self._wait_for_state('correct:exec')
        else:
            self.take_background()
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
    


class SimCCDImager(object):
    
    implements(IImagingDetector)

    def __init__(self, name, size, resolution):
        self.size = int(size)
        self.resolution = float(resolution)
        self.name = name
        self._state = 'idle'
        self._bg_taken = False
        self._src_dir = os.path.join(os.environ['BCM_PATH'], 'bcm', 'test','images')
    
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
        num = 1 + self.parameters['frame_number'] % 9
        src_img = os.path.join(self._src_dir, '_%04d.img.gz' % num)
        dst_img = os.path.join(self.parameters['directory'], 
                               '%s.gz' % self.parameters['filename'])
        os.system('/bin/cp %s %s' % (src_img, dst_img))
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
