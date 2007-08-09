#!/usr/bin/env python

import sys, time
import gtk, gobject, numpy
from pylab import load
import EpicsCA
import thread
from LogServer import LogServer
from EmissionTools import gen_spectrum, find_peaks

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
            
    def get_value(self):
        return self.value

    def get_name(self):
        return self.name
       
class FakeDetector(Detector):
    def __init__(self, name=None):
        Detector.__init__(self, name)
        filename = sys.path[0] + "/data/raw.dat"
        self.data = load(filename,'#')
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
        filename = sys.path[0] + "/data/raw.dat"
        self.data = load(filename,'#')
        self.ypoints = self.data[:,1]
        self.index = 0
        self.channels = channels
        self.ROI = (0,self.channels)
        self.offset = -0.45347
        self.slope = 0.00498
        
    def _roi_to_energy(self, x):
        return ( x * self.slope + self.offset)
    
    def _energy_to_roi(self, y):
        return   int(round((y - self.offset) / self.slope))

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
        midp = self._energy_to_roi(energy)
        self.ROI = (midp-15, midp+15)
        
    def get_spectrum(self):
        x = self._roi_to_energy( numpy.arange(0,4096,1) )
        return (x, self.data)
    

    def _collect(self, t=1.0):
    	time.sleep(t)
        self.data = gen_spectrum()

    def acquire(self, t=1.0):
        self._collect(t)
        return self.get_spectrum()                
        
    def copy(self):
        tmp = FakeMCA(self.name)
        tmp.set_roi(self.ROI)
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
        self.count_time = EpicsCA.PV("%s:mca1.PRTM" % name_parts[0], use_monitor=False)
        self.time_left = EpicsCA.PV("%s:timeRem" % name_parts[0])
        self.READ = EpicsCA.PV("%s:mca1.READ" % name_parts[0], use_monitor=False)
        self.read_status = self.READ
        self.START = EpicsCA.PV("%s:mca1EraseStart" % name_parts[0], use_monitor=False)
        self.dead_time = EpicsCA.PV("%s.IDTIM" % name, use_monitor=False)
        self.channels = channels
        self.ROI = (0, self.channels)
        self.offset = -0.45347
        self.slope = 0.00498
            
    def _roi_to_energy(self, x):
        return ( x * self.slope + self.offset)
    
    def _energy_to_roi(self, y):
        return   int(round((y - self.offset) / self.slope))
        
    def set_roi(self, roi=None):
        if roi is None:
            self.ROI = (0,self.channels)
        else:
            self.ROI = roi
            
    def set_roi_energy(self, energy):
        midp = self._energy_to_roi(energy)
        self.ROI = (midp-15, midp+15)
               
    def copy(self):
        tmp = EpicsMCA(self.name)
        tmp.set_roi(roi=self.ROI)
        return tmp
    
    def _collect(self, t=1.0):
        LogServer.log( "%s aquiring for %0.1f secs" % (self.name, t))
        self.count_time.value = t
        self.START.value = 1
        LogServer.log("%s waiting for start" % (self.name) )
        self._wait_count(start=True, stop=True)
        self.READ.value = 1
        LogServer.log("%s waiting for read" % (self.name))
        self._wait_read(start=True, stop=True)
        self.data = self.spectrum.value
        LogServer.log("%s finished aquiring" % (self.name))
    
    def count(self, t=1.0):
        self._collect(t)
        return self.get_value()        

    def acquire(self, t=1.0):
        self._collect(t)
        return self.get_spectrum()        
        
    def get_value(self):
        if not self.ROI:
            self.values = self.data
        else:
            self.values = self.data[self.ROI[0]:self.ROI[1]]
        return sum(self.values)
    
    def get_spectrum(self):
        x = self._roi_to_energy( numpy.arange(0,4096,1) )
        return (x, self.data)
        
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
        
        
    
