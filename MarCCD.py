#!/usr/bin/env python
import sys, time
import gtk, gobject, numpy
from EPICS import PV
from LogServer import LogServer

class CCDDetector:
    def __init__(self, name):
        self.name = name

    def start(self):
        pass
        
    def acquire_bg(self, wait=False):
        pass
        
    def save(self, wait=False):
        pass
    
    def set_header(self, data):
        pass
                
    def check_state(self,key):
        pass
        
    def wait_until(self,state, timeout=1.0):        
        pass

    def wait_while(self,state, timeout=1.0):        
        pass
    
class MarCCD(CCDDetector):
    def __init__(self, name):
        #house_keeping
        self._bg_taken = False
        self.name = name
        self.start_cmd = PV("%s:start:cmd" % name)
        self.abort_cmd = PV("%s:abort:cmd" % name)
        self.readout_cmd = PV("%s:correct:cmd" % name)
        self.writefile_cmd = PV("%s:writefile:cmd" % name)
        self.background_cmd = PV("%s:dezFrm:cmd" % name)
        self.save_cmd = PV("%s:rdwrOut:cmd" % name)
        self.collect_cmd = PV("%s:frameCollect:cmd" % name)
        self.header_cmd = PV("%s:header:cmd" % name)
        self.readout_flag = PV("%s:readout:flag" % name)
        
        #Header parameters
        self.header = {
            'filename' : PV("%s:img:filename" % name),
            'directory': PV("%s:img:dirname" % name),
            'beam_x' : PV("%s:beam:x" % name),
            'beam_y' : PV("%s:beam:y" % name),
            'distance' : PV("%s:distance" % name),
            'time' : PV("%s:exposureTime" % name),
            'axis' : PV("%s:rot:axis" % name),
            'wavelength':  PV("%s:src:wavelgth" % name),
            'delta' : PV("%s:omega:incr" % name),
            'frame_number': PV("%s:startFrame" % name),
            'prefix' : PV("%s:img:prefix" % name),
            'start_angle': PV("%s:start:omega" % name),
            'energy': PV("%s:runEnergy" % name),            
        }
                
        #Status parameters
        self.state = PV("%s:rawState" % name)
        self.state_bits = ['None','queue','exec','queue+exec','err','queue+err','exec+err','queue+exec+err','busy']
        self.state_names = ['unused','unused','dezinger','write','correct','read','acquire','state']
        self._bg_taken = False
                      
    def state_list(self):
        state_string = "%08x" % self.state.get()
        states = []
        for i in range(8):
            state_val = int(state_string[i])
            if state_val != 0:
                state_unit = "%s:%s" % (self.state_names[i],self.state_bits[state_val])
                states.append(state_unit)
        if len(states) == 0:
            states.append('idle')
        return states

    def wait_until(self,state, timeout=5.0):      
        #print "waiting to reach state '%s'" % state
        st_time = time.time()
        elapsed = time.time() - st_time

        while (not self.check_state(state)) and elapsed < timeout:
            elapsed = time.time() - st_time
            time.sleep(0.001)
        if elapsed < timeout:
            return True
        else:
            return False

    def wait_while(self,state):      
        #print "waiting for state '%s' to expire" % state
        while self.check_state(state):
            time.sleep(0.001)
        return True
        
    def check_state(self, key):
        if key in self.state_list():
            return True
        else:
            return False

    def acquire_bg(self, wait=True):
        #print 'acquiring dezingered  background'
        self.wait_while('acquire:queue')
        self.wait_while('acquire:exec')
        self.wait_while('read:exec')
        self.background_cmd.put(1)
        self._bg_taken = True
        if wait:
            self.wait_until('acquire:exec')
            self.wait_until('idle')
                        
    def start(self):
        if not self._bg_taken:
            self.acquire_bg(wait=True)
        self.wait_while('acquire:queue')
        self.wait_while('acquire:exec')
        self.wait_while('read:exec')
        self.start_cmd.put(1)
        self.wait_until('acquire:exec')
        
    def set_header(self, data):
        for key in data.keys():
            self.header[key].put(data[key])        
        self.header_cmd.put(1)
    
    def save(self,wait=False):
        self.readout_flag.put(0)
        self.save_cmd.put(1)
        if wait:
            self.wait_until('correct:exec')
            
    def wait_start(self):      
        self.wait_while('acquire:queue')
        self.wait_while('acquire:exec')
        self.wait_while('read:exec')

    def wait_stop(self):      
        self.wait_until('acquire:exec')
        self.wait_until('write:exec')        
    
