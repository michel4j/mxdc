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

from mxdc.utils.decorators import async_call
from mxdc.utils import cmaps, colors
from mxdc.utils.gui import color_palette
from mxdc.devices.interfaces import IVideoSink
from mxdc.utils.video import image_to_surface
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class VideoBox(Enum):
    PAD, CROP = range(2)


def pix(v):
    """Round to neareast 0.5 for cairo drawing"""
    x = round(v * 2)
    return x / 2 if x % 2 else (x + 1) / 2


@implementer(IVideoSink)
class VideoWidget(Gtk.DrawingArea):

    def __init__(self, camera, pixel_size=1.0, width=700):
        super(VideoWidget, self).__init__()
        self.props.expand = True
        self.props.halign = Gtk.Align.FILL
        self.props.valign = Gtk.Align.FILL
        self.camera = camera

        self.scale = 1.0
        self.size = numpy.array([0, 0], dtype=int)
        self.pixel_size = pixel_size
        self.mm_scale = 1.0

        self.overlays = {}  # keys 'beam', 'ruler', 'box', 'grid', 'points'
        self.image = None

        self.this_surface = None
        self.next_surface = None


        self.save_file = None
        self.stopped = False
        self.colorize = False
        self.ready = False
        self.palette = color_palette(cmaps.gist_ncar)
        self.colormap = colors.ColorMapper(vmin=0, vmax=100)
        self.set_display_size(width)

        self.fps = 0
        self._frame_count = 0
        self._frame_time = time.time()

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

    def set_src(self, src):
        self.camera = src
        self.camera.start()

    def set_pixel_size(self, size):
        """
        Update the pixel size.  Assumes square pixels.

        :param size: pixel_size
        """
        self.pixel_size = size
        self.mm_scale = size / self.scale

    def get_mm_scale(self):
        return self.pixel_size / self.scale

    def pix_to_image(self, x, y):
        """
        Convert display pixel coordinates to image pixel coordinates

        :param x: screen x pixel position
        :param y: screen y pixel position
        :return: tuple containing x and y image pixel coordinates
        """

        return x/self.scale, y/self.scale

    def pix_to_mm(self, x: float, y: float) -> tuple:
        """
        Convert display pixel coordinates to coordinates from center in mm
        :param x: screen x pixel position
        :param y: screen y pixel position
        :return: tuple containing x and y coordinates in mm
        """

        cx, cy = self.get_size() * 0.5
        xmm = (cx - x) * self.mm_scale
        ymm = (cy - y) * self.mm_scale
        return xmm, ymm

    def set_display_size(self, width):
        """
        Configure the display width, adjusting height accordingly to keep aspect ratio

        :param width: display width
        """
        video_width, video_height = self.camera.size
        height = int(video_height/video_width * width)
        self.set_size_request(width, height)
        #self.update_size(width, height)

    def update_size(self, width, height):
        video_width, video_height = self.camera.size
        self.size[:] = width, height
        self.scale = width / video_width
        self.mm_scale = self.pixel_size / self.scale
        self.ready = True

    def do_configure_event(self, event):
        video_width, video_height = self.camera.size
        aspect_ratio = video_width/video_height
        width_for_height = int(event.height * aspect_ratio)
        height_for_width = int(event.width / aspect_ratio)

        if height_for_width > event.height:
            height = event.height
            width = width_for_height
        else:
            width = event.width
            height = height_for_width

        self.size[:] = width, height
        self.scale = width / video_width
        self.mm_scale = self.pixel_size / self.scale
        self.ready = True

        #print(event.width, event.height, self.size)

    def on_destroy(self, obj):
        self.camera.del_sink(self)
        self.camera.stop()

    def get_size(self):
        return self.size

    def update_fps(self, frames=10):
        self._frame_count += 1
        if self._frame_count == frames:
            self.fps = self._frame_count / (time.time() - self._frame_time)
            self._frame_time = time.time()
            self._frame_count = 0

    def display(self, img):
        if self.stopped:
            return
        try:
            img = img.resize(self.size, Image.BICUBIC)
            if self.colorize:
                if img.mode != 'L':
                    img = img.convert('L')
                img.putpalette(self.palette)

            img = img.convert('RGB')
        except (OSError, ValueError):
            pass    # silently ignore bad images
        else:
            self.next_surface = image_to_surface(img)
            GLib.idle_add(self.queue_draw)

    def set_colorize(self, state=True):
        self.colorize = state

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

    def clear_overlays(self):
        """
        Remove all overlays

        """
        self.overlays = {}

    def set_overlay_beam(self, aperture: float = None):
        """
        Set the aperture size
        :param aperture: beam size mm
        """
        if aperture:
            self.overlays['beam'] = aperture
        else:
            self.overlays.pop('beam', None)
        self.queue_draw()

    def set_overlay_points(self, points = None):
        """
        Set the overlay points parameters
        :param points: numpy xyz array
        """
        if points is not None:
            self.overlays['points'] = points
        else:
            self.overlays.pop('points', None)
        self.queue_draw()

    def set_overlay_grid(self, grid: dict = None):
        """
        Set the overlay grid parameters
        :param grid: a tuple of tuples
        """

        if grid is not None:
            self.overlays['grid'] = grid
            if 'scores' in grid:
                self.colormap.rescale(grid['scores'])

        else:
            self.overlays.pop('grid', None)
        self.queue_draw()

    def set_overlay_box(self, coords: tuple = None):
        """
        Set the ruler coordinates
        :param coords: a tuple of tuples
        """
        if coords is not None:
            self.overlays['box'] = coords
        else:
            self.overlays.pop('box', None)
        self.queue_draw()

    def set_overlay_ruler(self, coords: tuple = None):
        """
        Set the ruler coordinates
        :param coords: a tuple of tuples
        """
        if coords is not None:
            self.overlays['ruler'] = coords
        else:
            self.overlays.pop('ruler', None)
        self.queue_draw()

    def save_image(self, filename):
        self.save_file = filename

    def do_draw(self, cr):
        if self.next_surface is not None:
            self.this_surface = self.next_surface

            target = cairo.ImageSurface(cairo.FORMAT_ARGB32, *self.size)
            ctx = cairo.Context(target)
            ctx.set_source_surface(self.this_surface, 0, 0)
            ctx.paint()
            self.draw_beam(ctx)
            self.draw_ruler(ctx)
            self.draw_box(ctx)
            self.draw_points(ctx)
            self.draw_grid(ctx)

            cr.set_source_surface(target, 0, 0)
            cr.paint()

            if self.save_file:
                self.save_snapshot(target, self.save_file)
                self.save_file = None

    @async_call
    def save_snapshot(self, target, filename):
        target.write_to_png(filename)
        logger.info('{} saved'.format(filename))

    def draw_beam(self, cr):
        if self.overlays.get('beam') is None:
            return

        radius = self.overlays['beam'] * 0.5 / self.get_mm_scale()
        tick_start = radius * 0.7
        tick_size = radius * 0.6
        cx, cy = self.size/2

        cr.set_source_rgba(1.0, 0.25, 0.0, 1.0)
        cr.set_line_width(1.5)

        cr.arc(cx, cy, radius, 0, 2.0 * numpy.pi)
        cr.move_to(cx, cy + tick_start)
        cr.rel_line_to(0, tick_size)
        cr.move_to(cx, cy - tick_start)
        cr.rel_line_to(0, -tick_size)
        cr.move_to(cx + tick_start, cy)
        cr.rel_line_to(tick_size, 0)
        cr.move_to(cx - tick_start, cy)
        cr.rel_line_to(-tick_size, 0)
        cr.stroke()

    def draw_ruler(self, cr):
        if self.overlays.get('ruler') is None:
            return

        (x1, y1), (x2, y2) = self.overlays['ruler']
        dist = 1000 * self.get_mm_scale() * numpy.sqrt((x2 - x1) ** 2.0 + (y2 - y1) ** 2.0)

        cr.set_font_size(10)
        cr.set_source_rgba(0.0, 0.5, 1.0, 1.0)
        cr.set_line_width(1.0)
        cr.move_to(x1, y1)
        cr.line_to(x2, y2)
        cr.stroke()

        label = '{:0.0f} µm'.format(dist)
        xb, yb, w, h = cr.text_extents(label)[:4]
        cr.move_to(x1 - w*(int(x2>x1) + xb/w), y1 - h*(int(y2>y1) + yb/h))
        cr.show_text(label)

    def draw_box(self, cr):
        if self.overlays.get('box') is None:
            return

        cr.set_font_size(10)
        cr.set_line_width(1.0)

        cr.set_source_rgba(0.0, 1.0, 1.0, 1.0)

        # rectangle
        (x1, y1), (x2, y2) = self.overlays['box']
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

        cr.set_operator(cairo.OPERATOR_DIFFERENCE)
        cr.rectangle(x1, y1, x2-x1, y2-y1)
        cr.stroke()


        # width
        width = 1e3 * self.get_mm_scale() * abs(x2 - x1)
        w_label = '{:0.0f} µm'.format(width)
        xb, yb, w, h = cr.text_extents(w_label)[:4]
        cr.move_to(cx - w/2, y1 - h/2)
        cr.show_text(w_label)

        # height
        height = 1e3 * self.get_mm_scale() * abs(y2 - y1)
        h_label = '{:0.0f} µm'.format(height)
        cr.move_to(x2 + h/2, cy)
        cr.show_text(h_label)
        cr.set_operator(cairo.OPERATOR_OVER)

    def draw_grid(self, cr):
        if self.overlays.get('grid') is None or self.overlays.get('beam') is None:
            return

        grid = self.overlays['grid']
        radius = self.overlays['beam'] * 0.5 / self.mm_scale
        width = 2 * radius
        font_size = min(width/3.15, 10)

        coords = grid.get('coords')
        scores = grid.get('scores')
        indices = grid.get('indices')
        frames = grid.get('frames')

        if any((coords is None, indices is None, frames is None)):
            return

        cr.set_line_width(1.0)
        cr.set_font_size(font_size)
        for i, (x, y, z) in enumerate(coords):
            try:
                ij = indices[i]
                frame = frames[i]
            except IndexError:
                continue

            ox, oy = x-radius, y-radius
            if scores is not None and scores[ij] >= 0:
                cr.set_source_rgba(*self.colormap.rgba_values(scores[ij], alpha=0.65))
                cr.rectangle(ox, oy, width, width)
                cr.fill()
            else:
                cr.set_source_rgba(0.5, 0.5, 0.5, 0.35)
                cr.rectangle(ox, oy, width-0.5, width-0.5)
                cr.fill()

            if font_size > 6:
                cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                cr.set_operator(cairo.OPERATOR_DIFFERENCE)
                name = f'{frame}'
                xb, yb, w, h = cr.text_extents(name)[:4]
                cr.move_to(x - w / 2. - xb, y - h / 2. - yb)
                cr.show_text(name)
                cr.set_operator(cairo.OPERATOR_OVER)

    def draw_points(self, cr):
        if self.overlays.get('points') is None or self.overlays.get('beam') is None:
            return

        points = self.overlays['points']
        radius = self.overlays['beam'] * 0.5 / self.mm_scale
        center = self.size / 2
        xyz = points / self.mm_scale
        radii = 0.5 * (1.0 - (xyz[:, 2] / center[1])) * radius
        xyz[:, :2] += center

        for i, (x, y, z) in enumerate(xyz):
            cr.set_source_rgba(1.0, 0.5, 0.5, 0.5)
            cr.arc(x, y, max(radii[i], 4), 0, 2.0 * 3.14)
            cr.fill()
            cr.move_to(x + 6, y)
            label = f'P{i+1}'
            xb, yb, w, h = cr.text_extents(label)[:4]
            cr.move_to(x - w / 2. - xb, y - h / 2. - yb)
            cr.set_source_rgba(1, 0.25, 0.25, 1)
            cr.set_operator(cairo.OPERATOR_DIFFERENCE)
            cr.show_text(label)
            cr.set_operator(cairo.OPERATOR_OVER)



@Gtk.Template.from_resource('/org/gtk/mxdc/data/video_view.ui')
class VideoView(Gtk.Window):
    __gtype_name__ = 'VideoView'

    video_frame = Gtk.Template.Child()

    def __init__(self, beamline, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.beamline = beamline
        self.canvas = VideoWidget(camera=self.beamline.sample_camera, pixel_size=self.beamline.camera_scale.get())

        self.canvas.props.valign =  Gtk.Align.FILL
        self.canvas.props.halign = Gtk.Align.FILL

        self.video_frame.add(self.canvas)
        self.canvas.set_src(self.beamline.sample_camera)
        self.canvas.set_overlay_beam(self.beamline.aperture.get_position()/1000.)
        self.beamline.camera_scale.connect('changed', self.on_camera_scale)
        self.video_frame.show_all()


    def on_camera_scale(self, obj, value):
        self.canvas.set_pixel_size(value)

    def do_configure_event(self, event):
        self.canvas.queue_resize()





