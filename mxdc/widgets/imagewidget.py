import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Union

import cairo
import gi
import matplotlib
import numpy
from mxio import read_image

gi.require_version('Gtk', '3.0')
gi.require_version('PangoCairo', "1.0")

from gi.repository import Gdk, Gtk, GLib, PangoCairo
from matplotlib.backends.backend_cairo import FigureCanvasCairo, RendererCairo
from matplotlib.figure import Figure
from matplotlib.ticker import FormatStrFormatter, MaxNLocator

from mxdc.utils.images import Box
from mxdc import Signal, Object
from mxdc.utils import cmaps, colors, images
from mxdc.utils.gui import color_palette

logger = logging.getLogger('image-widget')

RESCALE_TIMEOUT = 10  # duration between images to apply auto-rescale


class DataLoader:
    #class Signals:
    #    new_image = Signal("new-image", arg_types=())

    def __init__(self, view_queue: deque):
        super().__init__()

        self.frame: Union[images.Frame, None] = None
        self.pending_datasets = deque(maxlen=2)
        self.pending_files = deque(maxlen=2)
        self.view_queue = view_queue

        self.load_next = False
        self.load_prev = False
        self.load_number = None
        self.stopped = False
        self.paused = False
        self.color_scheme = 'binary'
        self.start()

    def open_path(self, path):
        """
        Add data path to queue for lazy loading

        :param path: full path to data frame
        """
        self.pending_files.append(path)

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def show_from_dataset(self, dataset):
        """
        Prepare and display externally loaded dataset

        :param dataset: dataset
        """
        self.pending_datasets.append(dataset)

    def set_colormap(self, name: str = 'binary'):
        self.color_scheme = name

    def set_frame(self, frame):
        self.frame = frame

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
        last_display_time = 0
        while not self.stopped:
            time.sleep(0.01)
            if self.paused:
                continue

            try:
                if len(self.pending_files):
                    # Load and set up the next pending file name and add frame to display queue
                    path = self.pending_files.popleft()
                    dataset = read_image(path)
                    frame = images.Frame(dataset=dataset, color_scheme=self.color_scheme)
                    self.view_queue.append(frame)
                    last_display_time = time.time()

                elif len(self.pending_datasets):
                    # Set up the next pending dataset and add frame to display queue
                    dataset = self.pending_datasets.popleft()
                    settings = None
                    if self.frame and time.time() - last_display_time > 10:
                        settings = self.frame.settings
                    frame = images.Frame(dataset=dataset, color_scheme=self.color_scheme, settings=settings)
                    self.view_queue.append(frame)
                    last_display_time = time.time()

                if self.frame:
                    success = False
                    if self.load_next:
                        success = self.frame.next_frame()
                    elif self.load_prev:
                        success = self.frame.prev_frame()
                    elif self.load_number:
                        success = self.frame.load_frame(self.load_number)
                        self.load_number = None
                    if success:
                        frame = images.Frame(
                            dataset=self.frame.dataset, color_scheme=self.color_scheme, settings=self.frame.settings
                        )
                        self.view_queue.append(frame)

                self.load_next = self.load_prev = False
            except IOError:
                logger.exception("Unable to load frame")


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


class ImageWidget(Gtk.DrawingArea):
    image_loaded = Signal("image-loaded", arg_types=())

    def __init__(self, size):
        super().__init__()

        self.settings = ImageSettings()
        self.frame = None
        self.surface = None
        self.spots = images.Spots()  # used for reflections
        self.view = images.Box()  # the rectangle region of the image to display
        self.view_stack = deque()  # view box history for undoing zoom
        self.display_queue = deque(maxlen=5)  # images.Frames waiting to be displayed

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

        self.data_loader = DataLoader(self.display_queue)
        display_thread = threading.Thread(
            target=self.frame_monitor, daemon=True, name=self.__class__.__name__ + ':Display'
        )
        display_thread.start()

    def frame_monitor(self):
        while True:
            if self.frame is not None:
                self.frame.setup()
                if self.frame.redraw:
                    self.create_surface()
                    GLib.idle_add(self.redraw)
            if len(self.display_queue):
                self.frame = self.display_queue.popleft()
                self.spots.select(self.frame.index)
                self.data_loader.set_frame(self.frame)
            time.sleep(0.01)

    def create_surface(self, full=False):
        self.settings.width, self.settings.height = self.frame.size
        width = min(self.settings.width, self.settings.height)
        if not self.view.width or full:
            self.view = images.Box(x=0, y=0, width=width, height=width)
        else:
            x = min(self.view.x, self.settings.width)
            y = min(self.view.y, self.settings.height)
            w = h = max(16, min(self.view.width, self.view.height, self.settings.width - x, self.settings.height - y))
            self.view = images.Box(x=x, y=y, width=w, height=h)
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

    def open_path(self, filename):
        self.data_loader.open_path(filename)

    def show_frame(self, dataset):
        return self.data_loader.show_from_dataset(dataset)

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

        coords = images.bressenham_line(x1, y1, x2, y2)
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
            self.view = images.Box(x=1, y=1, width=self.settings.width - 2, height=self.settings.height - 2)
            self.view_stack.clear()
        self.queue_draw()
        return bool(self.view_stack)

    def colorize(self, color=False):
        self.data_loader.set_colormap(images.COLOR_MAPS[int(color)])
        if self.frame is not None:
            self.frame.set_colormap(images.COLOR_MAPS[int(color)])

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
                new_view = images.Box(x=nx, y=ny, width=nw, height=nh)
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
                new_view = images.Box(x=x0, y=y0)
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
