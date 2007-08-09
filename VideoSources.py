#!/usr/bin/env python

import numpy
from EPICS import PV
import struct, thread
from scipy.misc import toimage, fromimage
import Image, ImageOps, urllib, cStringIO
import httplib

class VideoSource:
    def __init__(self):
        self.visible = True        
        self.controller = None
            
    def fetch_frame(self):
        if self.visible:
            self.raw_frame = numpy.zeros([480,640])
            self.frame = toimage(self.frame)                

    def get_frame(self):
        self.fetch_frame()
        return self.frame    
    
    def set_visible(self, vis):
        self.visible = vis

    def save(self, filename):
        try:
            img = ImageOps.autocontrast(self.frame)
            img.save(filename)
        except:
            print 'Could not save image:', filename
              
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
        self.cam = PV(self.pvname, connect=True)
        self.fetch_frame()
        self.visible = False        
    
    def fetch_frame(self):
        if self.visible:
            self.raw_frame = self.cam.get()
            self.frame = toimage(numpy.fromstring(self.raw_frame, 'B').reshape(480,640))                
        
class AxisController:
    def __init__(self,hostname):
        self.server = httplib.HTTPConnection(hostname)
        self.rzoom = 0
        
    def zoom(self,value):
        self.server.connect()
        command = "/axis-cgi/com/ptz.cgi?rzoom=%s" % value
        result = self.server.request("GET", command)
        self.rzoom -= value
        self.server.close()
        return

    def center(self, x, y):
        self.server.connect()
        command = "/axis-cgi/com/ptz.cgi?center=%d,%d" % (x, y)
        result = self.server.request("GET", command)
        self.server.close()
        return
    
    def goto(self, position):
        self.server.connect()
        position = urllib.quote_plus(position)
        command = "/axis-cgi/com/ptz.cgi?gotoserverpresetname=%s" % position
        result = self.server.request("GET", command)
        self.rzoom = 0
        self.server.close()
        return

class AxisServer(VideoSource):
    def __init__(self,hostname):
        VideoSource.__init__(self)
        self.url = 'http://%s/jpg/image.jpg' % hostname
        self.controller = AxisController(hostname)
        self.fetch_frame()
        self.visible = False        
    
    def fetch_frame(self):
        if self.visible:
            img_file = urllib.urlopen(self.url)
            img_str = cStringIO.StringIO(img_file.read())
            self.frame = Image.open(img_str)


        
