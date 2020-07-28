import time

import gi
import numpy
from enum import Enum
from PIL import Image

gi.require_version('Gtk', '3.0')

from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import Gtk
from zope.interface import implementer
import cairo

from mxdc.utils import cmaps
from mxdc.utils.gui import color_palette
from mxdc.devices.interfaces import IVideoSink
from mxdc.utils.video import image_to_surface
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class VideoBox(Enum):
    PAD, CROP = range(2)


@implementer(IVideoSink)
class VideoWidget(Gtk.DrawingArea):

    def __init__(self, camera, pixel_size=1.0, mode=VideoBox.PAD):
        super(VideoWidget, self).__init__()
        self.props.expand = True
        self.props.halign = Gtk.Align.FILL
        self.props.valign = Gtk.Align.FILL
        self.camera = camera
        self.mode = mode
        self.scale = 1
        self.pixel_size = pixel_size
        self.voffset = 0
        self.hoffset = 0
        self.surface = None
        self.save_file = None
        self.stopped = False
        self.colorize = False
        self.palette = color_palette(cmaps.gist_ncar)
        self.display_width = 0
        self.display_height = 0

        self.fps = 0
        self._frame_count = 0
        self._frame_time = time.time()

        self.overlay_func = None
        self.display_func = None
        self.set_events(
            Gdk.EventMask.EXPOSURE_MASK |
            Gdk.EventMask.LEAVE_NOTIFY_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.POINTER_MOTION_HINT_MASK |
            Gdk.EventMask.VISIBILITY_NOTIFY_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.SCROLL_MASK
        )

        self.connect('visibility-notify-event', self.on_visibility_notify)
        self.connect('unmap', self.on_unmap)
        self.connect('realize', self.on_realized)
        self.connect("unrealize", self.on_destroy)
        self.connect('configure-event', self.on_configure_event)

    def set_src(self, src):
        self.camera = src
        self.camera.connect('resized', self.on_resize)
        self.camera.start()

    def set_pixel_size(self, size):
        """
        Update the pixel size.  Assumes square pixels.

        :param size: pixel_size
        """
        self.pixel_size = size

    def mm_scale(self):
        return self.pixel_size / self.scale

    def screen_to_mm(self, x, y):
        mm_scale = self.mm_scale()
        cx, cy = numpy.array(self.get_size()) * 0.5
        xmm = (cx - x) * mm_scale
        ymm = (cy - y) * mm_scale
        ix = x / self.scale
        iy = y / self.scale
        return ix, iy, xmm, ymm

    def set_display_size(self, width, height):
        self.display_width, self.display_height = width, height

    def on_destroy(self, obj):
        self.camera.del_sink(self)
        self.camera.stop()

    def configure_video(self, dwidth, dheight, vwidth, vheight):
        """
        Configure the display

        :param dwidth: display widget width in pixels
        :param dheight: display widget height in pixels
        :param vwidth: video width in pixels
        :param vheight: video height in pixels
        """

        if self.mode == VideoBox.CROP:
            self.configure_crop(dwidth, dheight, vwidth, vheight)
        else:
            self.configure_pad(dwidth, dheight, vwidth, vheight)

    def configure_pad(self, dwidth, dheight, vwidth, vheight):
        video_aspect = float(vwidth) / vheight
        display_aspect = float(dwidth) / dheight

        if display_aspect < video_aspect:
            width = dwidth
            self.scale = float(width) / vwidth
            height = int(round(width / video_aspect))
            self.voffset = (dheight - height) // 2
            self.hoffset = 0
        else:
            height = dheight
            self.scale = float(height) / vheight
            width = int(round(video_aspect * height))
            self.hoffset = (dwidth - width) // 2
            self.voffset = 0

        self.display_width, self.display_height = width, height
        if dwidth > 12:
            self.props.parent.set(0.5, 0.5, video_aspect, False)

    def configure_crop(self, dwidth, dheight, vwidth, vheight):
        video_aspect = float(vwidth) / vheight
        display_aspect = float(dwidth) / dheight

        if display_aspect < video_aspect:
            width = dwidth
            self.scale = float(width) / vwidth
            height = int(round(width / video_aspect))
            self.voffset = 0
            self.hoffset = (dwidth - width) // 2
        else:
            height = dheight
            self.scale = float(height) / vheight
            width = int(round(video_aspect * height))
            self.hoffset = 0
            self.voffset = (dheight - height) // 2

        self.display_width, self.display_height = width, height

        if dwidth > 12:
            self.props.parent.set(0.5, 0.5, video_aspect, False)

    def on_configure_event(self, widget, event):
        self.configure_video(event.width, event.height, *self.camera.size)

    def on_resize(self, camera, width, height):
        self.configure_video(self.display_width, self.display_height, width, height)

    def get_size(self):
        return self.display_width, self.display_height

    def set_overlay_func(self, func):
        self.overlay_func = func

    def set_display_func(self, func):
        self.display_func = func

    def update_fps(self, frames=10):
        self._frame_count += 1
        if self._frame_count == frames:
            self.fps = self._frame_count / (time.time() - self._frame_time)
            self._frame_time = time.time()
            self._frame_count = 0

    def display(self, img):
        if self.stopped:
            return
        img = img.resize((self.display_width, self.display_height), Image.BICUBIC)
        if self.colorize:
            if img.mode != 'L':
                img = img.convert('L')
            img.putpalette(self.palette)

        img = img.convert('RGB')
        self.surface = image_to_surface(img)
        GLib.idle_add(self.queue_draw)
        self.update_fps()
        if self.display_func is not None:
            self.display_func(img, scale=self.scale)

    def set_colorize(self, state=True):
        self.colorize = state

    def do_draw(self, cr):
        if self.surface is not None:
            if self.overlay_func is not None:
                ctx = cairo.Context(self.surface)
                self.overlay_func(ctx)
            cr.set_source_surface(self.surface, 0, 0)
            cr.paint()

            if self.save_file:
                self.surface.write_to_png(self.save_file)
                logger.info('{} saved'.format(self.save_file))
                self.save_file = None

    def on_realized(self, obj):
        self.camera.add_sink(self)
        return True

    def on_visibility_notify(self, obj, event):
        if event.get_state() == Gdk.VisibilityState.FULLY_OBSCURED:
            self.stopped = True
        else:
            self.stopped = False
        return True

    def on_unmap(self, obj):
        self.stopped = True

    def save_image(self, filename):
        self.save_file = filename
