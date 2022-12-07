import logging
import math
import threading
import time
from collections import deque

import cairo
import cv2
import matplotlib
import numpy
from gi.repository import Gdk, Gtk, GLib
from matplotlib.backends.backend_cairo import FigureCanvasCairo, RendererCairo
from matplotlib.figure import Figure
from matplotlib.ticker import FormatStrFormatter, MaxNLocator
from mxio import read_image

from mxdc import Signal, Object
from mxdc.utils import cmaps, colors
from mxdc.utils.frames import line, bounding_box
from mxdc.utils.gui import color_palette

logger = logging.getLogger('mxdc.imagewidget')

RESCALE_TIMEOUT = 30  # duration between images to apply auto-rescale
ZSCALE_MULTIPLIER = 3.0
MAX_ZSCALE = 12.0
MIN_ZSCALE = 0.0
COLORMAPS = ('binary', 'inferno')
MAX_SAVE_JITTER = 0.5  # maxium amount of time in seconds to wait for file to be done writing to disk


def cmap(name):
    c_map = matplotlib.cm.get_cmap(name, 256)
    rgba_data = matplotlib.cm.ScalarMappable(cmap=c_map).to_rgba(numpy.arange(0, 1.0, 1.0 / 256.0), bytes=True)
    rgba_data = rgba_data[:, 0:-1].reshape((256, 1, 3))
    return rgba_data[:, :, ::-1]


def adjust_spines(ax, spines, color):
    for loc, spine in list(ax.spines.items()):
        if loc in spines:
            spine.set_position(('outward', 10))  # outward by 10 points
            spine.set_color(color)
        else:
            spine.set_color('none')  # don't draw spine

    ax.xaxis.set_tick_params(color=color, labelcolor=color)
    ax.yaxis.set_tick_params(color=color, labelcolor=color)
    ax.patch.set_alpha(0.0)

    # turn off ticks where there is no spine
    if 'left' in spines:
        ax.yaxis.set_ticks_position('left')
    elif 'right' in spines:
        ax.yaxis.set_ticks_position('right')
    else:
        ax.yaxis.set_ticks([])

    if 'bottom' in spines:
        ax.xaxis.set_ticks_position('bottom')
    else:
        ax.xaxis.set_ticks([])


class FrameSettings:
    def __init__(self):
        self.scale: float = 1.0
        self.multiplier: float = ZSCALE_MULTIPLIER
        self.default: float = ZSCALE_MULTIPLIER

    def update(self, min_value: float, max_value: float, avg_value: float, std_dev: float):
        if std_dev > 0:
            self.default = ZSCALE_MULTIPLIER * (max_value - avg_value)/std_dev
        self.scale = avg_value + self.multiplier * std_dev

    def adjust(self, direction: int = None, avg_value: float = 0.0, std_dev: float = 0.0):
        if direction is None:
            self.multiplier = self.default
        else:
            step = direction * max(round(self.multiplier / 10, 2), 0.1)
            self.multiplier = min(MAX_ZSCALE, max(MIN_ZSCALE, self.multiplier + step))
        self.scale = avg_value + self.multiplier * std_dev


