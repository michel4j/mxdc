import logging
import math
import threading
import time
from typing import Any, Tuple, List
from enum import Enum
from collections import deque
from methodtools import lru_cache
from dataclasses import dataclass, field

import cairo
import cv2
import matplotlib
import numpy
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('PangoCairo', "1.0")

from gi.repository import Gdk, Gtk, GLib, PangoCairo
from matplotlib.backends.backend_cairo import FigureCanvasCairo, RendererCairo
from matplotlib.figure import Figure
from matplotlib.ticker import FormatStrFormatter, MaxNLocator
from mxio import read_image, formats

from mxdc import Signal, Object
from mxdc.utils import cmaps, colors
from mxdc.utils.frames import bressenham_line
from mxdc.utils.gui import color_palette

logger = logging.getLogger('image-widget')

RESCALE_TIMEOUT = 30  # duration between images to apply auto-rescale
SCALE_MULTIPLIER = 3.0
MAX_SCALE = 12.0
MIN_SCALE = 0.0
RESOLUTION_STEP_SIZE = 30  # Radial step size between resolution rings in mm
LABEL_GAP = 0.0075  # Annotation label gap
COLOR_MAPS = ('binary', 'inferno')
MAX_SAVE_JITTER = 0.5  # maximum amount of time in seconds to wait for file to be done writing to disk


@dataclass
class Box:
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    def get_start(self):
        return self.x, self.y

    def get_end(self):
        return self.x + self.width, self.y + self.height

    def set_end(self, x, y):
        self.width = x - self.x
        self.height = y - self.y

    def set_start(self, x, y):
        self.x = x
        self.y = y

    def normalize(self):
        self.x = int(min(self.x, self.x + self.width))
        self.width = int(abs(self.width))
        self.y = int(min(self.y, self.y + self.height))
        self.height = int(abs(self.height))


