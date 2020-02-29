import os
import pickle
import re
import threading
import time
from io import BytesIO, StringIO

import gi

gi.require_version('Gtk', '3.0')

from gi.repository import GObject

import numpy
import redis
import requests
from PIL import Image
from .interfaces import ICamera, IZoomableCamera, IPTZCameraController, IMotor
from mxdc.devices.base import BaseDevice
from mxdc.utils.log import get_module_logger
from scipy import misc
from zope.interface import implementer

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)

session = requests.Session()


class VideoSrc(BaseDevice):
    __gsignals__ = {
        "resize": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, name="Basic Camera", maxfps=5.0):
        """
        Base class for all Video Sources. Maintains a list of listenners (sinks)
        and updates each one when the video frame changes.
        @param name: Camera Name (str)
        @param maxfps: Max frames per second (float)
        """
        BaseDevice.__init__(self)
        self.frame = None
        self.name = name
        self.size = (768, 576)
        self.maxfps = max(1.0, maxfps)
        self.resolution = 1.0e-3
        self.gain_factor = 1.0
        self.gain_value = 1.0
        self.zoom_save = False
        self.sinks = []
        self._stopped = True
        self.set_state(active=True)

    def notify_size(self, frame):
        if frame and frame.size != self.size:
            self.size = self.frame.size
            self.set_state(resize=self.size)

    def configure(self, **kwargs):
        """
        Configure the camera
        """
        pass

    def add_sink(self, sink):
        """
        Add a sink to the Camera
        @param sink: :class:`mxdc.interface.IVideoSink` provider
        """
        self.sinks.append(sink)
        sink.set_src(self)

    def del_sink(self, sink):
        """
        Remove a video sink.

        @param sink: :class:`mxdc.interface.IVideoSink` provider
        """
        if sink in self.sinks:
            self.sinks.remove(sink)

    def start(self):
        """
        Start producing video frames.
        """
        if self._stopped:
            self._stopped = False
            worker = threading.Thread(target=self.streamer)
            worker.setName('Video Thread: %s' % self.name)
            worker.setDaemon(True)
            worker.start()

    def stop(self):
        """
        Stop producing video frames.
        """
        self._stopped = True

    def streamer(self):
        dur = 1.0 / self.maxfps
        while not self._stopped:
            t = time.time()
            if self.is_active() and self.is_enabled() and any(not (sink.stopped) for sink in self.sinks):
                try:
                    img = self.get_frame()
                    self.notify_size(img)
                    if not img: continue
                    for sink in self.sinks:
                        if not sink.stopped:
                            sink.display(img)
                except Exception as e:
                    logger.warning('(%s) Error fetching frame:\n %s' % (self.name, e))
                    raise
            time.sleep(max(0, dur - (time.time() - t)))

    def get_frame(self):
        """
        Obtain the most recent video frame.
        @return: A :class:`Image.Image` (Python Imaging Library) image object.
        """
        pass

    def cleanup(self):
        self.stop()


@implementer(ICamera)
class SimCamera(VideoSrc):

    def __init__(self, name="Camera Simulator", img="sim_sample_video.png"):
        VideoSrc.__init__(self, name)
        if img is not None:
            fname = '%s/data/%s' % (os.environ.get('BCM_CONFIG_PATH'), img)
            self.frame = Image.open(fname)
            self.size = self.frame.size
            self.resolution = 1.0e-3
        else:
            self.size = (640, 480)
            self.resolution = 5.34e-3 * numpy.exp(-0.18)
            self._packet_size = self.size[0] * self.size[1]
            self._fsource = open('/dev/urandom', 'rb')
            data = self._fsource.read(self._packet_size)
            self.frame = misc.toimage(numpy.fromstring(data, 'B').reshape(
                self.size[1],
                self.size[0]))
        self.set_state(active=True, health=(0, ''))

    def get_frame(self):
        return self.frame


@implementer(IZoomableCamera)
class SimZoomableCamera(SimCamera):

    def __init__(self, name, motor):
        SimCamera.__init__(self, name)
        self._zoom = IMotor(motor)
        self._zoom.connect('changed', self._on_zoom_change)

    def zoom(self, value):
        """
        Zoom to the given value.

        @param value: zoom value
        """
        self._zoom.move_to(value, wait=True)

    def _on_zoom_change(self, obj, val):
        self.resolution = 5.34e-6 * numpy.exp(-0.18 * val)


@implementer(IPTZCameraController)
class SimPTZCamera(SimCamera):

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


@implementer(ICamera)
class MJPGCamera(VideoSrc):

    def __init__(self, url, size=(768, 576), name='MJPG Camera'):
        VideoSrc.__init__(self, name, maxfps=10.0)
        self.size = size
        self._read_size = 1024
        self.url = url
        self._last_frame = time.time()
        self.stream = None
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
                        self.frame = Image.open(StringIO(jpg))
                        both_found = True
                    time.sleep(0)
        except Exception as e:
            logger.error(e)
            self.stream = requests.get(self.url, stream=True).raw
        return self.frame


