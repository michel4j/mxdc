#!/usr/bin/env python

import sys, time
import gtk, gobject
from pylab import load
import EpicsCA
import thread
from FakeExcite import *

class Detector(gobject.GObject):
    def __init__(self, name=None):
        gobject.GObject.__init__(self)
        self.value = 100
        self.index = 0
        self.name = name
    
    def count(self, t=1.0):
        self.value += 1
        time.sleep(t)
        return self.value

    def copy(self):
        tmp = Detector(self.name)
        return tmp
        
    def setup(self, **args):
        pass
    
    def get_value(self):
        return self.value

    def get_name(self):
        return self.name
        
class FakeDetector(Detector):
    def __init__(self, name=None):
        Detector.__init__(self, name)
        self.data = load("data/raw.dat",'#')
        self.ypoints = self.data[:,1]
        self.index = 0

    def count(self, t=1.0):
        self.value = self.ypoints[self.index]
        if self.index < len(self.ypoints):
            self.index += 1
        else:
            self.index = 0
        time.sleep(t)
        return self.value

    def copy(self):
        tmp = FakeDetector(self.name)
        return tmp

    def get_name(self):
        return self.name

class FakeMCA(Detector):
    def __init__(self, name=None, channels=4096):
        Detector.__init__(self, name)
        self.data = load("data/raw.dat",'#')
        self.ypoints = self.data[:,1]
        self.index = 0
        self.channels = channels
        self.ROI = (0,self.channels)
        self.offset = -0.45347
        self.slope = 0.00498
        
    def count(self, t=1.0):
        self.value = self.ypoints[self.index]
        self.index = self.index % len(self.ypoints) + 1
        time.sleep(t)
        return self.value

    def set_roi(self, roi=None):
        if roi is None:
            self.ROI = (0,self.channels)
        else:
            self.ROI = roi

    def set_roi_energy(self, energy):
        midp = int(round((energy - self.offset) / self.slope))
        self.ROI = (midp-15, midp+15)
        
    def get_spectrum(self):
        if not self.ROI:
            self.values = self.spectrum
        else:
            self.values = (self.spectrum[0][self.ROI[0]:self.ROI[1]], self.spectrum[1][self.ROI[0]:self.ROI[1]])
        return self.values

    def acquire(self, t=1.0):
    	time.sleep(t)
        self.spectrum = gen_spectrum()
        return self.get_spectrum()                
        
    def copy(self):
        tmp = FakeMCA(self.name)
        return tmp

    def get_name(self):
        return self.name

class EpicsMCA(Detector):
    MCAException = "MCA Exception"
    def __init__(self, name=None, channels=4096):
        Detector.__init__(self,name)
        self.name = name     
        if (not name):
            raise self.MCAException, "name must be specified"
        name_parts = name.split(':')
        self.spectrum = EpicsCA.PV(name, use_monitor=False)
        self.count_time = EpicsCA.PV("%s:mca1.PRTM" % name_parts[0], use_monitor = False)
        self.time_left = EpicsCA.PV("%s:timeRem" % name_parts[0])
        self.READ = EpicsCA.PV("%s:mca1.READ" % name_parts[0], use_monitor = False)
        self.read_status = self.READ
        self.START = EpicsCA.PV("%s:mca1EraseStart" % name_parts[0], use_monitor = False)
        self.dead_time = EpicsCA.PV("%s.IDTIM" % name, use_monitor = False)
        self.channels = channels
        self.ROI = (0, self.channels)
        self.offset = -0.45347
        self.slope = 0.00498
    

    def _debug(self):
        print self.read_status.value
        return True
        
    def set_roi(self, roi=None):
        if roi is None:
            self.ROI = (0,self.channels)
        else:
            self.ROI = roi
            
    def set_roi_energy(self, energy):
        midp = int(round((energy - self.offset) / self.slope))
        self.ROI = (midp-15, midp+15)
        
        
    def copy(self):
        tmp = EpicsMCA(self.name)
        tmp.setup(roi=self.ROI)
        tmp.full_mode = self.full_mode
        return tmp
    
    def _collect(self, t=1.0):
        print "%s aquiring for %0.1f secs" % (self.name, t)
        self.count_time.value = t
        self.START.value = 1
        self._wait_count(start=True, stop=True)
        self.READ.value = 1
        self._wait_read(start=True, stop=True)
        self.data = self.spectrum.value
        print "%s finished aquiring" % (self.name)
    
    def count(self, t=1.0):
        self._collect()
        return self.get_value()        

    def acquire(self, t=1.0):
        self._collect()
        return self.get_spectrum()        
        
    def get_value(self):
        if not self.ROI:
            self.values = self.data
        else:
            self.values = self.data[self.ROI[0]:self.ROI[1]]
        return sum(self.values)
    
    def get_spectrum(self):
        if not self.ROI:
            self.values = self.data
        else:
            self.values = self.data[self.ROI[0]:self.ROI[1]]
        return self.values
        
    def _wait_count(self, start=False,stop=True,poll=0.01):
        st_time = time.time()
        if (start):
            while self.time_left.value == 0.0:
                time.sleep(poll)
        if (stop):
            while self.time_left.value > 0.0:
                time.sleep(poll)
                
    def _wait_read(self, start=False,stop=True,poll=0.01):       
        if (start):
            while self.read_status.value != 1:
                time.sleep(poll)                
        if (stop):
            while self.read_status.value != 0:
                time.sleep(poll)
        
        
    
