#!/usr/bin/env python

import numpy
from EPICS import PV
import struct, thread
from scipy.misc import toimage, fromimage

class VideoSource:
    def __init__(self):
        self.visible = True        
        pass
    
    def fetch_frame(self):
        if self.visible:
            self.raw_frame = numpy.zeros([480,640])
            self.frame = toimage(self.frame)                

    def get_frame(self):
        return self.frame    
    
    def set_visible(self, vis):
        self.visible = vis
              
class FakeCamera(VideoSource):
    def __init__(self, name=None):
        VideoSource.__init__(self)
        self.data = []
        self.count = 0
        self.name = name
        for i in range(10):
            self.data.append(numpy.random.randint(0,255, (480,640)))

    def fetch_frame(self):
        if self.visible:
            self.count = (self.count + 1) % 10
            self.raw_frame = self.data[self.count]
            self.frame = toimage(self.frame)                
    
        

class EpicsCamera(VideoSource):
    def __init__(self,name):
        VideoSource.__init__(self)
        self.pvname = name
        self.cam = PV(self.pvname, use_monitor=False)
        self.fetch_frame()
        self.visible = False        
        self.cam.connect('changed', lambda x: self.fetch_frame())
    
    def fetch_frame(self):
        if self.visible:
            self.raw_frame = self.cam.get()
            self.frame = toimage(numpy.fromstring(self.raw_frame, 'B').reshape(480,640))                
        
