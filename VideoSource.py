#!/usr/bin/env python

import numpy
from EPICS import PV
import struct
from scipy.misc import toimage, fromimage

class VideoSource:
    def __init__(self):
        pass
    
    def get_frame(self):
        self.frame = numpy.zeros([480,640])
        return toimage(self.frame)                

    def copy(self):
        return VideoSource()        
        
class FakeCamera(VideoSource):
    def __init__(self, name=None):
        VideoSource.__init__(self)
        self.data = []
        self.count = 0
        self.name = name
        for i in range(10):
            self.data.append(numpy.random.randint(0,255, (480,640)))

    def get_frame(self):
        self.count = (self.count + 1) % 10
        self.frame = self.data[self.count]
        return toimage(self.frame)                

    def copy(self):
        tmp = FakeCamera(self.name)
        return tmp

class EpicsCamera(VideoSource):
    def __init__(self,name):
        VideoSource.__init__(self)
        self.pvname = name
        self.cam = PV(self.pvname)
        self.frame = self.cam.get()
    
    def get_frame(self):
        self.frame = self.cam.get()
        #self.frame = self.frame + struct.pack('B',0)*(307200-len(self.frame))
        return toimage(numpy.fromstring(self.frame, 'B').reshape(480,640))                

    def copy(self):
        tmp = EpicsCamera(self.pvname)
        return tmp
