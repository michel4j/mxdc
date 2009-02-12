import time
import threading
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
from bcm.protocol import ca
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class VideoError(Exception):

    """Base class for errors in the video module."""
    

class VideoSrc(object):

    def __init__(self, name="Basic Camera", maxfps=10.0):
        self.frame = None
        self.name = name
        self.maxfps = max(1.0, maxfps)
        self.resolution = 1.0
        self.sinks = []
        self._stopped = True
        self._active = True
    
    def add_sink(self, sink):
        self.sinks.append( sink )
        sink.set_src(self)

    def del_sink(self, sink):
        self.sinks.remove(sink)
        
    def start(self):
        if self._stopped:
            self._stopped = False
            worker = threading.Thread(target=self._stream_video)
            worker.setDaemon(True)
            worker.start()
    
    def stop(self):
        self._stopped = True
            
    def _stream_video(self):
        ca.threads_init()
        while not self._stopped:
            if self._active:
                img = self.get_frame()
                for sink in self.sinks:
                    sink.display(img.copy())
            time.sleep(1.0/self.maxfps)
        
    def zoom(self, val):
        pass
    
    def get_frame(self): 
        pass                  
    
                 
class SimCamera(VideoSrc):

    implements(ICamera)    
    
    def __init__(self, name="Camera Simulator"):
        VideoSrc.__init__(self, name)
        self.size = (640, 480)
        self.resolution = 1.0
        self._packet_size = self.size[0] * self.size[1]
        self._fsource = open('/dev/urandom','rb')
        
    def get_frame(self):
        data = self._fsource.read(self._packet_size)
        frame = toimage(numpy.fromstring(data, 'B').reshape(
                                                    self.size[1], 
                                                    self.size[0]))
        return frame



class CACamera(VideoSrc):

    implements(ICamera)   
     
    def __init__(self, pv_name, zoom_motor, name='Camera'):
        VideoSrc.__init__(self, name)
        self._active = False
        self.size = (640, 480)
        self.resolution = 1.0
        self._packet_size = self.size[0] * self.size[1]
        self._cam = PV(pv_name)
        self._zoom = IMotor(zoom_motor)
        self._cam.connect('active', self._activate)
        self._zoom.connect('changed', self._on_zoom_change)
    
    def _activate(self, obj, val=None):
        self._active = True
    
    def _on_zoom_change(self, obj, val):
           self.resolution = 5.34e-3 * numpy.exp( -0.18 * val)
           
    def get_frame(self):
        data = self._cam.get()
        
        # Make sure full frame is obtained otherwise iterate until we
        # get a full frame. This is required because sometimes the frame
        # data is incomplete.
        while len(data) != self._packet_size:
            data = self._cam.get()
            
        frame = toimage(numpy.fromstring(data, 'B').reshape(
                                                self.size[1], 
                                                self.size[0]))
        return frame

    def zoom(self, val):
        self._zoom.move_to(val)
            


                                
class AxisCamera(VideoSrc):

    implements(ICamera, IPTZCameraController)  
      
    def __init__(self, hostname, name='Axis Camera'):
        VideoSrc.__init__(self, name, maxfps=5.0)
        self.size = (704, 480)
        self._url = 'http://%s/jpg/image.jpg' % hostname
        self._server = httplib.HTTPConnection(hostname)
        self._last_frame = time.time()
        self._rzoom = 0

    def get_frame(self):
        f = urllib.urlopen(self.url)
        f_str = cStringIO.StringIO(f.read())
        return Image.open(f_str)
       
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

