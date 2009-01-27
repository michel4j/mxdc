import time
import sys
import logging
import numpy
import gobject

from zope.interface import implements
from bcm.device.interfaces import IImagingDetector
from bcm.protocol import ca
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class DetectorError(Exception):

    """Base class for errors in the detector module."""
            
     
class MXCCDImager(object):
    
    implements(IImagingDetector)
    
    def __init__(self, name, size, resolution):
        self.size = size
        self.resolution = resolution
        self._name = name
        
        self._start_cmd = ca.PV("%s:start:cmd" % name, monitor=False)
        self._abort_cmd = ca.PV("%s:abort:cmd" % name, monitor=False)
        self._readout_cmd = ca.PV("%s:correct:cmd" % name, monitor=False)
        self._writefile_cmd = ca.PV("%s:writefile:cmd" % name, monitor=False)
        self._background_cmd = ca.PV("%s:dezFrm:cmd" % name, monitor=False)
        self._save_cmd = ca.PV("%s:rdwrOut:cmd" % name, monitor=False)
        self._collect_cmd = ca.PV("%s:frameCollect:cmd" % name, monitor=False)
        self._header_cmd = ca.PV("%s:header:cmd" % name, monitor=False)
        self._readout_flag = ca.PV("%s:readout:flag" % name, monitor=False)
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
        self._state = ca.PV("%s:rawState" % name)
        self._state_bits = ['None','queue','exec','queue+exec','err','queue+err','exec+err','queue+exec+err','busy']
        self._state_names = ['unused','unused','dezinger','write','correct','read','acquire','state']
        self._bg_taken = False
        
        self._state.connect('changed', self._on_state_change)
        self._state_string = "%08x" % self._state.get()
        self._connection_state.connect('changed', self._update_background)

    def __repr__(self):
        return "<%s:'%s', state:'%s'>" % (self.__class__.__name__, self._name, self.get_state() )
    
    def initialize(self, wait=True):
        if not self._bg_taken:
            _logger.debug('(%s) Initializing CCD ...' % (self._name,)) 
            if not self._is_in_state('idle'):
                self.stop()
            self._wait_in_state('acquire:queue')
            self._wait_in_state('acquire:exec')
            self._background_cmd.put(1)
            if wait:
                self.wait()
            self._bg_taken = True
            _logger.debug('(%s) CCD Initialization complete.' % (self._name,)) 
                        
    def start(self):
        self.initialize(True)
        self._wait_in_state('acquire:queue')
        self._wait_in_state('acquire:exec')
        self._start_cmd.put(1)
        self._wait_for_state('acquire:exec')

    def stop(self):
        _logger.debug('(%s) Stopping CCD ...' % (self._name,))
        self._abort_cmd.put(1)
        self._wait_for_state('idle')
        
    def save(self, props, wait=False):
        self._set_parameters(props)
        ca.flush()  # make sure headers are set before starting readout
        self._readout_flag.put(0)
        self._save_cmd.put(1)
        if wait:
            self._wait_for_state('read:exec')
    
    def get_state(self):
        state_string = self._state_string[:]
        states = []
        for i in range(8):
            state_val = int(state_string[i])
            if state_val != 0:
                state_unit = "%s:%s" % (self._state_names[i],self._state_bits[state_val])
                states.append(state_unit)
        if len(states) == 0:
            states.append('idle')
        return states
    
    def wait(self, state='idle'):
        self._wait_for_state(state,timeout=30.0)
                
    def _update_background(self, obj, state):
        if state == 1:
            self._bg_taken = False
                      
    def _set_parameters(self, data):
        for key in data.keys():
            self._header[key].put(data[key])        
        self._header_cmd.put(1)
    
    def _on_state_change(self, pv, val):
        self._state_string = "%08x" % val
        return True

    def _wait_for_state(self, state, timeout=5.0):
        _logger.debug('(%s) Waiting for state: %s' % (self._name, state,) ) 
        while (not self._is_in_state(state)) and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0: 
            return True
        else:
            _logger.warning('(%s) Timed out waiting for state: %s' % (self._name, state,) ) 
            return False

    def _wait_in_state(self, state):      
        _logger.debug('(%s) Waiting for state "%s" to expire.' % (self._name, state,) ) 
        while self._is_in_state(state):
            time.sleep(0.05)
        return True
        
    def _is_in_state(self, state):
        if state in self.get_state():
            return True
        else:
            return False
    
