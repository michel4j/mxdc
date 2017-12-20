import os
import re
import socket
import threading
import time
import zlib
from StringIO import StringIO
from io import BytesIO

import numpy
import redis
import requests
from PIL import Image
from interfaces import ICamera, IZoomableCamera, IPTZCameraController, IMotor, IVideoSink
from mxdc.devices.base import BaseDevice
from mxdc.utils.log import get_module_logger
from scipy import misc
from zope.interface import implements

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)

session = requests.Session()


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
        self.resolution = 1.0e-3
        self.sinks = []
        self._stopped = True
        self._active = True

    def add_sink(self, sink):
        """Add a video sink.

        Args:
            `sink` (:class:`mxdc.interface.IVideoSink` provider).
        """
        self.sinks.append(sink)
        sink.set_src(self)

    def del_sink(self, sink):
        """Remove a video sink.

        Args:
            `sink` (:class:`mxdc.interface.IVideoSink` provider).
        """
        if sink in self.sinks:
            self.sinks.remove(sink)

    def start(self):
        """Start producing video frames. """

        if self._stopped:
            self._stopped = False
            worker = threading.Thread(target=self._stream_video)
            worker.setName('Video Thread: %s' % self.name)
            worker.setDaemon(True)
            worker.start()

    def stop(self):
        """Start producing video frames. """
        self._stopped = True

    def _stream_video(self):
        dur = 1.0 / self.maxfps
        while not self._stopped:
            t = time.time()
            if self._active and any(not (sink.stopped) for sink in self.sinks):
                try:
                    img = self.get_frame()
                    if not img: continue
                    for sink in self.sinks:
                        if not sink.stopped:
                            sink.display(img)
                except Exception as e:
                    logger.warning('(%s) Error fetching frame:\n %s' % (self.name, e))
                    raise
            time.sleep(max(0, dur - (time.time() - t)))

    def get_frame(self):
        """Obtain the most recent video frame.

        Returns:
            A :class:`Image.Image` (Python Imaging Library) image object.
        """
        pass

    def cleanup(self):
        self.stop()


class SimCamera(VideoSrc):
    implements(ICamera)

    def __init__(self, name="Camera Simulator", img="sim_sample_video.png"):
        VideoSrc.__init__(self, name)
        if img is not None:
            fname = '%s/data/%s' % (os.environ.get('BCM_CONFIG_PATH'), img)
            self._frame = Image.open(fname)
            self.size = self._frame.size
            self.resolution = 1.0e-3
        else:
            self.size = (640, 480)
            self.resolution = 5.34e-3 * numpy.exp(-0.18)
            self._packet_size = self.size[0] * self.size[1]
            self._fsource = open('/dev/urandom', 'rb')
            data = self._fsource.read(self._packet_size)
            self._frame = misc.toimage(numpy.fromstring(data, 'B').reshape(
                self.size[1],
                self.size[0]))
        self.set_state(active=True, health=(0, ''))

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
        self._zoom.move_to(value, wait=True)

    def _on_zoom_change(self, obj, val):
        self.resolution = 5.34e-6 * numpy.exp(-0.18 * val)


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


class MJPGCamera(VideoSrc):
    implements(ICamera)

    def __init__(self, url, size=(768, 576), name='MJPG Camera'):
        VideoSrc.__init__(self, name, maxfps=10.0)
        self.size = size
        self._read_size = 1024
        self.url = url
        self._last_frame = time.time()
        self.stream = None
        self._frame = None
        self.set_state(active=True)
        self.lock = threading.Lock()

    def get_frame(self):
        return self.get_frame_raw()

    def get_frame_raw(self):
        if not self.stream:
            self.stream = requests.get(self.url, stream=True).raw
        try:
            with self.lock:
                both_found = False
                while not both_found:
                    self.data += self.stream.read(self._read_size)
                    b = self.data.rfind('\xff\xd9')
                    a = self.data[:b].rfind('\xff\xd8')
                    if a != -1 and b != -1:
                        jpg = self.data[a:b + 2]
                        self.data = self.data[b + 2:]
                        self._frame = Image.open(StringIO(jpg))
                        self.size = self._frame.size
                        both_found = True
                    time.sleep(0)
        except Exception as e:
            logger.error(e)
            self.stream = requests.get(self.url, stream=True).raw
        return self._frame


class JPGCamera(VideoSrc):
    implements(ICamera)

    def __init__(self, url, size=(768, 576), name='JPG Camera'):
        VideoSrc.__init__(self, name, maxfps=10.0)
        self.size = size
        self.url = url
        self.session = requests.Session()
        self._frame = None
        self.set_state(active=True)

    def get_frame(self):
        return self.get_frame_raw()

    def get_frame_raw(self):
        # r = self.session.get(self.url, stream=True)
        r = self.session.get(self.url)
        if r.status_code == 200:
            # r.raw.decode_content = True
            # self._frame = Image.open(r.raw)
            self._frame = Image.open(BytesIO(r.content))
            self.size = self._frame.size
        return self._frame