class Frame(object):
    def __init__(self, dataset, colormap: str = 'binary', rescale: bool = True):
        self.dataset = dataset
        self.header = dataset.header
        self.data = dataset.data
        self.stats_data = dataset.stats_data

        self.image = None
        self.needs_redraw = False
        self.needs_setup = False
        self.rescale = rescale
        self.needs_setup = True
        self.colormap = cmap(colormap)
        self.settings = None

        # needed for display
        self.delta_angle = self.header['delta_angle']
        self.beam_x, self.beam_y = self.header['beam_center']
        self.name = '{} [ {} ]'.format(self.header['name'], self.frame_number)
        self.image_size = self.header['detector_size']

    def __getattr__(self, key):
        if key in self.header:
            return self.header[key]
        else:
            raise AttributeError('{} does not have attribute: {}'.format(self, key))

    def setup(self, rescale: bool = False, settings: FrameSettings = None):
        if settings is not None:
            self.settings = settings
        elif self.settings is None:
            self.settings = FrameSettings()

        if rescale:
            p_lo, p_hi = numpy.percentile(self.stats_data, (5., 95.))
            self.header['percentiles'] = p_lo, p_hi
            self.settings.update(p_lo, p_hi, self.header['average_intensity'], self.header['std_dev'])

        img0 = cv2.convertScaleAbs(self.data, None, 255 / self.settings.scale, 0)
        img1 = cv2.applyColorMap(img0, self.colormap)
        self.image = cv2.cvtColor(img1, cv2.COLOR_BGR2BGRA)
        self.needs_setup = False
        self.needs_redraw = True

    def set_colormap(self, colormap: str):
        self.colormap = cmap(colormap)
        self.needs_setup = True

    def adjust(self, direction=None):
        self.settings.adjust(
            direction=direction, avg_value=self.header['average_intensity'], std_dev=self.header['std_dev']
        )
        self.needs_setup = True

    def next_frame(self):
        return self.dataset.next_frame()

    def prev_frame(self):
        return self.dataset.prev_frame()


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
        self.settings = FrameSettings()
        self.load_next = False
        self.load_prev = False
        self.set_colormap()
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
        self.frames.append(Frame(dataset))

    def load(self, path):
        attempts = 0
        success = False
        while not success and attempts < 5:
            try:
                dataset = read_image(path)
                self.show(dataset)
                success = True
            except Exception as e:
                logger.exception(e)
                success = False
            attempts += 1
            time.sleep(0.25)
        if not success:
            logger.warning("Unable to load {}".format(path))
        return success

    def set_colormap(self, name: str = 'binary'):
        self.colormap = name

    def set_current_frame(self, frame):
        self.cur_frame = frame

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
            # Setup any frames in the deque and add them to the display queue
            if not self.paused:
                rescale = (time.time() - last_update > RESCALE_TIMEOUT)
                if len(self.frames):
                    frame = self.frames.popleft()
                    frame.set_colormap(self.colormap)
                    frame.setup(settings=self.settings, rescale=rescale)
                    self.outbox.append(frame)
                    last_update = time.time()
                if self.cur_frame:
                    try:
                        success = False
                        if self.load_next:
                            success = self.cur_frame.next_frame()
                        elif self.load_prev:
                            success = self.cur_frame.prev_frame()
                        if success:
                            rescale = (time.time() - last_update > RESCALE_TIMEOUT)
                            frame = Frame(self.cur_frame.dataset, colormap=self.colormap)
                            frame.setup(settings=self.settings, rescale=rescale)
                            self.outbox.append(frame)
                            last_update = time.time()
                    except Exception as e:
                        logger.exception(e)
                self.load_next = self.load_prev = False

                # load any images from specified paths in the inbox
                if len(self.inbox):
                    path = self.inbox.popleft()
                    self.load(path)

            time.sleep(0.05)


