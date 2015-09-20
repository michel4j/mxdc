
from bcm.device.base import BaseDevice
from bcm.device.interfaces import ICamera, IZoomableCamera, IPTZCameraController, IMotor, IVideoSink
from bcm.protocol import ca
from bcm.utils.log import get_module_logger
from scipy import misc
from zope.interface import implements
from PIL import Image
import urllib
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
            self._frame = misc.toimage(numpy.fromstring(data, 'B').reshape(
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
            
        frame = misc.toimage(numpy.fromstring(data, 'B').reshape(
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
        self._read_size = 1024
        if idx is None:
            self.url = 'http://%s/mjpg/video.mjpg' % hostname
        else:
            self.url = 'http://%s/mjpg/%s/video.mjpg' % (hostname,idx)
        self._last_frame = time.time()
        self.stream = urllib.urlopen(self.url)
        self.set_state(active=True)

    def _stream_video(self):
        ca.threads_init()
        data = ''
        
        count = 0
        self._frame = None
        while not self._stopped:
            if self._active:
                try:
                    data += self.stream.read(self._read_size)
                    a = data.find('\xff\xd8')
                    b = data.find('\xff\xd9')
                    count += 1
                    if a!=-1 and b!=-1:
                        jpg = data[a:b+2]
                        data = data[b+2:]
                        f_str = cStringIO.StringIO(jpg)
                        img = Image.open(f_str)
                        if self._frame:
                            self._frame = Image.blend(self._frame, img, 0.5)
                        else:
                            self._frame = img
                        self.size = self._frame.size
                        for sink in self.sinks:
                            if not sink.stopped:
                                sink.display(self._frame)
                        if count > 4:
                            self._read_size *= 2
                        count = 0
                except:
                    pass

    def get_frame(self):
        return self._frame

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
        frame = misc.toimage(numpy.fromstring(zlib.decompress(data), 'H').reshape(self.size[1],
                                                                             self.size[0]))
        return frame

    def stop(self):
        self._sock.close()
        self._stopped = True


class VideoRecorder(object):
    implements(IVideoSink)    
    def __init__(self, camera):
        self.stopped = False
        self._colorize = False
        self._palette = None
        self._start_time = 0
        self._last_time = 0
        self._delta_t = 1.0
        self._scale = 0.5
        self._recording = False
        self._duration = 300
        self._filename = 'testing'
        self.camera = camera
            
    def set_src(self, src):
        self.camera = src
        self.camera.start()
    
    def display(self, img):
        if self._recording and time.time() - self._start_time <= self._duration:
            if time.time() - self._last_time >= self._delta_t:
                w, h = map(lambda x: int(x*self._scale), img.size)                
                img = img.resize((w, h), Image.ANTIALIAS)
                if self._colorize:
                    if img.mode != 'L':
                        img = img.convert('L')
                    img.putpalette(self._palette)
                self._video_images.append(img)
                self._video_times.append(time.time())
                self._last_time = self._video_times[-1]
        elif self._recording:
            self.stop()
           
    def set_colormap(self, colormap=None):
        from mxdc.widgets import video as vw
        if colormap is not None:
            self._colorize = True
            self._palette = vw.COLORMAPS[colormap]
        else:
            self._colorize = False
    
    def record(self, filename, duration=5, fps=0.5, scale=0.5):
        if not self._recording:
            self.camera.add_sink(self)
            self._filename = filename
            self._recording = True
            self._video_images = []
            self._video_times = []
            self._duration = duration*60
            self._delta_t = 1.0/fps
            self._start_time = time.time()
            self._last_time = self._start_time
            self._scale = scale
        
    def stop(self):
        from bcm.utils import images2gif
        if self._recording:
            self._recording = False
            self.camera.del_sink(self)
            dur = numpy.diff(self._video_times).mean()
            images2gif.writeGif(self._filename, self._video_images, duration=dur)
            del self._video_images
            del self._video_times
              