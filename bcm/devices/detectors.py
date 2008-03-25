from bcm.interfaces.detectors import *
from bcm.protocols import ca
from zope.interface import implements
import time
import threading
import numpy
import gobject

class DetectorException(Exception):
    def __init__(self, message):
        self.message = message
        
    def __str__(self):
        return 'Detector Exception %s' % self.message
    
class DetectorBase(gobject.GObject):
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "log": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
        }  

    def __init__(self):
        gobject.GObject.__init__(self)
        self._last_changed = time.time()
        self._change_interval = 0.1
    
    def _signal_change(self, obj, value):
        if time.time() - self._last_changed > self._change_interval:
            gobject.idle_add(self.emit,'changed', value)
            self._last_changed = time.time()
    
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)
       
class MCA(DetectorBase):
    implements(IMultiChannelAnalyzer)
    def __init__(self, name, channels=4096):
        DetectorBase.__init__(self)
        name_parts = name.split(':')
        self.spectrum = ca.PV(name)
        self.count_time = ca.PV("%s.PRTM" % name)
        self.time_left = ca.PV("%s:timeRem" % name_parts[0])
        self.READ = ca.PV("%s.READ" % name)
        self.RDNG = ca.PV("%s.RDNG" % name)
        self.START = ca.PV("%s.ERST" % name)
        self.IDTIM = ca.PV("%s.IDTIM" % name)
        self.TMODE = ca.PV("%s:Rontec1SetMode" % name_parts[0])
        self.SCAN = ca.PV("%s.SCAN" % name)
        self.ACQG = ca.PV("%s.ACQG" % name)
        self.status_scan = ca.PV("%s:mca1Status.SCAN" % name_parts[0])
        self.read_scan = ca.PV("%s:mca1Read.SCAN" % name_parts[0])
        self.channels = channels
        self.ROI = (0, self.channels)
        
        # Default parameters
        self.half_roi_width = 15 # in channel units 
        self.offset = -0.45347
        self.slope = 0.00498
        self._monitor_id = None

    def set_cooling(state):
        if state:
            self.TMODE.put(2)
        else:
            self.TMODE.put(0)

    def channel_to_energy(self, x):
        return ( x * self.slope + self.offset)
    
    def energy_to_channel(self, y):
        return   int(round((y - self.offset) / self.slope))
        
    def set_channel_ROI(self, roi=None):
        if roi is None:
            self.ROI = (0,self.channels)
        else:
            self.ROI = roi

    def set_energy_ROI(self, roi=None):
        if roi is None:
            self.ROI = (0,self.channels)
        else:
            lo_ch, hi_ch = energyToChannel(roi[0]), energyToChannel(roi[1])
            self.ROI = (lo_ch, hi_ch)

                    
    def set_energy(self, energy):
        midp = self.energy_to_channel(energy)
        self.ROI = (midp - self.half_roi_width, midp + self.half_roi_width)

    def set_channel(self, channel):
        self.ROI = (channel - self.half_roi_width, channel + self.half_roi_width)
               
    def count(self, t=1.0):
        self.status_scan.put(9)
        self.read_scan.put(0)
        self._collect(t)
        return self.get_value()        

    def acquire(self, t=1.0):
        self.status_scan.put(9)
        self.read_scan.put(0)
        self._collect(t)
        return self.get_spectrum()        
        
    def get_value(self):
        if not self.ROI:
            self.values = self.data
        else:
            self.values = self.data[self.ROI[0]:self.ROI[1]]
        return numpy.sum(self.values)
            
    def get_spectrum(self):
        x = self.channel_to_energy( numpy.arange(0,4096,1) )
        return (x, self.data)
        
    def _start(self, retries=5, timeout=5):
        i = 0
        success = False
        while i < retries and not success:
            i += 1
            self.START.put(1)
            success = self._wait_count(start=True, stop=False, timeout=timeout)
        if i==retries and not success:
            self._log('ERROR: MCA acquire failed')
                  
    def _read(self, retries=3, timeout=5):
        i = 0
        success = False
        while i < retries and not success:
            self.READ.put(1)
            success = self._wait_read(start=True, stop=False, timeout=timeout)
        if i==retries and not success:
            self._log('ERROR: MCA reading failed')
            
    def _collect(self, t=1.0):
        self.set_temp_monitor(False)
        self.count_time.put(t)
        self._start()
        #self.wait_count(start=False,stop=True)
        self._wait_read(start=True,stop=True)
        self.data = self.spectrum.get()
        self.set_temp_monitor(True)

    def _set_temp_monitor(self, mode):
        if mode:
              self._monitor_id = gobject.timeout_add(300000, self.set_cooling, False)
        elif self._monitor_id:
            gobject.source_remove(self._monitor_id)

    def _wait_count(self, start=False,stop=True,poll=0.05, timeout=5):
        if (start):
            time_left = timeout
            while self.ACQG.get() == 0 and time_left > 0:
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                return False
                
        if (stop):
            time_left = timeout
            while self.ACQG.get() !=0 and time_left > 0:
                test = self.ACQG.get()         
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                return False
        return True        
                
    def _wait_read(self, start=False,stop=True, poll=0.05, timeout=5):       
        if (start):
            time_left = timeout
            while self.RDNG.get() == 0 and time_left > 0:
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                return False
        if (stop):
            time_left = timeout
            while self.RDNG.get() != 0 and time_left > 0:
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                return False
        return True        

