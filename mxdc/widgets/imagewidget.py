import logging
import math
import os
import pathlib
import threading
import time
import cv2
import cairo
import matplotlib
import numpy
from queue import Queue

from gi.repository import Gdk
from gi.repository import Gtk
from matplotlib.backends.backend_cairo import FigureCanvasCairo, RendererCairo
from matplotlib.figure import Figure

from matplotlib.ticker import FormatStrFormatter, MaxNLocator
from mxio import read_image
from mxdc.utils import cmaps, colors
from mxdc.utils.frames import line, bounding_box
from mxdc.utils.gui import color_palette

from mxdc import Signal, Object

logger = logging.getLogger('mxdc.imagewidget')

ZSCALE_MULTIPLIER = 3
MAX_ZSCALE = 12
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


class DataLoader(Object):
    class Signals:
        new_image = Signal("new-image", arg_types=())

    def __init__(self, path=None):
        super().__init__()
        self.gamma = 0
        self.dataset = None
        self.header = None
        self.stopped = False
        self.paused = False
        self.skip_count = 10  # number of frames to skip at once
        self.zscale = ZSCALE_MULTIPLIER  # Standard zscale above mean for palette maximum
        self.default_zscale = ZSCALE_MULTIPLIER
        self.scale = 1.0
        self.inbox = Queue(10000)

        self.needs_refresh = False
        self.load_next = False
        self.load_prev = False

        self.set_colormap(0)
        self.start()
        if path:
            self.open(path)

    def open(self, path):
        """
        Add data path to queue for lazy loading

        :param path: full path to data frame
        """
        self.inbox.put(path)

    def show(self, dataset):
        """
        Prepare and display externally loaded dataset

        :param dataset: dataset
        """
        self.dataset = dataset
        avg = self.dataset.header['average_intensity']
        std_dev = self.dataset.header['std_dev']
        p_lo, p_hi = numpy.percentile(self.dataset.stats_data, (1., 99.))
        self.default_zscale = ZSCALE_MULTIPLIER * (p_hi - avg) / std_dev  # default Z-scale
        self.zscale = self.default_zscale
        self.scale = avg + self.zscale * std_dev
        self.needs_refresh = True
        logger.info("Loading frame {}".format(self.dataset.header['filename']))

    def load(self, path):
        attempts = 0
        success = False
        while not success and attempts < 10:
            path_obj = pathlib.Path(path)
            if path_obj.exists() and path_obj.stat().st_ctime < time.time() - MAX_SAVE_JITTER:
                try:
                    dataset = read_image(path)
                    self.show(dataset)
                    success = True
                except (ValueError, KeyError) as err:
                    success = False
            attempts += 1
            time.sleep(0.1)

        if not success:
            logger.info("Unable to load {}".format(path))
        return success

    def set_colormap(self, index):
        self.colormap = cmap(COLORMAPS[index])

    def adjust(self, direction=None):
        prev_scale = self.scale
        if not direction:
            self.zscale = self.default_zscale
        else:
            step = direction * max(round(self.zscale / 10, 2), 0.1)
            self.zscale = min(MAX_ZSCALE, max(MIN_ZSCALE, self.zscale + step))
        self.scale = self.header['average_intensity'] + self.zscale * self.header['std_dev']
        self.needs_refresh = (prev_scale != self.scale)

    def setup(self):
        self.needs_refresh = False
        self.data = self.dataset.data
        self.header = self.dataset.header

        img = cv2.convertScaleAbs(self.data, None, 255 / self.scale, 0)
        img1 = cv2.applyColorMap(img, self.colormap)
        self.image = cv2.cvtColor(img1, cv2.COLOR_BGR2BGRA)
        self.emit('new-image')

    def next_frame(self):
        self.load_next = True

    def prev_frame(self):
        self.load_prev = True

    def start(self):
        self.stopped = False
        self.paused = False
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName(self.__class__.__name__)
        worker_thread.start()

    def stop(self):
        self.stopped = True

    def run(self):
        path = None
        while not self.stopped:

            # skip ahead a few frames
            count = 0
            while not self.inbox.empty() and count < self.skip_count:
                path = self.inbox.get()
                count += 1

            if path:
                self.load(path)
                path = None

            # Check if next_frame or prev_frame has been requested
            if self.load_next:
                self.needs_refresh = self.dataset.next_frame()
                self.load_next = False

            if self.load_prev:
                self.needs_refresh = self.dataset.prev_frame()
                self.load_prev = False

            # check if setup is needed
            if self.needs_refresh:
                self.setup()

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

        self.extents_back = []
        self.extents_forward = []
        self.extents = None
        self.select_reflections()

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

        self.data_loader = DataLoader()
        self.data_loader.connect('new-image', self.on_data_loaded)

    def select_reflections(self, reflections=None):
        if reflections is not None:
            diff = (reflections[:, 2] - self.frame_number)
            frame_sel = (diff >= 0) & (diff < 1)
            frame_reflections = reflections[frame_sel]
            sel = numpy.abs(frame_reflections[:, 4:]).sum(1) > 0
            indexed = frame_reflections[sel]
            unindexed = frame_reflections[~sel]

            self.indexed_spots = indexed
            self.unindexed_spots = unindexed
        else:
            self.indexed_spots = []
            self.unindexed_spots = []

    def open(self, filename):
        self.data_loader.open(filename)

    def show(self, frame):
        self.data_loader.show(frame)

    def on_data_loaded(self, obj):
        self.image_header = obj.header
        self.beam_x, self.beam_y = obj.header['beam_center']
        self.pixel_size = obj.header['pixel_size']
        self.distance = obj.header['distance']
        self.wavelength = obj.header['wavelength']
        self.pixel_data = obj.data.T
        self.raw_img = obj.image
        self.frame_number = obj.header['frame_number']
        self.filename = obj.header['filename']
        self.name = '{} [ {} ]'.format(obj.header['name'], self.frame_number)
        self.image_size = obj.header['detector_size']
        self.create_surface()
        self.emit('image-loaded')

    def create_surface(self):
        self.image_width, self.image_height = self.image_size
        width = min(self.image_width, self.image_height)
        if not self.extents:
            self.extents = (1, 1, width - 2, width - 2)
        else:
            ox, oy, ow, oh = self.extents
            nx = min(ox, self.image_width)
            ny = min(oy, self.image_height)
            nw = nh = max(16, min(ow, oh, self.image_width - nx, self.image_height - ny))
            self.extents = (nx, ny, nw, nh)
        self.surface = cairo.ImageSurface.create_for_data(
            self.raw_img, cairo.FORMAT_ARGB32, self.image_width, self.image_height
        )
        self.image_loaded = True
        self.queue_draw()

    def get_image_info(self):
        return self.data_loader

    def get_line_profile(self, x1, y1, x2, y2, width=1):
        x1, y1 = self.get_position(x1, y1)[:2]
        x2, y2 = self.get_position(x2, y2)[:2]
        vmin = 0
        vmax = self.image_header['saturated_value']

        coords = line(x1, y1, x2, y2)

        data = numpy.zeros((len(coords), 3))
        n = 0
        for ix, iy in coords:
            ix = max(1, ix)
            iy = max(1, iy)
            data[n][0] = n
            src = self.pixel_data[ix - width:ix + width, iy - width:iy + width]
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
        if (0 < (self.beam_x - x) < x + w) and (0 < (self.beam_y - y) < y + h):
            cx = int((self.beam_x - x) * self.scale)
            cy = int((self.beam_y - y) * self.scale)
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
        cr.show_text(self.name)
        cr.stroke()

    def draw_spots(self, cr):
        # draw spots
        x, y, w, h = self.extents
        cr.set_line_width(0.75)
        cr.set_source_rgba(0.0, 0.5, 1.0, 1.0)
        for i, spots in enumerate([self.indexed_spots, self.unindexed_spots]):
            if i == 0:
                cr.set_source_rgba(0.0, 0.5, 1.0, 0.75)
            else:
                cr.set_source_rgba(1.0, 0.5, 0.0, 0.75)
            for spot in spots:
                sx, sy = spot[:2]
                if (0 < (sx - x) < x + w) and (0 < (sy - y) < y + h):
                    cx = int((sx - x) * self.scale)
                    cy = int((sy - y) * self.scale)
                    cr.arc(cx, cy, 16 * self.scale, 0, 2.0 * numpy.pi)
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
        if color:
            self.data_loader.set_colormap(1)
        else:
            self.data_loader.set_colormap(0)
        self.data_loader.setup()

    def reset_filters(self):
        self.data_loader.adjust()

    def get_position(self, x, y):
        if not self.image_loaded:
            return 0, 0, 0.0, 0

        ix, iy = self.screen_to_image(x, y)
        Res = self.image_resolution(ix, iy)
        return ix, iy, Res, self.pixel_data[ix, iy]

    def save_surface(self, path):
        self.surface.write_to_png(path)
        logger.info('Image saved to PNG: {}'.format(path))

    def screen_to_image(self, x, y):
        ix = int(x / self.scale) + self.extents[0]
        iy = int(y / self.scale) + self.extents[1]
        ix = max(1, min(ix, self.image_width - 2))
        iy = max(1, min(iy, self.image_height - 2))
        return ix, iy

    def image_resolution(self, x, y):
        displacement = self.pixel_size * math.sqrt((x - self.beam_x) ** 2 + (y - self.beam_y) ** 2)
        if self.distance == 0.0:
            angle = math.pi / 2
        else:
            angle = 0.5 * math.atan(displacement / self.distance)
        if angle < 1e-3:
            angle = 1e-3
        return self.wavelength / (2.0 * math.sin(angle))

    def radial_distance(self, x0, y0, x1, y1):
        d = math.sqrt((x0 - x1) ** 2 + (y0 - y1) ** 2) * self.pixel_size
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
            self.data_loader.adjust(1)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.data_loader.adjust(-1)

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