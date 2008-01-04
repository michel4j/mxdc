#!/usr/bin/env python

import sys, os, time
import gtk, gobject
import numpy
import thread, threading
from LogServer import LogServer
from EmissionTools import gen_spectrum, find_peaks
from EPICS import PV, thread_init
from pylab import load

class Detector(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['changed'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    DetectorException = "Detector Exception"
    def __init__(self, name=None):
        gobject.GObject.__init__(self)
        self.value = 100
        self.index = 0
        self.interval = 1.0
        self.tick = time.time()
        self.name = name
    
    def count(self, t=1.0):
        self.value += 1
        time.sleep(t)
        return self.value

    def get_value(self):
        return self.value

    def get_name(self):
        return self.name
    
    def signal_change(self):
        if (time.time() - self.tick) > self.interval:
            gobject.idle_add(self.emit, 'changed')
            self.tick = time.time()
       
class FakeDetector(Detector):
    def __init__(self, name=None):
        Detector.__init__(self, name)
        if sys.path[0] == '':
            file_path = os.getcwd()
        else:
            file_path = sys.path[0]
        filename = file_path + "/data/raw.dat"
        self.data = load(filename,'#')
        self.ypoints = self.data[:,1]
        self.index = 0

    def count(self, t=1.0):
        self.value = self.ypoints[self.index]
        self.index = (self.index + 1) % len(self.ypoints)
        time.sleep(t)
        return self.value

    def get_name(self):
        return self.name

class FakeMCA(Detector):
    def __init__(self, name=None, channels=4096):
        Detector.__init__(self, name)
        if sys.path[0] == '':
            file_path = os.getcwd()
        else:
            file_path = sys.path[0]
        filename = file_path + "/data/raw.dat"
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
        self.index = (self.index + 1) % len(self.ypoints)
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
        return [x, self.data]
    

    def _collect(self, t=1.0):
    	time.sleep(t)
        self.data = gen_spectrum()

    def acquire(self, t=1.0):
        self._collect(t)
        return self.get_spectrum()                
        
    def get_name(self):
        return self.name

    def set_cooling(self, mode):
        return

class EpicsMCA(Detector):
    def __init__(self, name=None, channels=4096):
        Detector.__init__(self,name)
        self.name = name     
        if (not name):
            raise self.MCAException, "name must be specified"
        name_parts = name.split(':')
        self.spectrum = PV(name)
        self.count_time = PV("%s.PRTM" % name)
        self.time_left = PV("%s:timeRem" % name_parts[0])
        self.READ = PV("%s.READ" % name)
        self.RDNG = PV("%s.RDNG" % name)
        self.START = PV("%s.ERST" % name)
        self.IDTIM = PV("%s.IDTIM" % name)
        self.TMODE = PV("%s:Rontec1SetMode" % name_parts[0])
        self.SCAN = PV("%s.SCAN" % name)
        self.ACQG = PV("%s.ACQG" % name)
        self.status_scan = PV("%s:mca1Status.SCAN" % name_parts[0])
        self.read_scan = PV("%s:mca1Read.SCAN" % name_parts[0])
        self.channels = channels
        self.ROI = (0, self.channels)
        self.offset = -0.45347
        self.slope = 0.00498
        self.status_scan.put(9)
        self.read_scan.put(0)
        self.last_activity = time.time()
        gobject.timeout_add(30000, self._monitor_mode)
            
    def _monitor_mode(self):
        elapsed_time = time.time() - self.last_activity
        if elapsed_time > 300:
            LogServer.log("%s MCA: No activity after %d seconds. Turning peltier off." % (self.name, elapsed_time))
            self.last_activity = time.time()
            self.set_cooling(False)
        return True

    def _roi_to_energy(self, x):
        return ( x * self.slope + self.offset)
    
    def _energy_to_roi(self, y):
        return   int(round((y - self.offset) / self.slope))
        
    def set_roi(self, roi=None):
        if roi is None:
            self.ROI = (0,self.channels)
        else:
            self.ROI = roi

    def set_cooling(self, mode):
        self.last_activity = time.time()
        if mode:
            self.TMODE.put(1)
        else:
            self.TMODE.put(0)
                    
    def set_roi_energy(self, energy):
        midp = self._energy_to_roi(energy)
        self.ROI = (midp-15, midp+15)
               
    def _start(self, retries=5, timeout=5):
        i = 0
        success = False
        while i < retries and not success:
            if i > 0:
                LogServer.log( "%s MCA could not start. Retry %d" % (self.name, i))
            i += 1
            self.START.put(1)
            success = self.wait_count(start=True, stop=False, timeout=timeout)
        if i==retries and not success:
            LogServer.log( "MCA acquire failed. Could not start after %s attempts." % i )
            raise DetectorException, 'MCA acquire failed'
                  
    def _read(self, retries=3, timeout=5):
        i = 0
        success = False
        while i < retries and not success:
            if i > 0:
                LogServer.log( "%s MCA could not read. Retry %d" % (self.name, i))
            i += 1
            self.READ.put(1)
            success = self.wait_read(start=True, stop=False, timeout=timeout)
        if i==retries and not success:
            raise DetectorException, 'MCA reading failed'
            
    def _collect(self, t=1.0):
        self.last_activity = time.time()
        LogServer.log( "%s aquiring for %0.1f secs" % (self.name, t))
        self.count_time.put(t)
        self._start()
        #self.wait_count(start=False,stop=True)
        self.wait_read(start=True,stop=True)
        self.data = self.spectrum.get()
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
        return numpy.sum(self.values)
    
    def get_dead_percent(self):
        return self.IDTIM.get()
        
    def get_spectrum(self):
        x = self._roi_to_energy( numpy.arange(0,4096,1) )
        return (x, self.data)
        
    def wait_count(self, start=False,stop=True,poll=0.05, timeout=5):
        if (start):
            time_left = timeout
            LogServer.log( "%s waiting for MCA to start counting" % (self.name))
            while self.ACQG.get() == 0 and time_left > 0:
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                return False
                
        if (stop):
            time_left = timeout
            LogServer.log( "%s waiting for MCA to stop counting" % (self.name))
            while self.ACQG.get() !=0 and time_left > 0:
                test = self.ACQG.get()         
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                return False
        return True        
                
    def wait_read(self, start=False,stop=True, poll=0.05, timeout=5):       
        if (start):
            time_left = timeout
            LogServer.log("%s waiting for MCA to start reading" % (self.name) )
            while self.RDNG.get() == 0 and time_left > 0:
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                return False
        if (stop):
            time_left = timeout
            LogServer.log("%s waiting for MCA to finish reading" % (self.name) )
            while self.RDNG.get() != 0 and time_left > 0:
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                return False
        return True        
        
class EpicsDetector(Detector):
    def __init__(self, name=None):
        Detector.__init__(self, name)
        if (not name):
            raise self.DetectorException, "name must be specified"
        self.name = name
        self.pv = PV(name)
                
    def count(self, t=1.0):
        interval = 0.01
        accum = []
        while t > 0:
            accum.append( self.pv.get() )
            time.sleep(interval)
            t -= interval
        return numpy.mean(accum)
                        
    def get_value(self):    
        return self.pv.get()
        
    def get_name(self):
        return self.name

class Normalizer(threading.Thread):
    def __init__(self, det=None):
        threading.Thread.__init__(self)
        self.factor = 1.0
        self.start_counting = False
        self.stopped = False
        self.interval = 0.01
        self.set_time(1.0)
        self.detector = det
        self.first = 1.0
        self.factor = 1.0

    def get_factor(self):
        return self.factor

    def set_time(self, t=1.0):
        self.duration = t
        self.accum = numpy.zeros( (self.duration / self.interval), numpy.float64)
    
    def initialize(self):
        self.first = self.detector.get_value()
        
    def stop(self):
        self.stopped = True
                        
    def run(self):
        thread_init()
        if not self.detector:
            self.factor = 1.0
            return
        self.initialize()
        self.count = 0
        while not self.stopped:
            self.accum[ self.count ] = self.detector.get_value()
            self.count = (self.count + 1) % len(self.accum)
            self.factor = self.first/numpy.mean(self.accum)
            time.sleep(self.interval)
            

class QBPM:
    def __init__(self, A, B, C, D):
        self.A = PV(A)
        self.B = PV(B)
        self.C = PV(C)
        self.D = PV(D)
        self.x_factor = 1.0
        self.y_factor = 1.0
        self.x_offset = 0.0
        self.y_offset = 0.0

    def set_factors(self, xf=1, yf=1):
        self.x_factor = xf
        self.y_factor = yf
    
    def set_offsets(self, xoff=0, yoff=0):
        self.x_offset = xoff
        self.y_offset = yoff

    def get_position(self):
        a = self.A.get()
        b= self.B.get()
        c = self.C.get()
        d = self.D.get()
        sumy = (a + b) - self.y_offset
        sumx = (c + d) - self.x_offset
        if sumy == 0.0:
            sumy = 1.0e-10
        if sumx == 0.0:
            sumx = 1.0e-10
        y = self.y_factor * (a - b) / sumy
        x = self.x_factor * (c - d) / sumx
        return [x, y]
    
    def sum(self):
        a, b, c, d = self.A.get(), self.B.get(), self.C.get(), self.D.get()
        return a + b + c + d
   
gobject.type_register(Detector)
    
