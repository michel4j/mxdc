from bcm.interfaces.detectors import IMultiChannelAnalyzer, ICounter, IBeamPositionMonitor
from bcm.protocols.ca import PV
from zope.interface import implements
import time

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
        self._change_interval
    
    def signal_change(self, obj, value):
        if time.time() - self._last_changed > self._change_interval:
            gobject.idle_add(self.emit,'changed', value)
            self._last_changed = time.time()
    
    def log(self, message):
        gobject.idle_add(self.emit, 'log', message)
       
class MCA(DetectorBase):
    implements(IMultiChannelAnalyzer)
    def __init__(self, name, channels=4096):
        DetectorBase.__init__(self)
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
        
        # Default parameters
        self.half_roi_width = 15 # in channel units 
        self.offset = -0.45347
        self.slope = 0.00498
        self._monitor_id = None

    def setCooling(state):
        if state:
            self.TMODE.put(2)
        else:
            self.TMODE.put(0)

    def channelToEnergy(self, x):
        return ( x * self.slope + self.offset)
    
    def energyToChannel(self, y):
        return   int(round((y - self.offset) / self.slope))
        
    def setChannelRoi(self, roi=None):
        if roi is None:
            self.ROI = (0,self.channels)
        else:
            self.ROI = roi

    def setEnergyRoi(self, roi=None):
        if roi is None:
            self.ROI = (0,self.channels)
        else:
            lo_ch, hi_ch = energyToChannel(roi[0]), energyToChannel(roi[1])
            self.ROI = (lo_ch, hi_ch)

                    
    def setEnergy(self, energy):
        midp = self.energyToChannel(energy)
        self.ROI = (midp - self.half_roi_width, midp + self.half_roi_width)

    def setChannel(self, channel):
        self.ROI = (channel - self.half_roi_width, channel + self.half_roi_width)
               
    def count(self, t=1.0):
        self.status_scan.put(9)
        self.read_scan.put(0)
        self._collect(t)
        return self.getValue()        

    def acquire(self, t=1.0):
        self.status_scan.put(9)
        self.read_scan.put(0)
        self._collect(t)
        return self.getSpectrum()        
        
    def getValue(self):
        if not self.ROI:
            self.values = self.data
        else:
            self.values = self.data[self.ROI[0]:self.ROI[1]]
        return numpy.sum(self.values)
            
    def getSpectrum(self):
        x = self.channelToEnergy( numpy.arange(0,4096,1) )
        return (x, self.data)
        
    def _start(self, retries=5, timeout=5):
        i = 0
        success = False
        while i < retries and not success:
            i += 1
            self.START.put(1)
            success = self._wait_count(start=True, stop=False, timeout=timeout)
        if i==retries and not success:
            self.log('ERROR: MCA acquire failed')
                  
    def _read(self, retries=3, timeout=5):
        i = 0
        success = False
        while i < retries and not success:
            self.READ.put(1)
            success = self._wait_read(start=True, stop=False, timeout=timeout)
        if i==retries and not success:
            self.log('ERROR: MCA reading failed')
            
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
              self._monitor_id = gobject.timeout_add(300000, self.setCooling, False)
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
        self.A.connect('changed', self.signal_change)
        self.B.connect('changed', self.signal_change)
        self.C.connect('changed', self.signal_change)
        self.D.connect('changed', self.signal_change)
        self._last_changed = time.time()
        self._change_interval = 0.1


    def setFactors(self, xf=1, yf=1):
        self.x_factor = xf
        self.y_factor = yf
    
    def setOffsets(self, xoff=0, yoff=0):
        self.x_offset = xoff
        self.y_offset = yoff

    def getPosition(self):
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
            values.append( self.getValue() )
            time_left -= interval
        total = (t/interval) * sum(values, 0.0)/len(values)
        return total
        
    def signal_change(self, obj, val):
        DetectorBase.signal_change(self, obj, self.getValue())

        
    def getValue(self):
        a, b, c, d = self.A.get(), self.B.get(), self.C.get(), self.D.get()
        return a + b + c + d
    
class Counter(DetectorBase):
    implements(ICounter)
    def __init__(self, pv_name):
        DetectorBase.__init__(self)
        self.name = pv_name     
        self.pv = PV(pv_name)
        self.pv.connect('changed', self.signal_change)
                
    def count(self, t):
        interval=0.01
        values = []
        time_left = t
        while time_left > 0.0:
            values.append( self.pv.get() )
            time_left -= interval
        total = (t/interval) * sum(values, 0.0)/len(values)
        return total
                        
    def getValue(self):    
        return self.pv.get()
        


            

   
gobject.type_register(Detector)
    