@implementer(ICamera)
class JPGCamera(VideoSrc):

    def __init__(self, url, size=(768, 576), name='JPG Camera'):
        VideoSrc.__init__(self, name, maxfps=10.0)
        self.size = size
        self.url = url
        self.session = requests.Session()
        self.set_state(active=True)

    def get_frame(self):
        return self.get_frame_raw()

    def get_frame_raw(self):
        r = self.session.get(self.url)
        if r.status_code == 200:
            self.frame = Image.open(BytesIO(r.content))
        return self.frame


@implementer(ICamera)
class REDISCamera(VideoSrc):
    # Camera Attributes
    ATTRS = {
        'gain': 'GainRaw',
        'exposure': 'ExposureTimeAbs'
    }

    def __init__(self, server, mac, zoom_slave=True, size=(1280,1024), name='REDIS Camera'):
        VideoSrc.__init__(self, name, maxfps=15.0)
        self.store = redis.Redis(host=server, port=6379, db=0)
        self.key = mac
        self.zoom_slave = zoom_slave
        self.server = server
        self.size = size
        self.stream = None
        self.data = ''

        self._last_frame = time.time()
        self._read_size = 48 * 1024

        self.set_state(active=True)
        self.lock = threading.Lock()

    def configure(self, **kwargs):
        if 'gain_factor' in kwargs:
            self.gain_factor = kwargs.pop('gain_factor')
            kwargs['gain'] = self.gain_value

        for k, v in list(kwargs.items()):
            attr = self.ATTRS.get(k)
            if not attr: continue
            if k == 'gain':
                if int(v) == self.gain_value: continue
                self.gain_value = int(v)
                value = max(1, min(22, self.gain_factor * self.gain_value))
            else:
                value = v
            self.store.publish('{}:CFG:{}'.format(self.key, attr), pickle.dumps(value))

    def get_frame(self):
        return self.get_frame_jpg()

    def get_frame_raw(self):
        with self.lock:
            data = self.store.get('{}:RAW'.format(self.key))
            while len(data) < self.size[0] * self.size[1] * 3:
                data = self.store.get('{}:RAW'.format(self.key))
                time.sleep(0.002)
            img = Image.frombytes('RGB', self.size, data, 'raw')
            self.frame = img.transpose(Image.FLIP_LEFT_RIGHT)
        return self.frame

    def get_frame_jpg(self):
        with self.lock:
            data = self.store.get('{}:JPG'.format(self.key))
            self.frame = Image.open(BytesIO(data))
        return self.frame


@implementer(ICamera)
class AxisCamera(JPGCamera):

    def __init__(self, hostname, idx=None, name='Axis Camera'):
        if idx is None:
            # url = 'http://%s/mjpg/video.mjpg' % hostname
            url = 'http://%s/jpg/image.jpg' % hostname
        else:
            # url = 'http://%s/mjpg/%s/video.mjpg' % (hostname, idx)
            url = 'http://%s/jpg/%s/image.jpg' % (hostname, idx)
        super(AxisCamera, self).__init__(url, name=name)


@implementer(IZoomableCamera)
class ZoomableCamera(object):

    def __init__(self, camera, zoom_motor, scale_device=None):
        self.camera = camera
        self._zoom = zoom_motor
        if scale_device:
            self._scale = scale_device
            self._scale.connect('changed', self.update_resolution)
            self._scale.connect('active', self.update_resolution)
        else:
            self._zoom.connect('changed', self.update_zoom)
            self._zoom.connect('active', self.update_zoom)

    def zoom(self, value, wait=False):
        """
        Zoom to the given value.

        @param value: zoom value
        @param wait: (boolean) default False, whether to wait until camera has zoomed in.
        """
        self._zoom.move_to(value, wait=wait)

    def update_resolution(self, *args, **kwar):
        self.camera.resolution = self._scale.get() or 0.0028

    def update_zoom(self, *args, **kwar):
        scale = 1360. / self.camera.size[0]
        self.camera.resolution = scale * 0.00227167 * numpy.exp(-0.26441385 * self._zoom.get_position())
        if self.camera.zoom_slave:
            self.camera.configure(gain=(self._zoom.get_position()**2)/4)

    def __getattr__(self, key):
        try:
            return getattr(self.camera, key)
        except AttributeError:
            raise


@implementer(IPTZCameraController)
class AxisPTZCamera(AxisCamera):

    def __init__(self, hostname, idx=None, name='Axis PTZ Camera'):
        AxisCamera.__init__(self, hostname, idx, name)
        self.url_root = 'http://{}/axis-cgi/com/ptz.cgi'.format(hostname)
        self._rzoom = 0
        self.presets = []
        self.fetch_presets()

    def zoom(self, value, wait=False):
        requests.get(self.url_root, params={'rzoom': value})
        self._rzoom -= value

    def center(self, x, y):
        """
        Center the Pan-Tilt-Zoom Camera at the given point.
        @param x: (int), x point
        @param y: (int), y point
        """
        requests.get(self.url_root, params={'center': '{},{}'.format(x, y)})

    def goto(self, position):
        """
        Go to the given named position
        @param position: named position
        """
        requests.get(self.url_root, params={'gotoserverpresetname': position})
        self._rzoom = 0

    def get_presets(self):
        return self.presets

    def fetch_presets(self):
        """
        Obtain a list of named positions from the PTZ Camera
        @return: list of strings
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