@dataclass
class Spots:
    data: Any = None
    selected: Any = None

    def select(self, frame_number, span=5):
        if self.data is not None:
            sel = (self.data[:, 2] >= frame_number - span // 2)
            sel &= (self.data[:, 2] <= frame_number + span // 2)
            self.selected = self.data[sel]
        else:
            self.selected = None


@dataclass
class ScaleSettings:
    scale: float = 1.0
    multiplier: float = SCALE_MULTIPLIER
    default: float = SCALE_MULTIPLIER

    def update(self, min_value: float, max_value: float, avg_value: float, std_dev: float):
        if std_dev > 0:
            self.default = SCALE_MULTIPLIER * (max_value - avg_value) / std_dev
        self.scale = avg_value + self.multiplier * std_dev

    def adjust(self, direction: int = None, avg_value: float = 0.0, std_dev: float = 0.0):
        if direction is None:
            self.multiplier = self.default
        else:
            step = direction * max(round(self.multiplier / 10, 2), 0.1)
            self.multiplier = min(MAX_SCALE, max(MIN_SCALE, self.multiplier + step))
        self.scale = avg_value + self.multiplier * std_dev


class MouseMode(Enum):
    NONE, PANNING, MEASURING, SELECTING = range(4)


@dataclass
class ImageSettings:
    scale: float = 1.0
    mode: MouseMode = MouseMode.NONE
    initialized: bool = False
    annotate: bool = False
    width: int = 0
    height: int = 0
    profile: Any = None
    surface: Any = None
    mouse_box: Box = field(init=False)

    def __post_init__(self):
        self.mouse_box = Box()


@dataclass
class Frame:
    dataset: formats.DataSet
    rescale: bool = True
    color_map: Any = field(init=False, repr=False)
    data: numpy.ndarray = field(init=False, repr=False)
    stats_data: numpy.ndarray = field(init=False, repr=False)
    settings: ScaleSettings = field(init=False, repr=False)
    header: dict = field(init=False, repr=False)
    image: Any = field(init=False, repr=False)
    redraw: bool = False
    dirty: bool = True

    name: str = field(init=False)
    size: Tuple[int, int] = field(init=False)
    pixel_size: float = field(init=False)
    beam_x: float = field(init=False)
    beam_y: float = field(init=False)
    index: int = field(init=False)
    delta_angle: float = field(init=False)
    distance: float = field(init=False)
    wavelength: float = field(init=False)
    saturated_value: float = field(init=False)
    resolution_shells: List[float] = field(init=False)

    def __post_init__(self):
        self.set_colormap('binary')
        self.header = self.dataset.header
        self.data = self.dataset.data
        self.stats_data = self.dataset.stats_data
        self.size = self.header['detector_size']
        self.index = self.header['frame_number']
        self.name = f'{self.header["name"]} [ {self.index} ]'
        self.beam_x, self.beam_y = self.header['beam_center']
        self.delta_angle = self.header['delta_angle']
        self.pixel_size = self.header['pixel_size']
        self.distance = self.header['distance']
        self.wavelength = self.header['wavelength']
        self.saturated_value = self.header['saturated_value']

        radii = numpy.arange(0, int(1.4142 * self.size[0] / 2), RESOLUTION_STEP_SIZE / self.pixel_size)[1:]
        self.resolution_shells = self.radius_to_resolution(radii)

    def setup(self, rescale: bool = False, settings: ScaleSettings = None):
        if self.dirty:
            if settings is not None:
                self.settings = settings
            elif self.settings is None:
                self.settings = ScaleSettings()

            if rescale:
                p_lo, p_hi = numpy.percentile(self.stats_data, (5., 95.))
                self.header['percentiles'] = p_lo, p_hi
                self.settings.update(p_lo, p_hi, self.header['average_intensity'], self.header['std_dev'])

            t = time.time()
            img0 = cv2.convertScaleAbs(self.data, None, 256 / self.settings.scale, 0)
            img1 = cv2.applyColorMap(img0, self.color_map)
            self.image = cv2.cvtColor(img1, cv2.COLOR_BGR2BGRA)

            self.dirty = False
            self.redraw = True

    @lru_cache()
    def get_resolution_rings(self, view_x, view_y, view_width, view_height, scale):
        x, y, w, h = view_x, view_y, view_width, view_height
        cx = int((self.beam_x - x) * scale)
        cy = int((self.beam_y - y) * scale)

        vx = (w // 2) * scale
        vy = (h // 2) * scale
        label_angle = numpy.arctan2(vy - cy, vx - cx)  # optimal angle for labels
        ux = scale * math.cos(label_angle)
        uy = scale * math.sin(label_angle)

        radii = numpy.arange(0, int(1.4142 * self.size[0] / 2), RESOLUTION_STEP_SIZE / self.pixel_size)[1:]
        shells = self.radius_to_resolution(radii)
        lx = cx + radii * ux
        ly = cy + radii * uy
        offset = shells * LABEL_GAP / scale

        return numpy.column_stack((radii * scale, shells, lx, ly, label_angle + offset, label_angle - offset)), (cx, cy)

    def image_resolution(self, x, y):
        displacement = numpy.sqrt((x - self.beam_x) ** 2 + (y - self.beam_y) ** 2)
        return self.radius_to_resolution(displacement)

    def resolution_to_radius(self, d):
        angle = numpy.arcsin(numpy.float(self.wavelength) / (2 * d))
        return self.distance * numpy.tan(2 * angle) / self.pixel_size

    def radius_to_resolution(self, r):
        angle = 0.5 * numpy.arctan2(r * self.pixel_size, self.distance)
        return numpy.float(self.wavelength) / (2 * numpy.sin(angle))

    def radial_distance(self, x0, y0, x1, y1):
        d = numpy.sqrt((x0 - x1) ** 2 + (y0 - y1) ** 2) * self.pixel_size
        return d

    def set_colormap(self, name: str):
        c_map = matplotlib.cm.get_cmap(name, 256)
        rgba_data = matplotlib.cm.ScalarMappable(cmap=c_map).to_rgba(numpy.arange(0, 1.0, 1.0 / 256.0), bytes=True)
        rgba_data = rgba_data[:, :-1].reshape((256, 1, 3))
        self.color_map = rgba_data[:, :, ::-1]
        self.dirty = True

    def adjust(self, direction=None):
        self.settings.adjust(
            direction=direction, avg_value=self.header['average_intensity'], std_dev=self.header['std_dev']
        )
        self.dirty = True

    def next_frame(self):
        return self.dataset.next_frame()

    def prev_frame(self):
        return self.dataset.prev_frame()

    def load_frame(self, number):
        return self.dataset.get_frame(number)


class DataLoader(Object):
    class Signals:
        new_image = Signal("new-image", arg_types=())

    def __init__(self, outbox: deque):
        super().__init__()
        self.stopped = False
        self.paused = False
        self.cur_frame = None
        self.frames = deque(maxlen=2)
        self.inbox = deque(maxlen=2)
        self.outbox = outbox
        self.settings = ScaleSettings()
        self.load_next = False
        self.load_prev = False
        self.load_number = None
        self.color_scheme = 'binary'
        self.start()

    def open(self, path):
        """
        Add data path to queue for lazy loading

        :param path: full path to data frame
        """
        self.inbox.append(path)

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def show(self, dataset):
        """
        Prepare and display externally loaded dataset

        :param dataset: dataset
        """
        self.frames.append(Frame(dataset=dataset))

    def load(self, path):
        try:
            dataset = read_image(path)
            self.show(dataset)
            success = True
        except Exception as e:
            logger.error(e)
            success = False

        if not success:
            logger.warning("Unable to load {}".format(path))
        return success

    def set_colormap(self, name: str = 'binary'):
        self.color_scheme = name

    def set_current_frame(self, frame):
        self.cur_frame = frame

    def load_frame(self, number):
        self.load_number = number

    def next_frame(self):
        self.load_next = True

    def prev_frame(self):
        self.load_prev = True

    def start(self):
        self.stopped = False
        self.paused = False
        worker_thread = threading.Thread(target=self.run, daemon=True, name="DataLoader")
        worker_thread.start()

    def stop(self):
        self.stopped = True

    def run(self):
        last_update = 0
        while not self.stopped:
            time.sleep(0.05)
            if self.paused:
                continue

            # Setup any frames in the deque and add them to the display queue
            rescale = (time.time() - last_update > RESCALE_TIMEOUT)
            if len(self.frames):
                frame = self.frames.popleft()
                frame.set_colormap(self.color_scheme)
                frame.setup(settings=self.settings, rescale=rescale)
                self.outbox.append(frame)
                last_update = time.time()

            if self.cur_frame:
                try:
                    success = False
                    if self.load_next:
                        success = self.cur_frame.next_frame()
                        self.load_next = False
                    elif self.load_prev:
                        success = self.cur_frame.prev_frame()
                        self.load_prev = False
                    elif self.load_number:
                        success = self.cur_frame.load_frame(self.load_number)
                        self.load_number = None
                    if success:
                        rescale = (time.time() - last_update > RESCALE_TIMEOUT)
                        frame = Frame(dataset=self.cur_frame.dataset)
                        frame.set_colormap(self.color_scheme)
                        frame.setup(settings=self.settings, rescale=rescale)
                        self.outbox.append(frame)
                        last_update = time.time()
                except Exception as e:
                    logger.error(f"Unable to read frame: {e}")
            self.load_next = self.load_prev = False

            # load any images from specified paths in the inbox
            if len(self.inbox):
                path = self.inbox.popleft()
                self.load(path)


class ImageWidget(Gtk.DrawingArea):
    image_loaded = Signal("image-loaded", arg_types=())

    def __init__(self, size):
        super().__init__()

        self.settings = ImageSettings()
        self.frame = None
        self.surface = None
        self.spots = Spots()
        self.view = Box()
        self.view_stack = deque()
        self.inbox = deque(maxlen=5)

        self.set_events(
            Gdk.EventMask.EXPOSURE_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.POINTER_MOTION_HINT_MASK |
            Gdk.EventMask.SCROLL_MASK
        )

        self.connect('unmap', self.on_visibility, False)
        self.connect('map', self.on_visibility, True)
        self.connect('motion-notify-event', self.on_mouse_motion)
        self.connect('button-press-event', self.on_mouse_press)
        self.connect('scroll-event', self.on_mouse_scroll)
        self.connect('button-release-event', self.on_mouse_release)
        self.set_size_request(size, size)
        self.palettes = {
            True: color_palette(cmaps.inferno),
            False: color_palette(cmaps.binary)
        }

        self.data_loader = DataLoader(self.inbox)
        display_thread = threading.Thread(target=self.frame_monitor, daemon=True,
                                          name=self.__class__.__name__ + ':Display')
        display_thread.start()

    def frame_monitor(self):
        while True:
            if self.frame is not None:
                self.frame.setup()
                if self.frame.redraw:
                    self.create_surface()
                    GLib.idle_add(self.redraw)
            if len(self.inbox):
                self.frame = self.inbox.popleft()
                self.spots.select(self.frame.index)
                self.data_loader.set_current_frame(self.frame)
            time.sleep(0.01)

    def create_surface(self, full=False):
        self.settings.width, self.settings.height = self.frame.size
        width = min(self.settings.width, self.settings.height)
        if not self.view.width or full:
            self.view = Box(x=1, y=1, width=width - 2, height=width - 2)
        else:
            x = min(self.view.x, self.settings.width)
            y = min(self.view.y, self.settings.height)
            w = h = max(16, min(self.view.width, self.view.height, self.settings.width - x, self.settings.height - y))
            self.view = Box(x=x, y=y, width=w, height=h)
        self.surface = cairo.ImageSurface.create_for_data(
            self.frame.image, cairo.FORMAT_ARGB32, self.settings.width, self.settings.height
        )

    def redraw(self):
        self.queue_draw()
        self.emit('image-loaded')
        self.settings.initialized = True
        self.frame.redraw = False

    def set_reflections(self, reflections=None):
        self.spots.data = reflections
        if self.frame:
            self.spots.select(self.frame.index)
        self.queue_draw()

    def open(self, filename):
        self.data_loader.open(filename)

    def show_frame(self, frame):
        return self.data_loader.show(frame)

    def load_next(self):
        return self.data_loader.next_frame()

    def load_prev(self):
        return self.data_loader.prev_frame()

    def load_frame(self, number):
        return self.data_loader.load_frame(number)

    def get_image_info(self):
        return self.frame

    def get_line_profile(self, box, width=1):
        x1, y1 = self.get_position(*box.get_start())[:2]
        x2, y2 = self.get_position(*box.get_end())[:2]
        min_value = 0
        max_value = self.frame.saturated_value

        coords = bressenham_line(x1, y1, x2, y2)
        data = numpy.zeros((len(coords), 3))
        n = 0
        for ix, iy in coords:
            ix = max(1, ix)
            iy = max(1, iy)
            data[n][0] = n
            src = self.frame.data[iy - width:iy + width, ix - width:ix + width, ]
            sel = (src > min_value) & (src < max_value)
            if sel.sum():
                val = src[sel].mean()
            else:
                val = numpy.nan
            data[n][2] = val
            data[n][1] = self.frame.radial_distance(ix, iy, coords[0][0], coords[0][1])
            n += 1
        return data[:, 1:]

    def plot_profile(self, data):
        color = colors.Category.CAT20C[0]
        formatter = FormatStrFormatter('%g')

        figure = Figure(frameon=False, figsize=(4, 2), dpi=72, edgecolor=color)
        specs = matplotlib.gridspec.GridSpec(ncols=8, nrows=1, figure=figure)

        ax = figure.add_subplot(specs[0, 1:7])
        ax.patch.set_alpha(0.0)
        ax.yaxis.set_tick_params(color=color, labelcolor=color)
        ax.yaxis.set_major_formatter(formatter)
        ax.yaxis.set_major_locator(MaxNLocator(5))
        ax.spines['left'].set_position(('outward', 10))
        ax.spines['left'].set_color(color)
        ax.spines[['right', 'bottom', 'top']].set_visible(False)
        ax.xaxis.set_ticks([])

        ax.plot(data[:, 0], data[:, 1], lw=0.75)
        ax.set_xlim(min(data[:, 0]), max(data[:, 0]))

        # Ask matplotlib to render the figure to a bitmap using the Agg backend
        canvas = FigureCanvasCairo(figure)
        width, height = canvas.get_width_height()
        renderer = RendererCairo(canvas.figure.dpi)
        renderer.set_width_height(width, height)
        self.settings.profile = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        renderer.set_ctx_from_surface(self.settings.profile)
        canvas.figure.draw(renderer)

    def draw_overlay_cairo(self, cr):
        cr.save()
        cr.set_source_rgba(0.0, 0.5, 1.0, 1.0)
        cr.set_line_width(1)

        # cross
        x, y, w, h = self.view.x, self.view.y, self.view.width, self.view.height
        radius = 32 * self.settings.scale
        if (0 < (self.frame.beam_x - x) < x + w) and (0 < (self.frame.beam_y - y) < y + h):
            cx = int((self.frame.beam_x - x) * self.settings.scale)
            cy = int((self.frame.beam_y - y) * self.settings.scale)
            cr.move_to(cx - radius, cy)
            cr.line_to(cx + radius, cy)
            cr.stroke()
            cr.move_to(cx, cy - radius)
            cr.line_to(cx, cy + radius)
            cr.stroke()
            cr.arc(cx, cy, radius / 2, 0, 2.0 * numpy.pi)
            cr.stroke()

        # select box
        if self.settings.mode == MouseMode.SELECTING:
            cr.rectangle(
                self.settings.mouse_box.x, self.settings.mouse_box.y,
                self.settings.mouse_box.width, self.settings.mouse_box.height
            )
            cr.stroke()

        # measuring
        if self.settings.mode == MouseMode.MEASURING:
            cr.move_to(*self.settings.mouse_box.get_start())
            cr.line_to(*self.settings.mouse_box.get_end())
            cr.stroke()

        # Filename
        alloc = self.get_allocation()
        layout = self.create_pango_layout(self.frame.name)
        ink, logical = layout.get_pixel_extents()
        cr.move_to(12, alloc.height - 12 - ink.height)
        PangoCairo.show_layout(cr, layout)
        cr.fill()
        cr.restore()

    def draw_spots(self, cr):
        # draw spots
        if self.spots.selected is not None:
            x, y, w, h = self.view.x, self.view.y, self.view.width, self.view.height
            cr.set_line_width(0.75)

            for spot in self.spots.selected:
                sx, sy, sn, st = spot
                if spot[3] == 0:
                    cr.set_source_rgba(1.0, 0.0, 0.0, 1.0)
                else:
                    cr.set_source_rgba(0.0, 0.5, 1.0, 1.0)
                if (0 < (sx - x) < x + w) and (0 < (sy - y) < y + h):
                    cx = int((sx - x) * self.settings.scale)
                    cy = int((sy - y) * self.settings.scale)
                    cr.arc(cx, cy, 12 * self.settings.scale, 0, 2.0 * numpy.pi)
                    cr.stroke()

    def draw_rings(self, cr):
        if self.settings.annotate:

            cr.save()
            cr.set_operator(cairo.OPERATOR_DIFFERENCE)
            cr.set_source_rgba(1.0, 0.8, 0.7, 1.0)
            cr.set_line_width(0.75)

            rings, (cx, cy) = self.frame.get_resolution_rings(
                self.view.x, self.view.y, self.view.width, self.view.height, self.settings.scale
            )
            layout = self.create_pango_layout()
            for r, d, lx, ly, start_ang, end_ang in rings:
                cr.arc(cx, cy, r, start_ang, end_ang)
                cr.stroke()
                layout.set_text(f'{d:0.2f}')
                ink, logical = layout.get_pixel_extents()
                cr.move_to(lx - logical.width / 2, ly - logical.height / 2)
                PangoCairo.show_layout(cr, layout)
                cr.fill()
            cr.restore()

    def go_back(self, full=False):
        if self.view_stack and not full:
            self.view = self.view_stack.pop()
        else:
            self.view = Box(x=1, y=1, width=self.settings.width - 2, height=self.settings.height - 2)
            self.view_stack.clear()
        self.queue_draw()
        return bool(self.view_stack)

    def colorize(self, color=False):
        self.data_loader.set_colormap(COLOR_MAPS[int(color)])
        if self.frame is not None:
            self.frame.set_colormap(COLOR_MAPS[int(color)])

    def reset_filters(self):
        if self.frame is not None:
            self.frame.adjust()

    def get_position(self, x, y):
        if not self.settings.initialized:
            return 0, 0, 0.0, 0

        ix, iy = self.screen_to_image(x, y)
        res = self.frame.image_resolution(ix, iy)
        return ix, iy, res, self.frame.data[iy, ix]

    def save_surface(self, path):
        if self.surface is not None:
            alloc = self.get_allocation()
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, alloc.width, alloc.height)
            ctx = cairo.Context(surface)

            self.paint_image(ctx, self.settings.scale)
            self.draw_profile(ctx)
            self.draw_overlay_cairo(ctx)
            self.draw_spots(ctx)
            self.draw_rings(ctx)

            surface.write_to_png(path)
            logger.info('Image saved to PNG: {}'.format(path))

    def screen_to_image(self, x, y):
        ix = int(x / self.settings.scale) + self.view.x
        iy = int(y / self.settings.scale) + self.view.y
        ix = max(1, min(ix, self.settings.width - 2))
        iy = max(1, min(iy, self.settings.height - 2))
        return ix, iy

    def set_cursor_mode(self, cursor=None):
        window = self.get_window()
        if window is None:
            return
        if cursor is None:
            window.set_cursor(None)
        else:
            window.set_cursor(Gdk.Cursor.new(cursor))
        self.queue_draw()

    def set_annotations(self, state: bool = False):
        self.settings.annotate = state
        self.queue_draw()

    def pause(self):
        self.data_loader.pause()

    def resume(self):
        self.data_loader.resume()

    def paint_image(self, cr, scale):
        cr.save()
        cr.scale(scale, scale)
        cr.translate(-self.view.x, -self.view.y)
        cr.set_source_surface(self.surface, 0, 0)
        if scale >= 1:
            cr.get_source().set_filter(cairo.FILTER_FAST)
        else:
            cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()

    def draw_profile(self, cr):
        if self.settings.profile:
            alloc = self.get_allocation()
            px = alloc.width - self.settings.profile.get_width() - 10
            py = alloc.height - self.settings.profile.get_height() - 10
            cr.save()
            cr.set_source_surface(self.settings.profile, px, py)
            cr.paint()
            cr.restore()

    def do_draw(self, cr):
        if self.surface is not None:
            alloc = self.get_allocation()
            width = min(alloc.width, alloc.height)
            self.settings.scale = float(width) / self.view.width
            self.paint_image(cr, self.settings.scale)
            self.draw_profile(cr)
            self.draw_overlay_cairo(cr)
            self.draw_spots(cr)
            self.draw_rings(cr)

    # callbacks
    def on_mouse_motion(self, widget, event):
        if self.settings.initialized:
            if event.get_state() & Gdk.ModifierType.BUTTON1_MASK and self.settings.mode == MouseMode.SELECTING:
                self.settings.mouse_box.set_end(event.x, event.y)
                self.queue_draw()
            elif event.get_state() & Gdk.ModifierType.BUTTON2_MASK and self.settings.mode == MouseMode.PANNING:
                self.settings.mouse_box.set_end(event.x, event.y)
                ox, oy, ow, oh = self.view.x, self.view.y, self.view.width, self.view.height
                nx = int(-self.settings.mouse_box.width / self.settings.scale) + ox
                ny = int(-self.settings.mouse_box.height / self.settings.scale) + oy
                nw, nh = ow, oh
                nx = min(max(0, nx), self.settings.width - nw)
                ny = min(max(0, ny), self.settings.height - nh)
                new_view = Box(x=nx, y=ny, width=nw, height=nh)
                if self.view != new_view:
                    self.view = new_view
                    self.settings.mouse_box.set_start(event.x, event.y)
                    self.queue_draw()
            elif event.get_state() & Gdk.ModifierType.BUTTON3_MASK and self.settings.mode == MouseMode.MEASURING:
                self.settings.mouse_box.set_end(event.x, event.y)
                self.queue_draw()

    def on_mouse_scroll(self, widget, event):
        if self.settings.initialized:
            if event.direction == Gdk.ScrollDirection.UP:
                self.frame.adjust(1)
            elif event.direction == Gdk.ScrollDirection.DOWN:
                self.frame.adjust(-1)

    def on_mouse_press(self, widget, event):
        if self.settings.initialized and event.button:
            self.settings.profile = None
            self.settings.mouse_box.set_start(event.x, event.y)
            self.settings.mouse_box.set_end(event.x, event.y)

            if event.button == Gdk.BUTTON_PRIMARY:
                self.set_cursor_mode(Gdk.CursorType.TCROSS)
                self.settings.mode = MouseMode.SELECTING
            elif event.button == Gdk.BUTTON_MIDDLE:
                self.view_stack.append(self.view)
                self.set_cursor_mode(Gdk.CursorType.FLEUR)
                self.settings.mode = MouseMode.PANNING
            elif event.button == Gdk.BUTTON_SECONDARY:
                self.set_cursor_mode(Gdk.CursorType.TCROSS)
                self.settings.mode = MouseMode.MEASURING

    def on_mouse_release(self, widget, event):
        if self.settings.initialized:
            if self.settings.mode == MouseMode.SELECTING:
                x0, y0 = self.screen_to_image(*self.settings.mouse_box.get_start())
                x1, y1 = self.screen_to_image(*self.settings.mouse_box.get_end())
                new_view = Box(x=x0, y=y0)
                new_view.set_end(x1, y1)
                new_view.normalize()
                if min(new_view.width, new_view.height) > 10:
                    self.view_stack.append(self.view)
                    self.view = new_view
                    self.queue_draw()
            elif self.settings.mode == MouseMode.MEASURING:
                data = self.get_line_profile(self.settings.mouse_box, 2)
                if len(data) > 4:
                    self.plot_profile(data)
                    self.queue_draw()

        self.settings.mode = None
        self.set_cursor_mode()

    def on_visibility(self, obj, state):
        if state:
            self.data_loader.resume()
        else:
            self.data_loader.pause()
