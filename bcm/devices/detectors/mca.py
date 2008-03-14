from bcm.interfaces.detectors import IMultiChannelAnalyzer
from bcm.protocols.ca import PV
from zope.interface import implements

class MCAException(Exception):
    def __init__(self, message):
        self.message = message
        
    def __str__(self):
        return 'MCA Exception %s' % self.message
        
class MCA:
    implements(IMultiChannelAnalyzer)
    def __init__(self, name, channels=4096):
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
        self._monitor_id = None

    def channelToEnergy(self, x):
        return ( x * self.slope + self.offset)
    
    def energyToChannel(self, y):
        return   int(round((y - self.offset) / self.slope))
        
    def setRoi(self, roi=None):
        if roi is None:
            self.ROI = (0,self.channels)
        else:
            self.ROI = roi

    def setCooling(state):
        if state:
            self.TMODE.put(2)
        else:
            self.TMODE.put(0)
                    
    def set_roi_energy(self, energy):
        midp = self.energyToChannel(energy)
        self.ROI = (midp-15, midp+15)
               
    def count(self, t=1.0):
        self._collect(t)
        return self.getValue()        

    def acquire(self, t=1.0):
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
            raise MCAException('MCA acquire failed')
                  
    def _read(self, retries=3, timeout=5):
        i = 0
        success = False
        while i < retries and not success:
            self.READ.put(1)
            success = self._wait_read(start=True, stop=False, timeout=timeout)
        if i==retries and not success:
            raise MCAException('MCA reading failed')
            
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
              self._monitor_id = gobject.timeout_add(300000, self.disable_peltier)
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