class ImageWidget(Gtk.DrawingArea):
    image_loaded = Signal("image-loaded", arg_types=())

    def __init__(self, size):
        super().__init__()
        self.surface = None
        self.is_rubber_banding = False
        self.is_shifting = False
        self.is_measuring = False
        self.pseudocolor = True
        self.image_loaded = False
        self.show_histogram = False
        self._canvas_is_clean = False

        self.display_gamma = 1.0
        self.gamma = 0
        self.scale = 1.0
        self.frame = None
        self.all_spots = None
        self.frame_spots = None
        self.extents_back = []
        self.extents_forward = []
        self.extents = None

        self.set_events(
            Gdk.EventMask.EXPOSURE_MASK |
            Gdk.EventMask.LEAVE_NOTIFY_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.POINTER_MOTION_HINT_MASK |
            Gdk.EventMask.VISIBILITY_NOTIFY_MASK | Gdk.EventMask.SCROLL_MASK
        )

        self.connect('visibility-notify-event', self.on_visibility_notify)
        self.connect('unmap', self.on_unmap)
        self.connect('motion-notify-event', self.on_mouse_motion)
        self.connect('button_press_event', self.on_mouse_press)
        self.connect('scroll-event', self.on_mouse_scroll)
        self.connect('button_release_event', self.on_mouse_release)
        self.set_size_request(size, size)
        self.palettes = {
            True: color_palette(cmaps.inferno),
            False: color_palette(cmaps.binary)
        }
        self.inbox = deque(maxlen=5)
        self.data_loader = DataLoader(self.inbox)
        display_thread = threading.Thread(target=self.frame_monitor, daemon=True, name=self.__class__.__name__ + ':Display')
        display_thread.start()

    def select_spots(self):
        if self.all_spots is not None and self.frame is not None:
            sel = (self.all_spots[:, 2] >= self.frame.frame_number - 5)
            sel &= (self.all_spots[:, 2] <= self.frame.frame_number + 5)
            self.frame_spots = self.all_spots[sel]
        else:
            self.frame_spots = None

    def frame_monitor(self):
        while True:
            if self.frame is not None:
                if self.frame.needs_setup:
                    self.frame.setup()
                if self.frame.needs_redraw:
                    self.create_surface()
                    GLib.idle_add(self.redraw)
            if len(self.inbox):
                self.frame = self.inbox.popleft()
                self.select_spots()
                self.data_loader.set_current_frame(self.frame)
            time.sleep(0.01)

    def create_surface(self, full=False):
        self.image_width, self.image_height = self.frame.image_size
        width = min(self.image_width, self.image_height)
        if not self.extents or full:
            self.extents = (1, 1, width - 2, width - 2)
        else:
            ox, oy, ow, oh = self.extents
            nx = min(ox, self.image_width)
            ny = min(oy, self.image_height)
            nw = nh = max(16, min(ow, oh, self.image_width - nx, self.image_height - ny))
            self.extents = (nx, ny, nw, nh)
        self.surface = cairo.ImageSurface.create_for_data(
            self.frame.image, cairo.FORMAT_ARGB32, self.image_width, self.image_height
        )

    def redraw(self):
        self.queue_draw()
        self.emit('image-loaded')
        self.image_loaded = True
        self.frame.needs_redraw = False

    def set_reflections(self, reflections=None):
        self.all_spots = reflections
        self.select_spots()

    def open(self, filename):
        self.data_loader.open(filename)

    def show_frame(self, frame):
        return self.data_loader.show(frame)

    def load_next(self):
        return self.data_loader.next_frame()

    def load_prev(self):
        return self.data_loader.prev_frame()

    def get_image_info(self):
        return self.frame

    def get_line_profile(self, x1, y1, x2, y2, width=1):
        x1, y1 = self.get_position(x1, y1)[:2]
        x2, y2 = self.get_position(x2, y2)[:2]
        vmin = 0
        vmax = self.frame.saturated_value

        coords = line(x1, y1, x2, y2)

        data = numpy.zeros((len(coords), 3))
        n = 0
        for ix, iy in coords:
            ix = max(1, ix)
            iy = max(1, iy)
            data[n][0] = n
            src = self.frame.data[iy - width:iy + width, ix - width:ix + width, ]
            sel = (src > vmin) & (src < vmax)
            if sel.sum():
                val = src[sel].mean()
            else:
                val = numpy.nan
            data[n][2] = val
            data[n][1] = self.radial_distance(ix, iy, coords[0][0], coords[0][1])
            n += 1
        return data[:, 1:]

    def make_histogram(self, data, show_axis=None, distance=True):
        color = colors.Category.CAT20C[0]
        matplotlib.rcParams.update({'font.size': 9.5})
        figure = Figure(frameon=False, figsize=(4, 2), dpi=72, edgecolor=color)
        specs = matplotlib.gridspec.GridSpec(ncols=8, nrows=1, figure=figure)
        plot = figure.add_subplot(specs[0,1:7])
        plot.patch.set_alpha(1.0)
        adjust_spines(plot, ['left'], color)
        formatter = FormatStrFormatter('%g')
        plot.yaxis.set_major_formatter(formatter)
        plot.yaxis.set_major_locator(MaxNLocator(5))

        if distance:
            plot.plot(data[:, 0], data[:, 1], lw=0.75)
        else:
            plot.vlines(data[:, 0], 0, data[:, 1])

        plot.set_xlim(min(data[:, 0]), max(data[:, 0]))

        # Ask matplotlib to render the figure to a bitmap using the Agg backend
        canvas = FigureCanvasCairo(figure)
        width, height = canvas.get_width_height()
        renderer = RendererCairo(canvas.figure.dpi)
        renderer.set_width_height(width, height)
        self.plot_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        renderer.set_ctx_from_surface(self.plot_surface)
        canvas.figure.draw(renderer)
        self.show_histogram = True

    def draw_overlay_cairo(self, cr):
        # rubber band
        cr.set_line_width(2)
        cr.set_source_rgba(0.0, 0.5, 1.0, 1.0)
        if self.is_rubber_banding:
            x, y, w, h = bounding_box(self.rubber_x0, self.rubber_y0, self.rubber_x1, self.rubber_y1)
            cr.rectangle(x, y, w, h)
            cr.stroke()

        # cross
        x, y, w, h = self.extents
        radius = 16 * self.scale
        if (0 < (self.frame.beam_x - x) < x + w) and (0 < (self.frame.beam_y - y) < y + h):
            cx = int((self.frame.beam_x - x) * self.scale)
            cy = int((self.frame.beam_y - y) * self.scale)
            cr.move_to(cx - radius, cy)
            cr.line_to(cx + radius, cy)
            cr.stroke()
            cr.move_to(cx, cy - radius)
            cr.line_to(cx, cy + radius)
            cr.stroke()
            cr.arc(cx, cy, radius / 2, 0, 2.0 * numpy.pi)

        # measuring
        if self.is_measuring:
            cr.set_line_width(2)
            cr.move_to(self.meas_x0, self.meas_y0)
            cr.line_to(self.meas_x1, self.meas_y1)
            cr.stroke()

        # Filename
        pcontext = self.get_pango_context()
        alloc = self.get_allocation()
        font_desc = pcontext.get_font_description()
        cr.select_font_face(font_desc.get_family(), cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11)
        cr.move_to(6, alloc.height - 6)
        cr.show_text(self.frame.name)
        cr.stroke()

    def draw_spots(self, cr):
        # draw spots
        if self.frame_spots is not None:
            x, y, w, h = self.extents
            cr.set_line_width(0.75)

            for spot in self.frame_spots:
                sx, sy, sn, st = spot
                if spot[3] == 0:
                    cr.set_source_rgba(1.0, 0.0, 0.0, 1.0)
                else:
                    cr.set_source_rgba(0.0, 0.5, 1.0, 1.0)
                if (0 < (sx - x) < x + w) and (0 < (sy - y) < y + h):
                    cx = int((sx - x) * self.scale)
                    cy = int((sy - y) * self.scale)
                    cr.arc(cx, cy, 12 * self.scale, 0, 2.0 * numpy.pi)
                    cr.stroke()

    def go_back(self, full=False):
        if len(self.extents_back) > 0 and not full:
            self.extents = self.extents_back.pop()
        else:
            self.extents = (1, 1, self.image_width - 2, self.image_height - 2)
            self.extents_back = []
        self.queue_draw()
        return len(self.extents_back) > 0

    def colorize(self, color=False):
        self.data_loader.set_colormap(COLORMAPS[int(color)])
        if self.frame is not None:
            self.frame.set_colormap(COLORMAPS[int(color)])

    def reset_filters(self):
        if self.frame is not None:
            self.frame.adjust()

    def get_position(self, x, y):
        if not self.image_loaded:
            return 0, 0, 0.0, 0

        ix, iy = self.screen_to_image(x, y)
        Res = self.image_resolution(ix, iy)
        return ix, iy, Res, self.frame.data[iy, ix]

    def save_surface(self, path):

        if self.surface is not None:
            alloc = self.get_allocation()
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, alloc.width, alloc.height)
            ctx = cairo.Context(surface)

            ctx.save()
            ctx.scale(self.scale, self.scale)
            ctx.translate(-self.extents[0], -self.extents[1])
            ctx.set_source_surface(self.surface, 0, 0)
            if self.scale >= 1:
                ctx.get_source().set_filter(cairo.FILTER_FAST)
            else:
                ctx.get_source().set_filter(cairo.FILTER_BEST)
            ctx.paint()
            ctx.restore()

            if self.show_histogram:
                px = alloc.width - self.plot_surface.get_width() - 10
                py = alloc.height - self.plot_surface.get_height() - 10
                ctx.save()
                ctx.set_source_surface(self.plot_surface, px, py)
                ctx.paint()
                ctx.restore()

            self.draw_overlay_cairo(ctx)
            self.draw_spots(ctx)

            surface.write_to_png(path)
            logger.info('Image saved to PNG: {}'.format(path))

    def screen_to_image(self, x, y):
        ix = int(x / self.scale) + self.extents[0]
        iy = int(y / self.scale) + self.extents[1]
        ix = max(1, min(ix, self.image_width - 2))
        iy = max(1, min(iy, self.image_height - 2))
        return ix, iy

    def image_resolution(self, x, y):
        displacement = self.frame.pixel_size * math.sqrt((x - self.frame.beam_x) ** 2 + (y - self.frame.beam_y) ** 2)
        if self.frame.distance == 0.0:
            angle = math.pi / 2
        else:
            angle = 0.5 * math.atan(displacement / self.frame.distance)
        if angle < 1e-3:
            angle = 1e-3
        return self.frame.wavelength / (2.0 * math.sin(angle))

    def radial_distance(self, x0, y0, x1, y1):
        d = math.sqrt((x0 - x1) ** 2 + (y0 - y1) ** 2) * self.frame.pixel_size
        return d  # (self.wavelength * self.distance/d)

    def set_cursor_mode(self, cursor=None):
        window = self.get_window()
        if window is None:
            return
        if cursor is None:
            window.set_cursor(None)
        else:
            window.set_cursor(Gdk.Cursor.new(cursor))
        Gtk.main_iteration()

    def pause(self):
        self.data_loader.pause()

    def resume(self):
        self.data_loader.resume()

    # callbacks
    def on_mouse_motion(self, widget, event):
        if not self.image_loaded:
            return False

        # print event.get_state().value_names
        alloc = self.get_allocation()
        w, h = alloc.width, alloc.height
        if 'GDK_BUTTON1_MASK' in event.get_state().value_names and self.is_rubber_banding:
            self.rubber_x1 = max(min(w - 1, event.x), 0) + 0.5
            self.rubber_y1 = max(min(h - 1, event.y), 0) + 0.5
            self.queue_draw()
        elif 'GDK_BUTTON2_MASK' in event.get_state().value_names and self.is_shifting:
            self.shift_x1 = event.x
            self.shift_y1 = event.y
            ox, oy, ow, oh = self.extents
            nx = int((self.shift_x0 - self.shift_x1) / self.scale) + ox
            ny = int((self.shift_y0 - self.shift_y1) / self.scale) + oy
            nw = ow
            nh = oh
            nx = max(0, nx)
            ny = max(0, ny)
            if nx + nw > self.image_width:
                nx = self.image_width - nw
            if ny + nh > self.image_height:
                ny = self.image_height - nh
            if self.extents != (nx, ny, nw, nh):
                self.extents = (nx, ny, nw, nh)
                self.shift_x0 = self.shift_x1
                self.shift_y0 = self.shift_y1
                self.queue_draw()
        elif 'GDK_BUTTON3_MASK' in event.get_state().value_names and self.is_measuring:
            self.meas_x1 = int(max(min(w - 1, event.x), 0)) + 0.5
            self.meas_y1 = int(max(min(h - 1, event.y), 0)) + 0.5
            self.queue_draw()

        return False

    def on_mouse_scroll(self, widget, event):
        if not self.image_loaded:
            return False
        if event.direction == Gdk.ScrollDirection.UP:
            self.frame.adjust(1)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.frame.adjust(-1)

    def on_mouse_press(self, widget, event):
        self.show_histogram = False
        if not self.image_loaded:
            return False

        alloc = self.get_allocation()
        w, h = alloc.width, alloc.height
        if event.button == 1:
            self.rubber_x0 = max(min(w, event.x), 0) + 0.5
            self.rubber_y0 = max(min(h, event.y), 0) + 0.5
            self.rubber_x1, self.rubber_y1 = self.rubber_x0, self.rubber_y0
            self.is_rubber_banding = True
            self.set_cursor_mode(Gdk.CursorType.TCROSS)
        elif event.button == 2:
            self.set_cursor_mode(Gdk.CursorType.FLEUR)
            self.shift_x0 = max(min(w, event.x), 0)
            self.shift_y0 = max(min(w, event.y), 0)
            self.shift_x1, self.shift_y1 = self.shift_x0, self.shift_y0
            self._shift_start_extents = self.extents
            self.is_shifting = True
            self.set_cursor_mode(Gdk.CursorType.FLEUR)
        elif event.button == 3:
            self.meas_x0 = int(max(min(w, event.x), 0))
            self.meas_y0 = int(max(min(h, event.y), 0))
            self.meas_x1, self.meas_y1 = self.meas_x0, self.meas_y0
            self.is_measuring = True
            self.set_cursor_mode(Gdk.CursorType.TCROSS)

    def on_mouse_release(self, widget, event):
        if not self.image_loaded:
            return False
        if self.is_rubber_banding:
            self.is_rubber_banding = False
            x0, y0 = self.screen_to_image(self.rubber_x0, self.rubber_y0)
            x1, y1 = self.screen_to_image(self.rubber_x1, self.rubber_y1)
            x, y, w, h = bounding_box(x0, y0, x1, y1)
            if min(w, h) < 10: return
            self.extents_back.append(self.extents)
            self.extents = (x, y, w, h)
            self.queue_draw()
        elif self.is_measuring:
            self.is_measuring = False
            # prevent zero-length lines
            self.histogram_data = self.get_line_profile(self.meas_x0, self.meas_y0, self.meas_x1, self.meas_y1, 2)
            if len(self.histogram_data) > 4:
                self.make_histogram(self.histogram_data, show_axis=['left', ])
                self.queue_draw()
        elif self.is_shifting:
            self.is_shifting = False
            self.extents_back.append(self._shift_start_extents)

        self.set_cursor_mode()

    def do_draw(self, cr):
        if self.surface is not None:
            alloc = self.get_allocation()
            width = min(alloc.width, alloc.height)
            self.scale = float(width) / self.extents[2]

            cr.save()
            cr.scale(self.scale, self.scale)
            cr.translate(-self.extents[0], -self.extents[1])
            cr.set_source_surface(self.surface, 0, 0)
            if self.scale >= 1:
                cr.get_source().set_filter(cairo.FILTER_FAST)
            else:
                cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint()
            cr.restore()

            if self.show_histogram:
                px = alloc.width - self.plot_surface.get_width() - 10
                py = alloc.height - self.plot_surface.get_height() - 10
                cr.save()
                cr.set_source_surface(self.plot_surface, px, py)
                cr.paint()
                cr.restore()

            self.draw_overlay_cairo(cr)
            self.draw_spots(cr)
            self._canvas_is_clean = True

    def on_visibility_notify(self, obj, event):
        if event.get_state() == Gdk.VisibilityState.FULLY_OBSCURED:
            self.stopped = True
        else:
            self.stopped = False

    def on_unmap(self, obj):
        self.stopped = True