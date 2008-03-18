import threading
import numpy
from bcm.protocols import ca

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

    def get_factor(self):
        return self.factor

    def set_time(self, t=1.0):
        self.duration = t
        self.accum = numpy.zeros( (self.duration / self.interval), numpy.float64)
    
    def initialize(self):
        self.first = self.device.getValue()
        
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
            self.accum[ self.count ] = self.device.getValue()
            self.count = (self.count + 1) % len(self.accum)
            self.factor = self.first/numpy.mean(self.accum)
            time.sleep(self.interval)