class QBPM(DetectorBase):
    implements(IBeamPositionMonitor)
    def __init__(self, A, B, C, D):
        DetectorBase.__init__(self)
        self.A = ca.PV(A)
        self.B = ca.PV(B)
        self.C = ca.PV(C)
        self.D = ca.PV(D)
        self.x_factor = 1.0
        self.y_factor = 1.0
        self.x_offset = 0.0
        self.y_offset = 0.0
        self.A.connect('changed', self._signal_change)
        self.B.connect('changed', self._signal_change)
        self.C.connect('changed', self._signal_change)
        self.D.connect('changed', self._signal_change)
        self._last_changed = time.time()
        self._change_interval = 0.1


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
    
    def count(self, t):
        interval=0.01
        values = []
        time_left = t
        while time_left > 0.0:
            values.append( self.get_value() )
            time_left -= interval
        total = (t/interval) * sum(values, 0.0)/len(values)
        return total
        
    def _signal_change(self, obj, val):
        DetectorBase._signal_change(self, obj, self.get_value())

        
    def get_value(self):
        a, b, c, d = self.A.get(), self.B.get(), self.C.get(), self.D.get()
        return a + b + c + d
    
class Counter(DetectorBase):
    implements(ICounter)
    def __init__(self, pv_name):
        DetectorBase.__init__(self)
        self.name = pv_name     
        self.pv = ca.PV(pv_name)
        self.pv.connect('changed', self._signal_change)
    
    def count(self, t):
        self.time = t
        worker_thread = threading.Thread(target=self._do_count)
        worker_thread.start()
        worker_thread.join()
        return self.total_count
        
                  
    def _do_count(self):
        ca.thread_init()
        interval=0.05
        values = []
        time_left = self.time
        while time_left > 0.0:
            print time_left
            values.append( self.pv.get() )
            time.sleep(interval)
            time_left -= interval
        total = sum(values, 0.0)/len(values)
        self.total_count = total
                        
    def get_value(self):    
        return self.pv.get()
        
