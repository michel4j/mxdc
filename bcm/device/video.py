
from bcm.device.base import BaseDevice
from bcm.device.interfaces import ICamera, IZoomableCamera, IPTZCameraController, IMotor
from bcm.protocol import ca
from bcm.utils.log import get_module_logger
from scipy.misc import toimage
from zope.interface import implements
import Image
import cStringIO
import httplib
import numpy
import os
import re
import socket
import threading
import time
import urllib
import zlib

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)
   

class VideoSrc(BaseDevice):
    """Base class for all Video Sources. Maintains a list of listenners (sinks)
    and updates each one when the video frame changes."""
    
    def __init__(self, name="Basic Camera", maxfps=5.0):
        """Kwargs:
            `name` (str): Camera name.
            `maxfps` (flaot): Maximum frame rate.
        """
        BaseDevice.__init__(self)
        self.frame = None
        self.name = name
        self.maxfps = max(1.0, maxfps)
        self.resolution = 1.0
        self.sinks = []
        self._stopped = True
        self._active = True
    
    def add_sink(self, sink):
        """Add a video sink.
        
        Args:
            `sink` (:class:`bcm.device.interfaces.IVideoSink` provider).
        """ 
        self.sinks.append( sink )
        sink.set_src(self)

    def del_sink(self, sink):
        """Remove a video sink.
        
        Args:
            `sink` (:class:`bcm.device.interfaces.IVideoSink` provider).
        """ 
        if sink in self.sinks:
            self.sinks.remove(sink)
            
    def start(self):
        """Start producing video frames. """ 
        
        if self._stopped == True:
            self._stopped = False
            worker = threading.Thread(target=self._stream_video)
            worker.setName('Video Thread: %s' % self.name)
            worker.setDaemon(True)
            worker.start()        
        
    def stop(self):
        """Start producing video frames. """ 
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
                return
               
    def get_frame(self):
        """Obtain the most recent video frame.
        
        Returns:
            A :class:`Image.Image` (Python Imaging Library) image object.
        """
        pass                  
    
                 
class SimCamera(VideoSrc):

    implements(ICamera)    
    
    def __init__(self, name="Camera Simulator", img="sim_sample_video.png"):
        VideoSrc.__init__(self, name)
        if img is not None:
            fname = '%s/data/%s' % (os.environ.get('BCM_CONFIG_PATH'), img)
            self._frame = Image.open(fname)
            self.size = self._frame.size
            self.resolution = 1.0
        else:            
            self.size = (640, 480)
            self.resolution = 5.34e-3 * numpy.exp(-0.18)
            self._packet_size = self.size[0] * self.size[1]
            self._fsource = open('/dev/urandom','rb')
            data = self._fsource.read(self._packet_size)
            self._frame = toimage(numpy.fromstring(data, 'B').reshape(
                                                        self.size[1], 
                                                        self.size[0]))
        self.set_state(active=True, health=(0,''))
        
    def get_frame(self):
        return self._frame


class SimZoomableCamera(SimCamera):
    implements(IZoomableCamera)
    def __init__(self, name, motor):
        SimCamera.__init__(self, name)
        self._zoom = IMotor(motor)
        self._zoom.connect('changed', self._on_zoom_change)
            
    def zoom(self, value):
        """Set the zoom position of the camera
        Args:
            `value` (float): the target zoom value.
        """
        self._zoom.move_to(value)

    def _on_zoom_change(self, obj, val):
        self.resolution = 5.34e-3 * numpy.exp( -0.18 * val)

class SimPTZCamera(SimCamera):
    implements(IPTZCameraController)

    def __init__(self):
        SimCamera.__init__(self, img="sim_hutch_video.png")
    
    def zoom(self, value):
        pass

    def center(self, x, y):
        pass
    
    def goto(self, position):
        pass

    def get_presets(self):
        presets = ["Hutch", "Detector", "Robot", "Goniometer", "Sample", "Panel"]
        return presets



class CACamera(VideoSrc):

    implements(IZoomableCamera)   
     
    def __init__(self, pv_name, zoom_motor, name='Camera'):
        VideoSrc.__init__(self, name, maxfps=20.0)
        self._active = False
        self.size = (640, 480)
        self.resolution = 1.0
        self._packet_size = self.size[0] * self.size[1]
        self._cam = self.add_pv(pv_name)
        self._zoom = IMotor(zoom_motor)
        self._cam.connect('active', self._activate)
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
      
    def __init__(self, hostname,  idx=None, name='Axis Camera'):
        VideoSrc.__init__(self, name, maxfps=20.0)
        self.size = (768, 576)
        if idx is None:
            self.url = 'http://%s/jpg/image.jpg' % hostname
        else:
            self.url = 'http://%s/jpg/%s/image.jpg' % (hostname,idx)
        self._last_frame = time.time()
        self.set_state(active=True)

    def get_frame(self):
        try:
            f = urllib.urlopen(self.url)
            f_str = cStringIO.StringIO(f.read())
            img = Image.open(f_str)
            self.size = img.size
        except:
            self.set_state(active=False, message='Unable to connect!')
            img = None
        return img

