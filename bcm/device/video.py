from zope.interface import implements
from bcm.interfaces.cameras import ICamera
from bcm.protocols.ca import PV
import time, math
import logging

import numpy
from scipy.misc import toimage, fromimage
import Image, ImageOps, ImageDraw, urllib, cStringIO
import httplib

__log_section__ = 'bcm.video'
camera_logger = logging.getLogger(__log_section__)

class CameraBase(object):
    def __init__(self, name='Video'):
        self.frame = None
        self.camera_on = False
        self.controller = None
        self.name = name
            
    def _log(self, message):
        pass

    def get_frame(self):
        return self.frame
    
    def update(self, obj=None, force=None):
        return True
    
    def save(self, filename):
        if self.frame is None:
            camera_logger.error('(%s) No image available to save.' % (self.name,) )
            result = False
        else:
            try:
                img = self.get_frame()
                img.save(filename)
                result = filename
            except:
                camera_logger.error('(%s) Unable to save image "%s".' % (self.name, filename) )
                result = False
        return result

    def get_name(self):
        return self.name
    
    
                 
class CameraSim(CameraBase):
    implements(ICamera)    
    def __init__(self,name='Video'):
        CameraBase.__init__(self,name)
        self._fsource = open('/dev/urandom','rb')
        self._packet_size = 307200
        self.name = name
        self.update()
    
    def __del__(self):
        self._fsource.close()
    
    def update(self, obj=None):
        data = self._fsource.read(self._packet_size)
        self.frame = toimage(numpy.fromstring(data, 'B').reshape(480,640))
        self.size = self.frame.size
        return True
                   
    def get_frame(self):
        if self.update():
            return self.frame
        else:
            return None

class Camera(CameraBase):
    implements(ICamera)    
    def __init__(self, pv_name, name='Video'):
        CameraBase.__init__(self,name)
        self._fsource = open('/dev/urandom','rb')
        self.cam = PV(pv_name)
        self._packet_size = 307200
        self.update()
    
    def __del__(self):
        self._fsource.close()


    def update(self, obj=None, arg=None):
        if self.cam.is_connected():
            data = self.cam.get()
            while len(data) != self._packet_size:
                data = self.cam.get()
        else:
            data = self._fsource.read(self._packet_size)

        self.frame = toimage(numpy.fromstring(data, 'B').reshape(480,640))
        self.size = self.frame.size
        return True

    def get_frame(self):
        if self.update():
            return self.frame
        else:
            return None


                                
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

class AxisCamera(CameraBase):
    implements(ICamera)    
    def __init__(self,hostname, name='Video'):
        CameraBase.__init__(self,name)
        self.url = 'http://%s/jpg/image.jpg' % hostname
        self.controller = AxisController(hostname)
        self.size = (704,480)
        self._last_frame = time.time()
        self.update()

    def _get_image(self):
            f = urllib.urlopen(self.url)
            f_str = cStringIO.StringIO(f.read())
            return Image.open(f_str)

    def update(self, obj=None):
        if time.time() - self._last_frame < 0.1:
            return True
        try:
            self.frame = self._get_image()
            self._last_frame = time.time()
        except:
            camera_logger.error('(%s) Failed fetching frame.' % (self.name,) )
            return False
        return True


    def get_frame(self):
        if self.update():
            return self.frame
        else:
            return None

def add_decorations(bl, img):
    _tick_size = 8
    draw = ImageDraw.Draw(img)
    cross_x = bl.cross_x.get_position()
    cross_y = bl.cross_y.get_position()
    img_w,img_h = img.size
    scale_factor = 1.0
    pixel_size = 5.34e-3 * math.exp( -0.18 * bl.sample_zoom.get_position())
    
    #draw cross
    draw.line([(cross_x-_tick_size, cross_y), (cross_x+_tick_size, cross_y)], fill=128)
    draw.line([(cross_x, cross_y-_tick_size), (cross_x, cross_y+_tick_size)], fill=128)
    
    #draw slits
    slits_x = bl.beam_x.get_position()
    slits_y = bl.beam_y.get_position()   
    slits_width  = bl.beam_w.get_position() / pixel_size
    slits_height = bl.beam_h.get_position() / pixel_size
    
    #if slits_width  >= img_w or slits_height  >= img_h:
    #    return img
    
    x = int((cross_x - (slits_x / pixel_size)) * scale_factor)
    y = int((cross_y - (slits_y / pixel_size)) * scale_factor)
    hw = int(0.5 * slits_width * scale_factor)
    hh = int(0.5 * slits_height * scale_factor)
    draw.line([x-hw, y-hh, x-hw, y-hh+_tick_size], fill=128)
    draw.line([x-hw, y-hh, x-hw+_tick_size, y-hh], fill=128)
    draw.line([x+hw, y+hh, x+hw, y+hh-_tick_size], fill=128)
    draw.line([x+hw, y+hh, x+hw-_tick_size, y+hh], fill=128)

    draw.line([x-hw, y+hh, x-hw, y+hh-_tick_size], fill=128)
    draw.line([x-hw, y+hh, x-hw+_tick_size, y+hh], fill=128)
    draw.line([x+hw, y-hh, x+hw, y-hh+_tick_size], fill=128)
    draw.line([x+hw, y-hh, x+hw-_tick_size, y-hh], fill=128)

    return img