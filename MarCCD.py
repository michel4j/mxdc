#!/usr/bin/env python
import sys, time
import gtk, gobject
import EpicsCA, numpy

class CCDDetector:
    def __init__(self, name):
        pass

    def start(self):
        pass
        
    def acquire_bg(self):
        pass
        
    def save(self):
        pass
    
    def set_header(self):
        pass
        
    def abort(self):
        pass
        
    def check_state(self,key):
        pass
        
    def wait_until(self,state, timeout=1.0):        
        pass

    def wait_while(self,state, timeout=1.0):        
        pass
    
    def copy(self):
        return CCDDetector()
        
class MarCCD(CCDDetector):
    def __init__(self, name):
        #house_keeping
        self._bg_taken = False
        self.name = name
        self.start_cmd = EpicsCA.PV("%s:start:cmd" % name)
        self.abort_cmd = EpicsCA.PV("%s:abort:cmd" % name)
        self.correct_cmd = EpicsCA.PV("%s:correct:cmd" % name)
        self.writefile_cmd = EpicsCA.PV("%s:writefile:cmd" % name)
        self.background_cmd = EpicsCA.PV("%s:dezFrm:cmd" % name)
        self.acquire_cmd = EpicsCA.PV("%s:rdwrOut:cmd" % name)

        #Header parameters
        self.header = {
            'filename' : EpicsCA.PV("%s:img:filename" % name),
            'directory': EpicsCA.PV("%s:img:dirname" % name),
            'beam_x' : EpicsCA.PV("%s:beam:x" % name),
            'beam_y' : EpicsCA.PV("%s:beam:y" % name),
            'distance' : EpicsCA.PV("%s:distance" % name),
            'time' : EpicsCA.PV("%s:exposureTime" % name),
            'axis' : EpicsCA.PV("%s:rot:axis" % name),
            'wavelength':  EpicsCA.PV("%s:src:wavelgth" % name),
            'delta' : EpicsCA.PV("%s:omega:incr" % name)
        }
        #Status parameters
        self.state = EpicsCA.PV("%s:rawState" % name)
        self.state_bits = ['None','queue','exec','queue+exec','err','queue+err','exec+err','queue+exec+err','busy']
        self.state_names = ['unused','unused','dezinger','write','correct','read','acquire','state']
            
    def copy(self):
        return MarCCD(self.name)
          
    def state_list(self):
        state_string = "%08x" % self.state.value
        states = []
        for i in range(8):
            state_val = int(state_string[i])
            if state_val != 0:
                state_unit = "%s:%s" % (self.state_names[i],self.state_bits[state_val])
                states.append(state_unit)
        if len(states) == 0:
            states.append('idle')
        return states

    def wait_until(self,state, timeout=10.0):      
        st_time = time.time()
        elapsed = time.time() - st_time

        while (not self.check_state(state)) and elapsed < timeout:
            elapsed = time.time() - st_time
            time.sleep(0.01)
        if elapsed < timeout:
            return True
        else:
            return False

    def wait_while(self,state):      
        while self.check_state(state):
            time.sleep(0.01)
        return True
        
    def check_state(self, key):
        if key in self.state_list():
            return True
        else:
            return False

    def acquire_bg(self, wait=False):
        success = self.wait_until('idle')
        if success:
            self.background_cmd.value = 1
            self._bg_taken = True
            if wait:
                self.wait_until('acquire:exec')
                self.wait_until('idle')
                        
    def start(self):
        #if not self._bg_taken:
        #    self.acquire_bg(wait=True)
        self.wait_while('acquire:queue')
        self.wait_while('acquire:exec')
        self.start_cmd.value = 1
        success = self.wait_until('acquire:exec')
        
    def set_header(self, data):
        for key in data.keys():
            self.header[key].value = data[key]
    
    def save(self,wait=False):
        self.acquire_cmd.value = 1
        if wait:
            self.wait_until('write:exec')
        
    
        
        
