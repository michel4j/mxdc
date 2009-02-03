import time
import math
import logging
import urllib
import cStringIO
import httplib
import Image
import ImageDraw
import warnings
warnings.simplefilter("ignore")
import numpy
from scipy.misc import toimage, fromimage
from zope.interface import implements
from bcm.device.interfaces import ICamera, IPTZCameraController, IMotor
from bcm.protocol.ca import PV
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class VideoError(Exception):

    """Base class for errors in the video module."""
    

class CameraBase(object):

    def __init__(self, name="Basic Camera"):
        self.frame = None
        self.name = name
        self.resolution = 1.0
    
    def zoom(self):
        pass
                       
    def save(self, filename):
        if self.frame is None:
            _logger.error('(%s) No image available to save.' % (self.name,) )
            result = False
        else:
            try:
                img = self.get_frame()
                img.save(filename)
                result = filename
            except:
                _logger.error('(%s) Unable to save image "%s".' % (self.name, filename) )
                result = False
        return result
    
                 
class SimCamera(CameraBase):

    implements(ICamera)    
    
    def __init__(self, name="Camera Simulator"):
        CameraBase.__init__(self, name)
        self.size = (480, 640)
        self.resolution = 1.0
        self._packet_size = self.size[0] * self.size[1]
        self._fsource = open('/dev/urandom','rb')
        self._update()
        
    def _update(self):
        data = self._fsource.read(self._packet_size)
        self.frame = toimage(numpy.fromstring(data, 'B').reshape(
                                                    self.resolution[1], 
                                                    self.resolution[0]))

    def get_frame(self):
        self.update()
        return self.frame


class CACamera(CameraBase):

    implements(ICamera)   
     
    def __init__(self, pv_name, zoom_motor, name='Camera'):
        CameraBase.__init__(self, name)
        self.size = (640, 480)
        self.resolution = 1.0
        self._packet_size = self.size[0] * self.size[1]
        self._cam = PV(pv_name)
        self._zoom = IMotor(zoom_motor)

    def _update(self):
        try:
            data = self._cam.get()
            
            # Make sure full frame is obtained otherwise iterate until we
            # get a full frame. This is required because sometimes the frame
            # data is incomplete.
            while len(data) != self._packet_size:
                data = self._cam.get()
                
            self.frame = toimage(numpy.fromstring(data, 'B').reshape(
                                                    self.resolution[1], 
                                                    self.resolution[0]))
        except:
            _logger.error('(%s) Failed fetching frame.' % (self.name,) )
            # FIXME: What should we do when PV can not connect?

    def zoom(self, val):
        self._zoom.move_to(val)
            
    def get_frame(self):
        self._update()
        return self.frame


                                
class AxisCamera(CameraBase):

    implements(ICamera, IPTZCameraController)  
      
    def __init__(self, hostname, name='Axis Camera'):
        CameraBase.__init__(self, name)
        self.size = (704, 480)
        self._url = 'http://%s/jpg/image.jpg' % hostname
        self._server = httplib.HTTPConnection(hostname)
        self._last_frame = time.time()
        self._rzoom = 0
        self._update()

    def _get_image(self):
            f = urllib.urlopen(self.url)
            f_str = cStringIO.StringIO(f.read())
            return Image.open(f_str)

    def _update(self):
        if time.time() - self._last_frame < 0.1:
            return
        try:
            self.frame = self._get_image()
            self._last_frame = time.time()
        except:
            _logger.error('(%s) Failed fetching frame.' % (self.name,) )

    def get_frame(self):
        self.update()
       
    def zoom(self, value):
        self._server.connect()
        command = "/axis-cgi/com/ptz.cgi?rzoom=%s" % value
        result = self._server.request("GET", command)
        self._rzoom -= value
        self._server.close()

    def center(self, x, y):
        self._server.connect()
        command = "/axis-cgi/com/ptz.cgi?center=%d,%d" % (x, y)
        result = self._server.request("GET", command)
        self._server.close()
    
    def goto(self, position):
        self._server.connect()
        position = urllib.quote_plus(position)
        command = "/axis-cgi/com/ptz.cgi?gotoserverpresetname=%s" % position
        result = self._server.request("GET", command)
        self._rzoom = 0
        self._server.close()



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