class ZoomableAxisCamera(AxisCamera):
    
    implements(IZoomableCamera)
    
    def __init__(self, hostname, zoom_motor, idx=None, name="Zoomable Axis Camera"):
        AxisCamera.__init__(self, hostname, idx=idx, name=name)
        self._zoom = IMotor(zoom_motor)
        self.resolution = 1.0
        self._zoom.connect('changed', self._on_zoom_change)
    
    def zoom(self, value):
        self._zoom.move_to(value)
    
    def _on_zoom_change(self, obj, val):
        self.resolution = 3.6875e-3 * numpy.exp( -0.2527 * val)


class ZoomableCamera(object):
    
    implements(IZoomableCamera)
    
    def __init__(self, camera, zoom_device, name="Zoomable Camera"):
        self._camera = camera
        self.resolution = 1.0
        self._zoom = IMotor(zoom_device)
        self._zoom.connect('changed', self._on_zoom_change)
    
    def zoom(self, value):
        """Set the zoom position of the camera
        Args:
            `value` (float): the target zoom value.
        """
        self._zoom.move_to(value)
    
    def _on_zoom_change(self, obj, val):
        self.resolution = 3.6875e-3 * numpy.exp( -0.2527 * val)
    
    def __getattr__(self, key):
        try:
            return getattr(self._camera, key)
        except AttributeError:
            raise

                                        
class AxisPTZCamera(AxisCamera):

    implements(IPTZCameraController)  
      
    def __init__(self, hostname, idx=None, name='Axis PTZ Camera'):
        AxisCamera.__init__(self, hostname, idx, name)
        self._server = httplib.HTTPConnection(hostname)
        self._rzoom = 0
       
    def zoom(self, value):
        """Set the zoom position of the PTZ camera
        
        Args:
            `value` (int): the target zoom value.
        """
        self._server.connect()
        command = "/axis-cgi/com/ptz.cgi?rzoom=%s" % value
        self._server.request("GET", command)
        self._rzoom -= value
        self._server.close()

    def center(self, x, y):
        """Set the pan-tilt focal point of the PTZ camera
        
        Args:
            `x` (int): the target horizontal focal point on the image.
            `y` (int): the target horizontal focal point on the image.
        """
        self._server.connect()
        command = "/axis-cgi/com/ptz.cgi?center=%d,%d" % (x, y)
        self._server.request("GET", command)
        self._server.close()
    
    def goto(self, position):
        """Set the pan-tilt focal point based on a predefined position
        
        Args:
            `position` (str): Name of predefined position.
        """
        self._server.connect()
        position = urllib.quote_plus(position)
        command = "/axis-cgi/com/ptz.cgi?gotoserverpresetname=%s" % position
        self._server.request("GET", command)
        self._rzoom = 0
        self._server.close()

    def get_presets(self):
        """Get a list of all predefined position names from the PTZ camera
        
        Returns:
            A list of strings.
        """
        
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
     
class FDICamera(VideoSrc):

    implements(ICamera)
      
    def __init__(self, hostname, name='FDI Camera'): 
        VideoSrc.__init__(self, name)
        self._hostname = hostname
        self._name = name
        self.size = (1388, 1040)
        self.resolution = 0.0064
        self._open_socket()

    def _open_socket(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)        
        self._sock.connect((self._hostname,50000))

    def get_frame(self):
        self._sock.send('GetImage\n')
        camdata = self._sock.recv(1024).split(';',2)
        while not camdata[0]:
            self._sock.close()
            self._open_socket()
            self._sock.send('GetImage\n')
            camdata = self._sock.recv(1024).split(';',2)

        if len(camdata[2]) != 6:
            data = camdata[2][6:]
            camdata = int(camdata[2][:6])
        else:
            data = ''
            camdata = int(camdata[2])
        timeout = 100000
        while (len(data) < camdata) and timeout:
            data = data + self._sock.recv(camdata)
            timeout = timeout - 1
        frame = toimage(numpy.fromstring(zlib.decompress(data), 'H').reshape(self.size[1],
                                                                             self.size[0]))
        return frame

    def stop(self):
        self._sock.close()
        self._stopped = True
