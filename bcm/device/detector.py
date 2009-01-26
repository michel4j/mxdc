from bcm.interfaces.detectors import *
from bcm.protocols import ca
from zope.interface import implements
import time
import threading
import sys
import numpy
import gobject
import logging

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class DetectorError(Exception):

    """Base class for errors in the detector module."""
            

    
        
class MarCCDImager(object):
    implements(IImagingDetector)
    def __init__(self, name):
        self.name = name
        self.start_cmd = ca.PV("%s:start:cmd" % name, monitor=False)
        self.abort_cmd = ca.PV("%s:abort:cmd" % name, monitor=False)
        self.readout_cmd = ca.PV("%s:correct:cmd" % name, monitor=False)
        self.writefile_cmd = ca.PV("%s:writefile:cmd" % name, monitor=False)
        self.background_cmd = ca.PV("%s:dezFrm:cmd" % name, monitor=False)
        self.save_cmd = ca.PV("%s:rdwrOut:cmd" % name, monitor=False)
        self.collect_cmd = ca.PV("%s:frameCollect:cmd" % name, monitor=False)
        self.header_cmd = ca.PV("%s:header:cmd" % name, monitor=False)
        self.readout_flag = ca.PV("%s:readout:flag" % name, monitor=False)
        self.connection_state = ca.PV('%s:sock:state'% name)
        
        #Header parameters
        self.header = {
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
        self.state = ca.PV("%s:rawState" % name)
        self.state_bits = ['None','queue','exec','queue+exec','err','queue+err','exec+err','queue+exec+err','busy']
        self.state_names = ['unused','unused','dezinger','write','correct','read','acquire','state']
        self._bg_taken = False
        
        self.state.connect('changed', self._on_state_change)
        self.state_string = "%08x" % self.state.get()
        self.connection_state.connect('changed', self._update_background)
        self._logger = logging.getLogger('bcm.ccd')

    def _update_background(self, obj, state):
        if state == 1:
            self._bg_taken = False
                      
    def start(self):
        self.initialize(True)
        self._wait_in_state('acquire:queue')
        self._wait_in_state('acquire:exec')
        self.start_cmd.put(1)
        self._wait_for_state('acquire:exec')

    def is_healthy(self):
        if self.connection_state.get() == 1:
            return True
        else:
            return False

    def set_parameters(self, data):
        for key in data.keys():
            self.header[key].put(data[key])        
        self.header_cmd.put(1)
    
    def save(self,wait=False):
        self.readout_flag.put(0)
        self.save_cmd.put(1)
        if wait:
            self._wait_for_state('read:exec')
    
    def _on_state_change(self, pv, val):
        self.state_string = "%08x" % val
        return True
    
    def _get_states(self):
        state_string = self.state_string[:]
        states = []
        for i in range(8):
            state_val = int(state_string[i])
            if state_val != 0:
                state_unit = "%s:%s" % (self.state_names[i],self.state_bits[state_val])
                states.append(state_unit)
        if len(states) == 0:
            states.append('idle')
        return states

    def _wait_for_state(self,state, timeout=5.0):
        self._logger.debug('Waiting for state: %s' % (state,) ) 
        while (not self._is_in_state(state)) and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0: 
            return True
        else:
            self._logger.warning('Timed out waiting for state: %s' % (state,) ) 
            return False

    def _wait_in_state(self, state):      
        self._logger.debug('Waiting for state "%s" to expire.' % (state,) ) 
        while self._is_in_state(state):
            time.sleep(0.05)
        return True
        
    def _is_in_state(self, state):
        if state in self._get_states():
            return True
        else:
            return False

    def initialize(self, wait=True):
        if not self._bg_taken:
            self._logger.debug('Initializing CCD ...') 
            if not self._is_in_state('idle'):
                self.abort_cmd.put(1)
                self._wait_for_state('idle')
            self._wait_in_state('acquire:queue')
            self._wait_in_state('acquire:exec')
            self.background_cmd.put(1)
            if wait:
                self._wait_for_state('acquire:exec')
                self._wait_for_state('idle')
            self._bg_taken = True
            self._logger.debug('CCD Initialization complete.') 
                        
            


gobject.type_register(DetectorBase)
    
