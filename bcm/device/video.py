import time
import gc
import threading
import logging
import urllib
import cStringIO
import httplib
import Image
import numpy
import gtk
import gobject
import re

# suppres scipy import warnings
import warnings
warnings.simplefilter("ignore")

from scipy.misc import toimage, fromimage
from zope.interface import implements
from bcm.device.interfaces import ICamera, IZoomableCamera, IPTZCameraController, IMotor
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
        if sink in self.sinks:
            self.sinks.remove(sink)
            
    def start(self):
        if self._stopped == True:
            self._stopped = False
            worker = threading.Thread(target=self._stream_video)
            worker.setName('Video Thread: %s' % self.name)
            worker.setDaemon(True)
            worker.start()        
        
    def stop(self):
        self._stopped = True
    
    def _stream_video(self):
        ca.threads_init()
        dur = 1.0/self.maxfps
        while not self._stopped:
            if self._active:
                try:
                    img = self.get_frame()
                    for sink in self.sinks:
                        if not sink.stopped:
                            sink.display(img)
                except:
                    #_logger.error('(%s) Error fetching frame' % self.name)
                    pass
            # for some reason this does not cleanup properly without try-except
            try:
                time.sleep(dur)
            except:
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

    implements(IZoomableCamera)   
     
    def __init__(self, pv_name, zoom_motor, name='Camera'):
        VideoSrc.__init__(self, name, maxfps=20.0)
        self._active = False
        self.size = (640, 480)
        self.resolution = 1.0
        self._packet_size = self.size[0] * self.size[1]
        self._cam = PV(pv_name)
        self._zoom = IMotor(zoom_motor)
        self._cam.connect('active', self._activate, True)
        self._cam.connect('inactive', self._activate, False)
        self._zoom.connect('changed', self._on_zoom_change)
    
    def _activate(self, obj, val):
        self._active = val
        if not val:
            self._stopped = True
    
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

    implements(ICamera)  
      
    def __init__(self, hostname,  id=None, name='Axis Camera'):
        VideoSrc.__init__(self, name, maxfps=20.0)
        self.size = (640, 480)
        if id is None:
            self._url = 'http://%s/jpg/image.jpg' % hostname
        else:
            self._url = 'http://%s/jpg/%s/image.jpg' % (hostname,id)
        self._server = httplib.HTTPConnection(hostname)
        self._last_frame = time.time()

    def get_frame(self):
        f = urllib.urlopen(self._url)
        f_str = cStringIO.StringIO(f.read())
        img = Image.open(f_str)
        self.size = img.size
        return img

class ZoomableAxisCamera(AxisCamera):
    
    implements(IZoomableCamera)
    
    def __init__(self, hostname, zoom_motor, id=None, name="Zoomable Axis Camera"):
        AxisCamera.__init__(self, hostname, id=id, name=name)
        self._zoom = IMotor(zoom_motor)
        self.resolution = 1.0
        self._zoom.connect('changed', self._on_zoom_change)
    
    def zoom(self, value):
        self._zoom.move_to(value)
    
    def _on_zoom_change(self, obj, val):
        self.resolution = 3.6875132 * numpy.exp( -0.2527 * val)


                                
class AxisPTZCamera(AxisCamera):

    implements(IPTZCameraController)  
      
    def __init__(self, hostname, id=None, name='Axis PTZ Camera'):
        AxisCamera.__init__(self, hostname, id, name)
        self._rzoom = 0
       
    def zoom(self, value):
        self._server.connect()
        command = "/axis-cgi/com/ptz.cgi?rzoom=%s" % value
        self._server.request("GET", command)
        self._rzoom -= value
        self._server.close()

    def center(self, x, y):
        self._server.connect()
        command = "/axis-cgi/com/ptz.cgi?center=%d,%d" % (x, y)
        self._server.request("GET", command)
        self._server.close()
    
    def goto(self, position):
        self._server.connect()
        position = urllib.quote_plus(position)
        command = "/axis-cgi/com/ptz.cgi?gotoserverpresetname=%s" % position
        self._server.request("GET", command)
        self._rzoom = 0
        self._server.close()

    def get_presets(self):
        try:
            self._server.connect()
            command = "/axis-cgi/com/ptz.cgi?query=presetposall"
            self._server.request("GET", command)
            result = self._server.getresponse().read()
            self._server.close()
        except:
            result = ''
            _logger.error('Could not connect to video server')
        presets = []
        pospatt = re.compile('presetposno.+=(?P<name>[\w ]+)')
        for line in result.split('\n'):
            m = pospatt.match(line)
            if m:
                presets.append(m.group('name'))
        return presets
     