class REDISCamera(VideoSrc):
    implements(ICamera)

    def __init__(self, server, key, size=(768, 576), name='REDIS Camera'):
        VideoSrc.__init__(self, name, maxfps=15.0)
        self.size = size
        self._read_size = 48 * 1024
        self.store = redis.Redis(host=server, port=6379, db=0)
        self.key = key
        self.server = server
        self._last_frame = time.time()
        self.stream = None
        self.data = ''
        self._frame = None
        self.set_state(active=True)
        self.lock = threading.Lock()

    def get_frame(self):
        return self.get_frame_raw()

    def get_frame_raw(self):
        with self.lock:
            data = self.store.get(self.key)
            self._frame = Image.open(StringIO(data))
            self.size = self._frame.size
        return self._frame


class AxisCamera(JPGCamera):
    implements(ICamera)

    def __init__(self, hostname, idx=None, name='Axis Camera'):
        if idx is None:
            # url = 'http://%s/mjpg/video.mjpg' % hostname
            url = 'http://%s/jpg/image.jpg' % hostname
        else:
            # url = 'http://%s/mjpg/%s/video.mjpg' % (hostname, idx)
            url = 'http://%s/jpg/%s/image.jpg' % (hostname, idx)
        super(AxisCamera, self).__init__(url, name=name)


class ZoomableCamera(object):
    implements(IZoomableCamera)

    def __init__(self, camera, zoom_device):
        self._camera = camera
        self._zoom = IMotor(zoom_device)
        self._zoom.connect('changed', self.update_resolution)
        self._zoom.connect('active', self.update_resolution)

    def zoom(self, value):
        """Set the zoom position of the camera
        Args:
            `value` (float): the target zoom value.
        """
        self._zoom.move_to(value)

    def update_resolution(self, *args, **kwar):
        scale = 768.0 / self._camera.size[0]
        self._camera.resolution = scale * 3.6875e-3 * numpy.exp(-0.2527 * self._zoom.get_position())

    def __getattr__(self, key):
        try:
            return getattr(self._camera, key)
        except AttributeError:
            raise


class AxisPTZCamera(AxisCamera):
    implements(IPTZCameraController)

    def __init__(self, hostname, idx=None, name='Axis PTZ Camera'):
        AxisCamera.__init__(self, hostname, idx, name)
        self.url_root = 'http://{}/axis-cgi/com/ptz.cgi'.format(hostname)
        self._rzoom = 0
        self.presets = []
        self.fetch_presets()

    def zoom(self, value):
        """Set the zoom position of the PTZ camera

        Args:
            `value` (int): the target zoom value.
        """
        requests.get(self.url_root, params={'rzoom': value})
        self._rzoom -= value

    def center(self, x, y):
        """Set the pan-tilt focal point of the PTZ camera

        Args:
            `x` (int): the target horizontal focal point on the image.
            `y` (int): the target horizontal focal point on the image.
        """
        requests.get(self.url_root, params={'center': '{},{}'.format(x, y)})

    def goto(self, position):
        """Set the pan-tilt focal point based on a predefined position

        Args:
            `position` (str): Name of predefined position.
        """
        requests.get(self.url_root, params={'gotoserverpresetname': position})
        self._rzoom = 0

    def get_presets(self):
        return self.presets

    def fetch_presets(self):
        """Get a list of all predefined position names from the PTZ camera

        Returns:
            A list of strings.
        """
        presets = []
        r = requests.get(self.url_root, params={'query': 'presetposall'})
        if r.status_code == requests.codes.ok:
            pospatt = re.compile('presetposno.+=(?P<name>[\w ]+)')
            for line in r.text.split('\n'):
                m = pospatt.match(line)
                if m:
                    presets.append(m.group('name'))
        self.presets = presets


class FDICamera(VideoSrc):
    implements(ICamera)

    def __init__(self, hostname, name='FDI Camera'):
        VideoSrc.__init__(self, name)
        self._hostname = hostname
        self._name = name
        self.size = (1388, 1040)
        self.resolution = 0.0064e-3
        self._open_socket()

    def _open_socket(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((self._hostname, 50000))

    def get_frame(self):
        self._sock.send('GetImage\n')
        camdata = self._sock.recv(1024).split(';', 2)
        while not camdata[0]:
            self._sock.close()
            self._open_socket()
            self._sock.send('GetImage\n')
            camdata = self._sock.recv(1024).split(';', 2)

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
                w, h = map(lambda x: int(x * self._scale), img.size)
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
            self._duration = duration * 60
            self._delta_t = 1.0 / fps
            self._start_time = time.time()
            self._last_time = self._start_time
            self._scale = scale

    def stop(self):
        from mxdc.utils import images2gif
        if self._recording:
            self._recording = False
            self.camera.del_sink(self)
            dur = numpy.diff(self._video_times).mean()
            images2gif.writeGif(self._filename, self._video_images, duration=dur)
            del self._video_images
            del self._video_times
