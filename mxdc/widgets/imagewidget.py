# -*- coding: UTF8 -*-
from gi.repository import GObject
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gtk

import matplotlib
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FormatStrFormatter, MaxNLocator
from matplotlib.backends.backend_cairo import FigureCanvasCairo, RendererCairo

from mxdc.libs.imageio import read_image
from mxdc.libs.imageio.utils import stretch
from mxdc.utils.science import find_peaks
from mxdc.utils.video import image_to_surface
import Queue
import cairo

import logging
import math
import numpy
import array
import os
import pickle
import sys
import threading
import time

__log_section__ = 'mxdc.imagewidget'
img_logger = logging.getLogger(__log_section__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
COLORMAPS = pickle.load(file(os.path.join(DATA_DIR, 'colormaps.data')))
_COLORNAMES = ['gist_yarg', 'gist_gray', 'hot', 'jet', 'hsv', 'Spectral',
               'Paired', 'gist_heat', 'PiYG', 'Set1', 'gist_ncar']

# Modify default colormap to add overloaded pixel effect
COLORMAPS['gist_yarg'][-1] = 0
COLORMAPS['gist_yarg'][-2] = 0
COLORMAPS['gist_yarg'][-3] = 255

# Modify default colormap to add overloaded pixel effect
COLORMAPS['gist_yarg'][0] = 255
COLORMAPS['gist_yarg'][1] = 255
COLORMAPS['gist_yarg'][2] = 255

_GAMMA_SHIFT = 3.5


def image2pixbuf(im):
    arr = array.array('B', im.tobytes())
    width, height = im.size
    return GdkPixbuf.Pixbuf.new_from_data(arr, GdkPixbuf.Colorspace.RGB, True, 8, width, height, width * 4)


def _lut(offset=0, scale=1.0, lo=0, hi=65536):
    nlo = offset + lo
    lut = scale * 254. * (numpy.arange(65536) - nlo) / (hi - nlo)
    lut[lut>254] = 254
    lut[lut<1] = 1
    lut[:2] = 0
    return lut.astype(int)


def _histogram(data, lo=0.1, hi=95, bins='auto'):
    rmin, rmax = numpy.percentile(data, (lo,hi))
    hist, edges = numpy.histogram(data, bins=bins, range=(rmin, rmax))
    return numpy.stack((edges[2:], hist[1:]), axis=1)



def _load_frame_image(filename,  offset=0, scale=1.0):
    image_info = {}
    image_obj = read_image(filename)
    image_info['header'] = image_obj.header
    image_info['data'] = image_obj.data  # numpy.transpose(numpy.asarray(image_obj.image))
    mask = (image_obj.data > 0.0) & (image_obj.data < image_obj.header['saturated_value'])

    image_info['src-image'] = image_obj.image
    lo, md, hi = numpy.percentile(image_obj.data[mask], [1., 50., 99.])
    image_info['percentiles'] = lo, md, hi
    lut = _lut(offset=offset, scale=scale, lo=lo, hi=hi)

    image_info['image'] = image_obj.image.point(lut.tolist(), 'L')
    image_info['histogram'] = _histogram(image_obj.data[mask], lo=1, hi=98, bins=255)
    return image_info


def image_loadable(filename):
    filename = os.path.abspath(filename)
    if not os.path.isdir(os.path.dirname(filename)):
        return False
    if os.path.basename(filename) in os.listdir(os.path.dirname(filename)):
        statinfo = os.stat(filename)
        if (time.time() - statinfo.st_mtime) > 1.0:
            if not os.path.isfile(filename):
                return False
            if os.access(filename, os.R_OK):
                return True
            else:
                return False
        else:
            return False
    return False


class FileLoader(GObject.GObject):
    __gsignals__ = {
        "new-image": (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        self.inbox = Queue.Queue(1000)
        self.outbox = Queue.Queue(1000)
        self._stopped = False
        self._paused = False
        self.lut_offset = 0
        self.lut_scale = 1.0

    def queue_file(self, filename):
        if not self._paused and not self._stopped:
            self.inbox.put(filename)
            img_logger.debug('Queuing for display: %s' % filename)
        else:
            self.load_file(filename)

    def load_file(self, filename):
        if image_loadable(filename):
            self.outbox.put(_load_frame_image(filename, offset=self.lut_offset, scale=self.lut_scale))
            GObject.idle_add(self.emit, 'new-image')

    def reset(self):
        while not self.inbox.empty():
            _junk = self.inbox.get()

    def start(self):
        self._stopped = False
        worker_thread = threading.Thread(target=self._run)
        worker_thread.setDaemon(True)
        worker_thread.start()

    def stop(self):
        self._stopped = True

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def _run(self):
        filename = None
        while not self._stopped:
            time.sleep(0.5)
            if self._paused:
                continue
            elif filename is None:
                filename = self.inbox.get(block=True)
                _search_t = time.time()
            elif image_loadable(filename):
                try:
                    img_info = _load_frame_image(filename,  offset=self.lut_offset, scale=self.lut_scale)
                except:
                    pass
                else:
                    self.outbox.put(img_info)
                    img_logger.debug('Loading image: %s' % filename)
                    GObject.idle_add(self.emit, 'new-image')
                    filename = None
            elif (time.time() - _search_t > 10.0) and self.inbox.qsize() > 0:
                img_logger.debug('Error loading image: %s' % filename)
                filename = None


class ImageWidget(Gtk.DrawingArea):
    __gsignals__ = {
        "image-loaded": (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    def __init__(self, size):
        GObject.GObject.__init__(self)
        self.surface = None
        self._rubber_band = False
        self._shifting = False
        self._measuring = False
        self._colorize = False
        self._palette = None
        self.image_loaded = False
        self._draw_histogram = False
        self._best_interp = GdkPixbuf.InterpType.TILES
        self._saturation_factor = 1.0
        self._canvas_is_clean = False

        self.display_gamma = 1.0
        self.scale = 1.0

        self.extents_back = []
        self.extents_forward = []
        self.extents = None
        self.set_spots()

        self.set_events(Gdk.EventMask.EXPOSURE_MASK |
                        Gdk.EventMask.LEAVE_NOTIFY_MASK |
                        Gdk.EventMask.BUTTON_PRESS_MASK |
                        Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK |
                        Gdk.EventMask.POINTER_MOTION_HINT_MASK |
                        Gdk.EventMask.VISIBILITY_NOTIFY_MASK |
                        Gdk.EventMask.SCROLL_MASK)

        self.connect('visibility-notify-event', self.on_visibility_notify)
        self.connect('unmap', self.on_unmap)
        self.connect('draw', self.on_draw)
        self.connect('motion_notify_event', self.on_mouse_motion)
        self.connect('button_press_event', self.on_mouse_press)
        self.connect('scroll-event', self.on_mouse_scroll)
        self.connect('button_release_event', self.on_mouse_release)
        self.set_size_request(size, size)
        self.set_colormap('gist_yarg')
        self.file_loader = FileLoader()
        self.file_loader.connect('new-image', self.on_image_loaded)
        self.file_loader.start()

    def set_colormap(self, colormap=None, index=None):
        if colormap is not None:
            self._colorize = True
            self._palette = COLORMAPS[colormap]
        elif index is not None:
            index = int(index)
            self._colorize = True
            self._palette = COLORMAPS[_COLORNAMES[(index % 11)]]
        else:
            self._colorize = False

    def set_cross(self, x, y):
        self.beam_x, self.beam_y = x, y

    def set_spots(self, indexed=[], unindexed=[]):
        self.indexed_spots = indexed
        self.unindexed_spots = unindexed

    def load_frame(self, filename):
        self.file_loader.load_file(filename)

    def queue_frame(self, filename):
        self.file_loader.queue_file(filename)

    def on_image_loaded(self, obj):
        self._set_cursor_mode(Gdk.CursorType.WATCH)
        self.img_info = obj.outbox.get(block=True)
        self.beam_x, self.beam_y = self.img_info['header']['beam_center']
        self.pixel_size = self.img_info['header']['pixel_size']
        self.distance = self.img_info['header']['distance']
        self.wavelength = self.img_info['header']['wavelength']
        self.gamma = self.img_info['header']['gamma']
        self.pixel_data = self.img_info['data']
        self.raw_img = self.img_info['image']
        self.filename = self.img_info['header']['filename']
        self._create_surface()
        self.queue_draw()
        self.image_loaded = True
        self.emit('image-loaded')
        self.src_image = self.img_info['src-image']
        self.histogram = self.img_info['histogram']
        self._set_cursor_mode()

    def _create_surface(self):
        if self._colorize and self.raw_img.mode in ['L', 'P']:
            self.raw_img.putpalette(self._palette)
        self.image = self.raw_img.convert('RGB')
        self.image_width, self.image_height = self.image.size

        if not self.extents:
            self.extents = (1, 1, self.image_width - 2, self.image_height - 2)
        else:
            ox, oy, ow, oh = self.extents
            nx = min(ox, self.image_width)
            ny = min(oy, self.image_height)
            nw = ow
            nh = oh
            if nx + nw > self.image_width:
                nw = self.image_width - nx
            if ny + nh > self.image_height:
                nh = self.image_height - ny
            nw = max(16, min(nh, nw))
            nh = nw
            self.extents = (nx, ny, nw, nh)

        self.surface = image_to_surface(self.image)

    def get_image_info(self):
        if not self.image_loaded:
            return {}
        return self.img_info['header']

    def _calc_bounds(self, x0, y0, x1, y1):
        x = int(min(x0, x1))
        y = int(min(y0, y1))
        w = int(abs(x0 - x1))
        h = int(abs(y0 - y1))
        return (x, y, w, h)

    def _get_intensity_line(self, x, y, x2, y2, lw=1):
        """Bresenham's line algorithm"""

        x, y = self.get_position(x, y)[:2]
        x2, y2 = self.get_position(x2, y2)[:2]

        steep = 0
        coords = []
        dx = abs(x2 - x)
        if (x2 - x) > 0:
            sx = 1
        else:
            sx = -1
        dy = abs(y2 - y)
        if (y2 - y) > 0:
            sy = 1
        else:
            sy = -1
        if dy > dx:
            steep = 1
            x, y = y, x
            dx, dy = dy, dx
            sx, sy = sy, sx
        d = (2 * dy) - dx
        for i in range(0, dx):
            if steep:
                coords.append((y, x))
            else:
                coords.append((x, y))
            while d >= 0:
                y = y + sy
                d = d - (2 * dx)
            x = x + sx
            d = d + (2 * dy)
        coords.append((x2, y2))

        data = numpy.zeros((len(coords), 3))
        n = 0
        for ix, iy in coords:
            ix = max(1, ix)
            iy = max(1, iy)
            data[n][0] = n
            val = self.pixel_data[ix - lw:ix + lw, iy - lw:iy + lw].mean()
            data[n][2] = val
            data[n][1] = self._rdist(ix, iy, coords[0][0], coords[0][1])
            n += 1
        return data[:, 1:]

    def _plot_histogram(self, data, show_axis=None, distance=True):
        def _adjust_spines(ax, spines):
            for loc, spine in ax.spines.items():
                if loc in spines:
                    spine.set_position(('outward', 10))  # outward by 10 points
                    spine.set_smart_bounds(True)
                else:
                    spine.set_color('none')  # don't draw spine

            # turn off ticks where there is no spine
            if 'left' in spines:
                ax.yaxis.set_ticks_position('left')
            else:
                # no yaxis ticks
                ax.yaxis.set_ticks([])

            if 'bottom' in spines:
                ax.xaxis.set_ticks_position('bottom')
            else:
                # no xaxis ticks
                ax.xaxis.set_ticks([])

        matplotlib.rcParams.update({'font.size': 9.5})
        figure = matplotlib.figure.Figure(frameon=False, figsize=(4, 2), dpi=72)
        plot = figure.add_subplot(111)
        plot.patch.set_alpha(0.4)
        _adjust_spines(plot, ['left'])
        figure.subplots_adjust(left=0.18, right=0.95)
        formatter = FormatStrFormatter('%g')
        plot.yaxis.set_major_formatter(formatter)
        plot.yaxis.set_major_locator(MaxNLocator(5))

        if distance:
            plot.plot(data[:, 0], data[:, 1])
        else:
            plot.vlines(data[:, 0], 0, data[:, 1])

        if distance:
            peaks = find_peaks(data[:, 0], data[:, 1], sensitivity=0.1)
            if len(peaks) > 0:
                plot.set_ylim(0, 1.1 * max([p[1] for p in peaks]))

        # Ask matplotlib to render the figure to a bitmap using the Agg backend
        plot.set_xlim(min(data[:, 0]), max(data[:, 0]))

        canvas = FigureCanvasCairo(figure)
        width, height = canvas.get_width_height()
        renderer = RendererCairo(canvas.figure.dpi)
        renderer.set_width_height(width, height)
        self.plot_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        renderer.set_ctx_from_surface(self.plot_surface)
        canvas.figure.draw(renderer)
        self._draw_histogram = True

    def img_histogram(self, widget, cr):
        data = self.img_info['histogram']
        matplotlib.rcParams.update({'font.size': 9.5})
        figure = matplotlib.figure.Figure(frameon=False, figsize=(5.5, 2), dpi=80)
        figure.subplots_adjust(left=0.03, right=0.98)
        plot = figure.add_subplot(111)
        formatter = FormatStrFormatter('%g')
        plot.yaxis.set_major_formatter(formatter)
        plot.yaxis.set_major_locator(MaxNLocator(5))
        sel = data[:, 1] > 0
        plot.plot(data[sel, 0], data[sel, 1])
        plot.set_xlim(min(data[:, 0]), max(data[:, 0]))
        plot.yaxis.set_visible(False)

        canvas = FigureCanvasCairo(figure)
        width, height = canvas.get_width_height()
        renderer = RendererCairo(canvas.figure.dpi)
        renderer.set_width_height(width, height)
        plot_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        renderer.set_ctx_from_surface(plot_surface)
        canvas.figure.draw(renderer)
        cr.set_source_surface(plot_surface, 0, 0)
        cr.paint()

    def _calc_palette(self, percent):
        frac = percent / 100.0
        cdict = {
            'red': ((0., 1., 1.), (frac, 0.9, 0.9), (1., 0., 0.)),
            'green': ((0., 1., 1.), (frac, 0.9, 0.9), (1., 0., 0.)),
            'blue': ((0., 1., 1.), (frac, 0.9, 0.9), (1., 0., 0.))
        }
        cmap = LinearSegmentedColormap('_tmp_cmap', cdict)
        a = numpy.arange(256)
        tpal = cmap(a)[:, :-1].reshape((-1, 1))
        rpal = [int(round(v[0] * 255)) for v in tpal]
        return rpal

    def draw_overlay_cairo(self, cr):
        # rubber band
        cr.set_line_width(1)
        cr.set_source_rgb(0.0, 0.5, 1.0)
        if self._rubber_band:
            x, y, w, h = self._calc_bounds(self.rubber_x0, self.rubber_y0, self.rubber_x1, self.rubber_y1)
            cr.rectangle(x, y, w, h)
            cr.stroke()

        # cross
        x, y, w, h = self.extents
        if (0 < (self.beam_x - x) < x + w) and (0 < (self.beam_y - y) < y + h):
            cx = int((self.beam_x - x) * self.scale)
            cy = int((self.beam_y - y) * self.scale)
            cr.move_to(cx - 4, cy)
            cr.line_to(cx + 4, cy)
            cr.stroke()
            cr.move_to(cx, cy - 4)
            cr.line_to(cx, cy + 4)
            cr.stroke()
        # measuring
        if self._measuring:
            cr.set_source_rgba(0.0, 0.5, 1.0, 0.5)
            cr.set_line_width(4)
            cr.move_to(self.meas_x0, self.meas_y0)
            cr.line_to(self.meas_x1, self.meas_y1)
            cr.stroke()

        # Filename
        pcontext = self.get_pango_context()
        alloc = self.get_allocation()
        font_desc = pcontext.get_font_description()
        cr.select_font_face(font_desc.get_family(), cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12)
        cr.set_line_width(0.85)
        cr.move_to(6, alloc.height - 6)
        cr.show_text(os.path.basename(self.filename))
        cr.stroke()

    def draw_spots(self, cr):
        # draw spots
        x, y, w, h = self.extents
        cr.set_line_width(0.75)
        cr.set_source_rgba(1.0, 0.0, 0.0, 0.5)
        for i, spots in enumerate([self.indexed_spots, self.unindexed_spots]):
            if i == 0:
                cr.set_source_rgba(0.1, 0.1, 0.8, 0.75)
            else:
                cr.set_source_rgba(0.8, 0.1, 0.1, 0.75)
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

    def set_contrast(self, value):
        self._palette = self._calc_palette(value)
        self._colorize = True
        self._create_surface()
        self.queue_draw()

    def set_brightness(self, value):
        # new images need to respect this so file_loader should be informed

        self.file_loader.lut_offset = value
        self.file_loader.lut_scale = 1.0
        lut = _lut(
            self.file_loader.lut_offset, self.file_loader.lut_scale,
            lo=self.img_info['percentiles'][0],
            hi=self.img_info['percentiles'][-1],
        )

        self.raw_img = self.src_image.point(lut.tolist(), 'L')
        self._create_surface()
        self._canvas_is_clean = False
        self.queue_draw()


    def colorize(self, value):
        self.set_colormap(index=value)
        self._canvas_is_clean = False
        self._create_surface()
        self.queue_draw()

    def reset_filters(self):
        self.set_colormap('gist_yarg')
        self.file_loader.lut_offset = 0
        self.file_loader.lut_scale = 1.0
        lut = _lut(
            self.file_loader.lut_offset, self.file_loader.lut_scale,
            lo=self.img_info['percentiles'][0],
            hi=self.img_info['percentiles'][-1],
        )
        self.raw_img = self.src_image.point(lut.tolist(), 'L')
        self._create_surface()
        self.queue_draw()

    def _calc_pos(self, x, y):
        Ix = int(x / self.scale) + self.extents[0]
        Iy = int(y / self.scale) + self.extents[1]
        Ix = max(1, min(Ix, self.image_width - 2))
        Iy = max(1, min(Iy, self.image_height - 2))
        return Ix, Iy

    def _res(self, x, y):
        displacement = self.pixel_size * math.sqrt((x - self.beam_x) ** 2 + (y - self.beam_y) ** 2)
        angle = 0.5 * math.atan(displacement / self.distance)
        if angle < 1e-3:
            angle = 1e-3
        return self.wavelength / (2.0 * math.sin(angle))

    def _rdist(self, x0, y0, x1, y1):
        d = math.sqrt((x0 - x1) ** 2 + (y0 - y1) ** 2) * self.pixel_size
        return d  # (self.wavelength * self.distance/d)

    def get_position(self, x, y):
        if not self.image_loaded:
            return 0, 0, 0.0, 0

        Ix, Iy = self._calc_pos(x, y)
        Res = self._res(Ix, Iy)
        return Ix, Iy, Res, self.pixel_data[Ix, Iy]

    def _set_cursor_mode(self, cursor=None):
        window = self.get_window()
        if window is None:
            return
        if cursor is None:
            window.set_cursor(None)
        else:
            window.set_cursor(Gdk.Cursor.new(cursor))
        Gtk.main_iteration()

    def _clear_extents(self):
        self.extents_back = None
        self.back_btn.set_sensitive(False)

    def on_mouse_motion(self, widget, event):
        if not self.image_loaded:
            return False

        # print event.get_state().value_names
        alloc = self.get_allocation()
        w, h = alloc.width, alloc.height
        if 'GDK_BUTTON1_MASK' in event.get_state().value_names and self._rubber_band:
            self.rubber_x1 = max(min(w - 1, event.x), 0) + 0.5
            self.rubber_y1 = max(min(h - 1, event.y), 0) + 0.5
            self.queue_draw()
        elif 'GDK_BUTTON2_MASK' in event.get_state().value_names and self._shifting:
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
        elif 'GDK_BUTTON3_MASK' in event.get_state().value_names and self._measuring:
            self.meas_x1 = int(max(min(w - 1, event.x), 0)) + 0.5
            self.meas_y1 = int(max(min(h - 1, event.y), 0)) + 0.5
            self.queue_draw()

        return False

    def on_mouse_scroll(self, widget, event):
        if not self.image_loaded:
            return False
        if event.direction == Gdk.ScrollDirection.UP:
            self.set_brightness(min(128, self.file_loader.lut_offset + 2))
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.set_brightness(max(-128, self.file_loader.lut_offset - 2))

    def on_mouse_press(self, widget, event):
        self._draw_histogram = False
        if not self.image_loaded:
            return False

        alloc = self.get_allocation()
        w, h = alloc.width, alloc.height
        if event.button == 1:
            self.rubber_x0 = max(min(w, event.x), 0) + 0.5
            self.rubber_y0 = max(min(h, event.y), 0) + 0.5
            self.rubber_x1, self.rubber_y1 = self.rubber_x0, self.rubber_y0
            self._rubber_band = True
            self._set_cursor_mode(Gdk.CursorType.TCROSS)
        elif event.button == 2:
            self._set_cursor_mode(Gdk.CursorType.FLEUR)
            self.shift_x0 = max(min(w, event.x), 0)
            self.shift_y0 = max(min(w, event.y), 0)
            self.shift_x1, self.shift_y1 = self.shift_x0, self.shift_y0
            self._shift_start_extents = self.extents
            self._shifting = True
            self._set_cursor_mode(Gdk.CursorType.FLEUR)
        elif event.button == 3:
            self.meas_x0 = int(max(min(w, event.x), 0))
            self.meas_y0 = int(max(min(h, event.y), 0))
            self.meas_x1, self.meas_y1 = self.meas_x0, self.meas_y0
            self._measuring = True
            self._set_cursor_mode(Gdk.CursorType.TCROSS)

    def on_mouse_release(self, widget, event):
        if not self.image_loaded:
            return False
        if self._rubber_band:
            self._rubber_band = False
            x0, y0 = self._calc_pos(self.rubber_x0, self.rubber_y0)
            x1, y1 = self._calc_pos(self.rubber_x1, self.rubber_y1)
            x, y, w, h = self._calc_bounds(x0, y0, x1, y1)
            if min(w, h) < 10: return
            self.extents_back.append(self.extents)
            self.extents = (x, y, w, h)
            self.queue_draw()
        elif self._measuring:
            self._measuring = False
            # prevent zero-length lines
            self._histogram_data = self._get_intensity_line(self.meas_x0, self.meas_y0,
                                                            self.meas_x1, self.meas_y1, 2)
            if len(self._histogram_data) > 4:
                self._plot_histogram(self._histogram_data, show_axis=['left', ])
                self.queue_draw()
        elif self._shifting:
            self._shifting = False
            self.extents_back.append(self._shift_start_extents)

        self._set_cursor_mode()

    def on_draw(self, widget, ctx):
        if self.surface is not None:
            alloc = self.get_allocation()
            self.scale = min(float(alloc.width) / self.extents[2], float(alloc.height) / self.extents[3])

            ctx.save()
            ctx.scale(self.scale, self.scale)
            ctx.translate(-self.extents[0], -self.extents[1])
            ctx.set_source_surface(self.surface, 0, 0)
            if self.scale >= 1.0:
                ctx.get_source().set_filter(cairo.FILTER_FAST);
            else:
                ctx.get_source().set_filter(cairo.FILTER_GOOD);
            ctx.paint()
            ctx.restore()

            if self._draw_histogram:
                px = alloc.width - self.plot_surface.get_width() - 10
                py = alloc.height - self.plot_surface.get_height() - 10
                ctx.save()
                ctx.set_source_surface(self.plot_surface, px, py)
                ctx.paint()
                ctx.restore()

            self.draw_overlay_cairo(ctx)
            self.draw_spots(ctx)
            self._canvas_is_clean = True

    def on_visibility_notify(self, obj, event):
        if event.get_state() == Gdk.VisibilityState.FULLY_OBSCURED:
            self.stopped = True
        else:
            self.stopped = False

    def on_unmap(self, obj):
        self.stopped = True


def main():
    win = Gtk.Window()
    win.connect("destroy", lambda x: Gtk.main_quit())
    win.set_border_width(6)
    win.set_title("Diffraction Image Viewer")
    myview = ImageWidget(int(Gdk.Screen.height() * 0.8))
    GObject.idle_add(myview.load_frame, '/home/michel/Work/data-processing/testins_101.img')

    hbox = Gtk.AspectFrame(ratio=1.0)
    hbox.set_shadow_type(Gtk.ShadowType.NONE)
    hbox.add(myview)
    win.add(hbox)
    win.show_all()

    if len(sys.argv) == 2:
        myview.load_frame(sys.argv[1])

    try:
        Gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()


if __name__ == '__main__':
    main()