class MarCCDImager:
    implements(IImagingDetector)
    def __init__(self, name):
        self.name = name
        self.start_cmd = ca.PV("%s:start:cmd" % name)
        self.abort_cmd = ca.PV("%s:abort:cmd" % name)
        self.readout_cmd = ca.PV("%s:correct:cmd" % name)
        self.writefile_cmd = ca.PV("%s:writefile:cmd" % name)
        self.background_cmd = ca.PV("%s:dezFrm:cmd" % name)
        self.save_cmd = ca.PV("%s:rdwrOut:cmd" % name)
        self.collect_cmd = ca.PV("%s:frameCollect:cmd" % name)
        self.header_cmd = ca.PV("%s:header:cmd" % name)
        self.readout_flag = ca.PV("%s:readout:flag" % name)
        
        #Header parameters
        self.header = {
            'filename' : ca.PV("%s:img:filename" % name),
            'directory': ca.PV("%s:img:dirname" % name),
            'beam_x' : ca.PV("%s:beam:x" % name),
            'beam_y' : ca.PV("%s:beam:y" % name),
            'distance' : ca.PV("%s:distance" % name),
            'time' : ca.PV("%s:exposureTime" % name),
            'axis' : ca.PV("%s:rot:axis" % name),
            'wavelength':  ca.PV("%s:src:wavelgth" % name),
            'delta' : ca.PV("%s:omega:incr" % name),
            'frame_number': ca.PV("%s:startFrame" % name),
            'prefix' : ca.PV("%s:img:prefix" % name),
            'start_angle': ca.PV("%s:start:omega" % name),
            'energy': ca.PV("%s:runEnergy" % name),            
        }
                
        #Status parameters
        self.state = ca.PV("%s:rawState" % name)
        self.state_bits = ['None','queue','exec','queue+exec','err','queue+err','exec+err','queue+exec+err','busy']
        self.state_names = ['unused','unused','dezinger','write','correct','read','acquire','state']
        self._bg_taken = False
                      
    def start(self):
        if not self._bg_taken:
            self.initialize(wait=True)
        self._wait_in_state('acquire:queue')
        self._wait_in_state('acquire:exec')
        self.start_cmd.put(1)
        self._wait_for_state('acquire:exec')
        
    def set_parameters(self, data):
        for key in data.keys():
            self.header[key].put(data[key])        
        self.header_cmd.put(1)
    
    def save(self,wait=False):
        self.readout_flag.put(0)
        self.save_cmd.put(1)
        if wait:
            self._wait_for_state('read:exec')

    def _get_states(self):
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

    def _wait_for_state(self,state, timeout=5.0):      
        tf = time.time()
        tI = int(tf)
        st_time = time.time()
        elapsed = time.time() - st_time

        while (not self._is_in_state(state)) and elapsed < timeout:
            elapsed = time.time() - st_time
            time.sleep(0.001)
        if elapsed < timeout:
            return True
        else:
            return False

    def _wait_in_state(self,state):      
        tf = time.time()
        tI = int(tf)
        st_time = time.time()
        elapsed = time.time() - st_time
        while self._is_in_state(state):
            elapsed = time.time() - st_time
            time.sleep(0.001)
        return True
        
    def _is_in_state(self, key):
        if key in self._get_states():
            return True
        else:
            return False

    def initialize(self, wait=True):
        self._wait_in_state('acquire:queue')
        self._wait_in_state('acquire:exec')
        self.background_cmd.put(1)
        self._bg_taken = True
        if wait:
            self._wait_for_state('acquire:exec')
            self._wait_for_state('idle')
                        
            

class Normalizer(threading.Thread):
    def __init__(self, dev=None):
        threading.Thread.__init__(self)
        self.factor = 1.0
        self.start_counting = False
        self.stopped = False
        self.interval = 0.05
        self.set_time(1.0)
        self.device = dev
        self.first = 1.0
        self.factor = 1.0
        
        # Enable the use of both PVs and positioners 
        if not hasattr(dev, 'get_value') and hasattr(dev, 'get'):
            self.device.get_value = self.device.get
            

    def get_factor(self):
        return self.factor

    def set_time(self, t=1.0):
        self.duration = t
        self.accum = numpy.zeros( (self.duration / self.interval), numpy.float64)
    
    def initialize(self):
        if self.device:
            self.first = self.device.get_value()
        
    def stop(self):
        self.stopped = True
                        
    def run(self):
        ca.thread_init()
        if not self.device:
            self.factor = 1.0
            return
        self.initialize()
        self.count = 0
        while not self.stopped:
            self.accum[ self.count ] = self.device.get_value()
            self.count = (self.count + 1) % len(self.accum)
            self.factor = self.first/numpy.mean(self.accum)
            time.sleep(self.interval)   
   
gobject.type_register(DetectorBase)
    
