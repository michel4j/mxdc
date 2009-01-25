class Counter(DetectorBase):
    implements(ICounter)
    def __init__(self, pv_name):
        DetectorBase.__init__(self)
        self.name = pv_name     
        self.pv = ca.PV(pv_name)
        self.pv.connect('changed', self._signal_change)
    
    def count(self, t):
        detector_logger.info('Integrating detector (%s) for %0.2f sec.' % (self.name, t) )
        interval=0.001
        values = []
        time_to_finish = time.time() + t
        while time.time() < time_to_finish:
            values.append( self.pv.get() )
        total = sum(values, 0.0)/len(values)
        return total
                        
    def get_value(self):    
        return self.pv.get()

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
   
