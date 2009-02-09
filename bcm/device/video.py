import time
import logging
import urllib
import cStringIO
import httplib
import Image
import numpy
# suppres scipy import warnings
import warnings
warnings.simplefilter("ignore")

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
        self.is_active = False
    
    def zoom(self, val):
        pass
                       
    
                 
class SimCamera(CameraBase):

    implements(ICamera)    
    
    def __init__(self, name="Camera Simulator"):
        CameraBase.__init__(self, name)
        self.size = (480, 640)
        self.resolution = 1.0
        self._packet_size = self.size[0] * self.size[1]
        self._fsource = open('/dev/urandom','rb')
        self.is_active = True
        
    def _update(self):
        data = self._fsource.read(self._packet_size)
        self.frame = toimage(numpy.fromstring(data, 'B').reshape(
                                                    self.size[1], 
                                                    self.size[0]))

    def get_frame(self):
        self._update()
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
        self._cam.connect('active', self._activate)
        self._zoom.connect('changed', self._on_zoom_change)
        self._sim_cam = SimCamera()
    
    def _activate(self, obj, val=None):
        self.is_active = True
    
    def _on_zoom_change(self, obj, val):
           self.resolution = 5.34e-3 * numpy.exp( -0.18 * val)
           
    def _update(self):
        if self.is_active:
            data = self._cam.get()
            
            # Make sure full frame is obtained otherwise iterate until we
            # get a full frame. This is required because sometimes the frame
            # data is incomplete.
            while len(data) != self._packet_size:
                data = self._cam.get()
                
            self.frame = toimage(numpy.fromstring(data, 'B').reshape(
                                                    self.size[1], 
                                                    self.size[0]))
        else:
            self.frame = self._sim_cam.get_frame()

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