class Gonio:
    def __init__(self, name):
        #house_keeping
        self.name = name
        self.scan_cmd = PV("%s:scanFrame.PROC" % name)

        #Status parameters
        self.state = PV("%s:scanFrame:status" % name)
        self.shutter_state = PV("%s:lowerTOUT.B0" % name)
        self.move_state = PV("%s:moving" % name)
        self.active = False
        
        #parameters
        self.params = {
            'time' : PV("%s:expTime" % name),
            'delta' : PV("%s:deltaOmega" % name),
            'start_angle': PV("%s:openSHPos" % name),
        }
        
                    
    def set_params(self, data):
        for key in data.keys():
            self.params[key].put(data[key])
            #print key, data[key]
    
    def scan(self, wait=True):
        self.scan_cmd.put('\x01')
        if wait:
            self.wait(start=True, stop=True)

    def shutter_is_open(self):
        return self.shutter_state.get() == '\x01'

    def is_active(self):
        return self.state.get() != 0
            
    def wait(self, start=True, stop=True, poll=0.001, timeout=20):
        if (start):
            time_left = 2
            #print 'waiting for shutter to open'
            while not self.is_active() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
        if (stop):
            time_left = timeout
            #print 'waiting gonio to stop'
            while self.is_active() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
            #time.sleep(0.5) # delay between shutter close command and actual closing
    
class MarCCD2(CCDDetector):
    def __init__(self, name):
        #house_keeping
        self.name = name
        self.collect_cmd = PV("%s:frameCollect:cmd" % name)

        #Status parameters
        self.state = PV("%s:dataCol:status" % name)

        #Header parameters
        self.header = {
            'filename' : PV("%s:img:filename" % name),
            'directory': PV("%s:img:dirname" % name),
            'beam_x' : PV("%s:beam:x" % name),
            'beam_y' : PV("%s:beam:y" % name),
            'distance' : PV("%s:distance" % name),
            'time' : PV("%s:exposureTime" % name),
            'axis' : PV("%s:rot:axis" % name),
            'wavelength':  PV("%s:src:wavelgth" % name),
            'delta' : PV("%s:omega:incr" % name),
            'frame_number': PV("%s:startFrame" % name),
            'prefix' : PV("%s:img:prefix" % name),
            'start_angle': PV("%s:start:omega" % name),
            'energy': PV("%s:runEnergy" % name),            
        }
        #Status parameters
        self.state = PV("%s:rawState" % name)
        self.state_bits = ['None','queue','exec','queue+exec','err','queue+err','exec+err','queue+exec+err','busy']
        self.state_names = ['unused','unused','dezinger','write','correct','read','acquire','state']
            
    def set_header(self, data):
        for key in data.keys():
            self.header[key].put(data[key])
            
    def wait_until(self,state, timeout=10.0):      
        #print "waiting for state '%s'" % state
        st_time = time.time()
        elapsed = time.time() - st_time

        while (not self.check_state(state)) and elapsed < timeout:
            elapsed = time.time() - st_time
            time.sleep(0.001)
        if elapsed < timeout:
            return True
        else:
            return False

    def wait_while(self,state):
        #print "waiting for state '%s' to expire" % state
        while self.check_state(state):
            time.sleep(0.001)
        return True
        
    def check_state(self, key):
        if key in self.state_list():
            return True
        else:
            return False

    def wait_stop(self):      
        while not self.get_state():
            #print 'waiting for stop', self.get_state()
            time.sleep(0.001)
   
    def state_list(self):
        state_string = "%08x" % self.state.get()
        states = []
        for i in range(8):
            state_val = int(state_string[i])
            if state_val != 0:
                state_unit = "%s:%s" % (self.state_names[i],self.state_bits[state_val])
                states.append(state_unit)
        if len(states) == 0:
            states.append('idle')
        return states
        
    def wait_start(self):
        while self.get_state():
            #print 'waiting for start', self.get_state()
            time.sleep(0.001)
        
    def get_state(self):
        if self.state.get() == 0:
            return True
        else:
            return False
                        
    def start(self):
        self.wait_while('acquire:queue')
        self.wait_while('acquire:exec')
        self.wait_while('read:exec')
        self.collect_cmd.put(1)
        self.wait_until('acquire:exec')
        self.wait_until('write:exec')
