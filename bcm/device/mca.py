class DetectorBase(gobject.GObject):
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        }  

    def __init__(self):
        gobject.GObject.__init__(self)
        self._last_changed = time.time()
        self._change_interval = 0.1
        self.name = 'Basic Detector'
    
    def _signal_change(self, obj, value):
        if time.time() - self._last_changed > self._change_interval:
            gobject.idle_add(self.emit,'changed', value)
            self._last_changed = time.time()
    
    def _log(self, message):
        detector_logger.info(message)

    def get_name(self):
        return self.name
       
class MCA(DetectorBase):
    implements(IMultiChannelAnalyzer)
    def __init__(self, name, channels=4096):
        DetectorBase.__init__(self)
        name_parts = name.split(':')
        self.spectrum = ca.PV(name)
        self.count_time = ca.PV("%s.PRTM" % name, monitor=False)
        self.time_left = ca.PV("%s:timeRem" % name_parts[0])
        self.READ = ca.PV("%s.READ" % name, monitor=False)
        self.RDNG = ca.PV("%s.RDNG" % name)
        self.START = ca.PV("%s.ERST" % name, monitor=False)
        self.ERASE = ca.PV("%s.ERAS" % name, monitor=False)
        self.IDTIM = ca.PV("%s.IDTIM" % name, monitor=False)
        self.TMODE = ca.PV("%s:Rontec1SetMode" % name_parts[0], monitor=False)
        self.SCAN = ca.PV("%s.SCAN" % name)
        self.ACQG = ca.PV("%s.ACQG" % name)
        self.status_scan = ca.PV("%s:mca1Status.SCAN" % name_parts[0], monitor=False)
        self.read_scan = ca.PV("%s:mca1Read.SCAN" % name_parts[0], monitor=False)
        self.channels = channels
        self.ROI = (0, self.channels)
        self.name = name_parts[0]
        
        # Default parameters
        self.half_roi_width = 15 # in channel units 
        self.offset = -0.45347
        self.slope = 0.00498
        self._monitor_id = None
        self.name = 'MCA'

        self._read_state = False
        self.RDNG.connect('changed', self._monitor_reading)
    
    def _monitor_reading(self, obj, state):
        if state == 0:
            self._read_state = False
            
    def set_cooling(self, state):
        if state:
            self.TMODE.put(2)
        else:
            self.TMODE.put(0)
    
    def is_cool(self):
        if self.TMODE.get() == 2:
            return True
        else:
            return False

    def channel_to_energy(self, x):
        return ( x * self.slope + self.offset)
    
    def energy_to_channel(self, y):
        return   int(round((y - self.offset) / self.slope))
        
    def set_channel_roi(self, roi=None):
        if roi is None:
            self.ROI = (0,self.channels)
        else:
            self.ROI = roi

    def set_energy_roi(self, roi=None):
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
        self._collect(t)
        return self.get_value()        

    def erase(self):
        self.ERASE.put(0)
        self.status_scan.put(9)
        self.read_scan.put(0)
        self.data = self.spectrum.get()

    def acquire(self, t=1.0):
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
        
    def _start(self, retries=5):
        i = 0
        success = False
        while i < retries and not success:
            i += 1
            self.START.put(1)
            success = self._wait_count()
            self._read_state = True
        if i==retries and not success:
            detector_logger.error('MCA acquire failed after %s retries' % retries)
                              
    def _collect(self, t=1.0):
        self._set_temp_monitor(False)
        self.count_time.put(t)
        self._start()
        self._wait_read()
        self.data = self.spectrum.get()
        self._set_temp_monitor(True)

    def _set_temp_monitor(self, mode):
        if mode:
              self._monitor_id = gobject.timeout_add(300000, self.set_cooling, False)
        elif self._monitor_id:
            gobject.source_remove(self._monitor_id)

    def _wait_count(self, start=True, stop=False,poll=0.05, timeout=2):
        if (start):
            time_left = timeout
            detector_logger.debug('Waiting for MCA to start counting.')
            while self.ACQG.get() == 0 and time_left > 0:
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                detector_logger.warning('Timed out waiting for acquire to start after %d sec' % timeout)
                return False                
        if (stop):
            time_left = timeout
            detector_logger.debug('Waiting for MCA to stop counting.')
            while self.ACQG.get() !=0 and time_left > 0:
                test = self.ACQG.get()         
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                detector_logger.warning('Timed out waiting for acquire to stop after %d sec' % timeout)
                return False
        return True        
                
    def _wait_read(self, poll=0.05, timeout=5):       
        time_left = timeout
        detector_logger.debug('Waiting for MCA to start reading.')
        while self._read_state and time_left > 0:
            time_left -= poll
            time.sleep(poll)
        if time_left <= 0:
            detector_logger.warning('Timed out waiting for READ after %d sec' % timeout)
            return False

