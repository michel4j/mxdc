
import os
import re
import threading
import time
from io import BytesIO, StringIO
from os import PathLike
from pathlib import Path

import numpy
import redis
import requests
from PIL import Image
from zope.interface import implementer

from mxdc import Signal, Device
from mxdc import APP_DIR
from mxdc.utils.log import get_module_logger
from mxdc.utils import decorators
from .interfaces import ICamera, IZoomableCamera, IPTZCameraController

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)

session = requests.Session()


@implementer(ICamera)
class VideoSrc(Device):
    """
    Base class for all Video Sources. Maintains a list of listenners (sinks)
    and updates each one when the video frame changes.

    :param name: Camera Name (str)
    :param maxfps: Max frames per second (float)
    """
    class Signals:
        resized = Signal("resized", arg_types=(int,int))

    def __init__(self, name="Basic Camera", size=(768, 576), maxfps=5.0):
        super().__init__()
        self.frame = None
        self.name = name
        self.size = size
        self.maxfps = max(1.0, maxfps)
        self.resolution = 1.0e-3
        self.gain_factor = 1.0
        self.gain_value = 1.0
        self.zoom_save = False
        self.sinks = []
        self._stopped = True
        self.set_state(active=True)

    def configure(self, **kwargs):
        """
        Configure the camera. Keyword arguments are device dependent.
        """
        pass

    def add_sink(self, sink):
        """
        Add a sink to the Camera

        :param sink: :class:`mxdc.interface.IVideoSink` provider
        """
        self.sinks.append(sink)
        sink.set_src(self)

    def del_sink(self, sink):
        """
        Remove a video sink.

        :param sink: :class:`mxdc.interface.IVideoSink` provider
        """
        if sink in self.sinks:
            self.sinks.remove(sink)

    def start(self):
        """
        Start producing video frames.
        """
        if self._stopped:
            self._stopped = False
            worker = threading.Thread(target=self.streamer, daemon=True, name='Video Thread: %s' % self.name)
            worker.start()

    def stop(self):
        """
        Stop producing video frames.
        """
        logger.debug(f'{self.name} Stopping video feed ')
        self._stopped = True

    def streamer(self):
        dur = 1.0 / self.maxfps
        while not self._stopped:
            t = time.time()
            if self.is_active() and any(not (sink.stopped) for sink in self.sinks):
                try:
                    self.fetch_frame()
                    if not self.frame:
                        continue
                    for sink in self.sinks:
                        sink.display(self.frame)
                except Exception as e:
                    logger.warning('(%s) Error fetching frame:\n %s' % (self.name, e))
                    raise
            time.sleep(max(0, dur - (time.time() - t)))

    def get_frame(self):
        """
        Obtain the most recent video frame.

        :return: A PIL Image object.
        """
        return self.frame

    def fetch_frame(self):
        """
        Update the current frame from the camera
        """
        pass

    @decorators.async_call
    def save_frame(self, filename: PathLike):
        """
        Save current frame to filename
        :param filename: str or Path
        """
        file_path = Path(filename)
        self.fetch_frame()
        if self.frame:
            logger.debug(f'Saving Frame ...{file_path.name}')
            self.frame.save(str(file_path))

    def cleanup(self):
        self.stop()


class SimCamera(VideoSrc):
    """
    Simulated Camera
    """
    def __init__(self, name="Camera Simulator", size=(1280, 960)):
        super().__init__(name=name, size=size)
        self.resolution = 5.34e-3 * numpy.exp(-0.18)
        self._packet_size = self.size[0] * self.size[1]*3
        self._fsource = open('/dev/urandom', 'rb')
        self.set_state(active=True, health=(0, '', ''))

    def fetch_frame(self):
        data = self._fsource.read(self._packet_size)
        self.frame = Image.frombytes('RGB', self.size, data)


class SimGIFCamera(VideoSrc):
    """
    Simulated Camera
    """
    def __init__(self, gonio=None, zoom=None, name="GIF Camera Simulator"):
        super().__init__(name=name, size=(1280, 960))
        self.src = Image.open(os.path.join(APP_DIR, 'share/data/simulated/crystal.gif'))
        self.num_frames = self.src.n_frames
        self.gonio = gonio
        self.zoom = zoom
        self.index = 0
        self.scale = 1.0
        self.resolution = 5.34e-3 * numpy.exp(-0.18)
        self.set_state(active=True, health=(0, '', ''))
        if self.zoom is not None:
            self.zoom.connect('changed', self.on_zoom)
        if self.gonio is not None:
            self.gonio.omega.connect('changed', self.on_gonio)

    def on_gonio(self, obj, pos):
        self.index = int(self.num_frames * (pos % 360.)/360.)

    def on_zoom(self, obj, pos):
        self.scale = pos/2

    def fetch_frame(self):
        self.src.seek(self.index)
        if self.gonio is None:
            self.index = (self.index + 1) % self.num_frames
        self.frame = self.src.resize(self.size, Image.NEAREST).convert('RGB')


