import os
import pickle
import time

import gi
import numpy
from PIL import Image

gi.require_version('Gtk', '3.0')

from gi.repository import GObject
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gtk
from zope.interface import implements

from mxdc.utils import cmaps
from mxdc.utils.gui import color_palette
from mxdc.devices.interfaces import IVideoSink
from mxdc.utils.video import image_to_surface


class VideoWidget(Gtk.DrawingArea):
    implements(IVideoSink)

    def __init__(self, camera):
        super(VideoWidget, self).__init__()
        self.props.expand = True
        self.props.halign = Gtk.Align.FILL
        self.props.valign = Gtk.Align.FILL
        self.camera = camera
        self.scale = 1
        self.voffset = 0
        self.hoffset = 0
        self.surface = None
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
        #self.connect('draw', self.on_draw)
        self.connect('realize', self.on_realized)
        self.connect("unrealize", self.on_destroy)
        self.connect('configure-event', self.on_configure_event)
        self.override_background_color(Gtk.StateType.NORMAL, Gdk.RGBA(red=0, green=1, blue=0, alpha=1))

    def set_src(self, src):
        self.camera = src
        self.camera.start()

    def mm_scale(self):
        return self.camera.resolution / self.scale

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

    def on_configure_event(self, widget, event):
        frame_width, frame_height = event.width, event.height
        video_width, video_height = self.camera.size

        video_ratio = float(video_width) / video_height
        frame_ratio = float(frame_width) / frame_height

        if frame_ratio < video_ratio:
            width = frame_width
            height = int(round(width / video_ratio))
            self.voffset = (frame_height - height) // 2
            self.hoffset = 0
        else:
            height = frame_height
            width = int(round(video_ratio * height))
            self.hoffset = (frame_width - width) // 2
            self.voffset = 0

        self.scale = float(width) / video_width
        self.display_width, self.display_height = width, height
        if event.width > 12:
            self.props.parent.set(0.5, 0.5, video_ratio, False)

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
        img = img.resize((self.display_width, self.display_height), Image.BICUBIC)
        if self.colorize:
            if img.mode != 'L':
                img = img.convert('L')
            img.putpalette(self.palette)
        img = img.convert('RGB')
        self.surface = image_to_surface(img)
        GObject.idle_add(self.queue_draw)
        self.update_fps()
        if self.display_func is not None:
            self.display_func(img, scale=self.scale)

    def set_colorize(self, state=True):
        self.colorize = state

    def do_draw(self, cr):
        if self.surface is not None:
            cr.set_source_surface(self.surface, 0, 0)
            cr.paint()
            if self.overlay_func is not None:
                self.overlay_func(cr)

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
        window = self.get_window()
        colormap = window.get_colormap()
        pixbuf = GdkPixbuf.Pixbuf(GdkPixbuf.Colorspace.RGB, 0, 8, *window.get_size())
        pixbuf = pixbuf.get_from_drawable(window, colormap, 0, 0, 0, 0, *window.get_size())
        ftype = os.path.splitext(filename)[-1]
        ftype = ftype.lower()
        if ftype in ['.jpg', '.jpeg']:
            ftype = 'jpeg'
        else:
            ftype = 'png'
        pixbuf.save(filename, ftype)