@implementer(IPTZCameraController)
class SimPTZCamera(SimCamera):
    """
    Simulated PTZ Camera
    """
    def __init__(self):
        super().__init__(name='Sim PTZ Camera', size=(1920, 1080))

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
    """
    MJPG Camera
    """
    def __init__(self, url, size=(768, 576), name='MJPG Camera'):
        VideoSrc.__init__(self, name, maxfps=10.0, size=size)
        self._read_size = 1024
        self.url = url
        self._last_frame = time.time()
        self.stream = None
        self.set_state(active=True)

    def fetch_frame(self):
        if not self.stream:
            self.stream = requests.get(self.url, stream=True).raw
        try:
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
                time.sleep(0.001)
        except Exception as e:
            logger.error(e)
            self.stream = requests.get(self.url, stream=True).raw


class JPGCamera(VideoSrc):
    """
    JPG Camera
    """
    def __init__(self, url, size=(768, 576), name='JPG Camera'):
        VideoSrc.__init__(self, name, maxfps=10.0, size=size)
        self.url = url
        self.session = requests.Session()
        self.set_state(active=True)

    def fetch_frame(self):
        r = self.session.get(self.url)
        if r.status_code == 200:
            self.frame = Image.open(BytesIO(r.content))


class REDISCamera(VideoSrc):
    """
    REDIS Camera
    """
    ATTRS = {
        'gain': 'GainRaw',
        'exposure': 'ExposureTimeAbs'
    }

    def __init__(self, server, mac, size=(1280, 1024), name='REDIS Camera'):
        VideoSrc.__init__(self, name, maxfps=15.0, size=size)
        self.key = mac
        self.stores = {
            threading.current_thread(): redis.Redis(host=server, port=6379, db=0)
        }
        self.server = server
        self.set_state(active=True)

    def get_store(self):
        thread = threading.current_thread()
        if thread in self.stores:
            return self.stores[thread]
        else:
            self.stores[thread] = redis.Redis(host=self.server, port=6379, db=0)
            return self.stores[thread]

    def configure(self, **kwargs):
        conn = self.get_store()
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
            conn.publish('{}:CFG:{}'.format(self.key, attr), value)

    def fetch_frame_raw(self):
        conn = self.get_store()
        data = conn.get('{}:RAW'.format(self.key))
        while len(data) < self.size[0] * self.size[1] * 3:
            data = conn.get('{}:RAW'.format(self.key))
            time.sleep(0.001)
        img = Image.frombytes('RGB', self.size, data, 'raw')
        self.frame = img.transpose(Image.FLIP_LEFT_RIGHT)

    def fetch_frame_jpg(self):
        conn = self.get_store()
        data = conn.get('{}:JPG'.format(self.key))
        self.frame = Image.open(BytesIO(data))

    def fetch_frame(self):
        self.fetch_frame_jpg()


class AxisCamera(JPGCamera):
    """
    Axis JPG Camera
    """
    def __init__(self, hostname, idx=None, size=(1280,1024), name='Axis Camera'):
        if idx is None:
            url = 'http://%s/jpg/image.jpg' % hostname
        else:
            url = 'http://%s/jpg/%s/image.jpg' % (hostname, idx)
        super(AxisCamera, self).__init__(url, name=name, size=size)


@implementer(IZoomableCamera)
class ZoomableCamera(object):

    def __init__(self, camera, zoom_motor):
        self.camera = camera
        self._zoom = zoom_motor

    def zoom(self, value, wait=False):
        """
        Zoom to the given value.

        :param value: zoom value
        :param wait: (boolean) default False, whether to wait until camera has zoomed in.
        """
        self._zoom.move_to(value, wait=wait)

    def __getattr__(self, key):
        try:
            return getattr(self.camera, key)
        except AttributeError:
            raise


@implementer(IPTZCameraController)
class AxisPTZCamera(AxisCamera):
    """
    Axis PTZ Camera
    """
    def __init__(self, hostname, idx=None, size=(1920, 1080), name='Axis PTZ Camera'):
        AxisCamera.__init__(self, hostname, idx=idx, size=size, name=name)
        self.url_root = 'http://{}/axis-cgi/com/ptz.cgi'.format(hostname)
        self._rzoom = 0
        self.presets = []
        try:
            self.fetch_presets()
        except requests.ConnectionError:
            logger.error('Failed to establish connection')

    def zoom(self, value, wait=False):
        requests.get(self.url_root, params={'rzoom': value})
        self._rzoom -= value

    def center(self, x, y):
        """
        Center the Pan-Tilt-Zoom Camera at the given point.
        :param x: (int), x point
        :param y: (int), y point
        """
        requests.get(self.url_root, params={'center': '{},{}'.format(x, y)})

    def goto(self, position):
        """
        Go to the given named position
        :param position: named position
        """
        requests.get(self.url_root, params={'gotoserverpresetname': position})
        self._rzoom = 0

    def get_presets(self):
        return self.presets

    def fetch_presets(self):
        """
        Obtain a list of named positions from the PTZ Camera
        :return: list of strings
        """
        presets = []
        r = requests.get(self.url_root, params={'query': 'presetposall'})
        if r.status_code == requests.codes.ok:
            pospatt = re.compile(r'presetposno.+=(?P<name>[\w ]+)')
            for line in r.text.split('\n'):
                m = pospatt.match(line)
                if m:
                    presets.append(m.group('name'))
        self.presets = presets
