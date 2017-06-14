# -*- coding: UTF8 -*-
from bcm.libs.imageio import read_image
from bcm.libs.imageio.utils import stretch
from bcm.utils.science import find_peaks
from bcm.utils.decorators import async
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FormatStrFormatter, MaxNLocator
import Queue
import cairo
import gc
import gobject
import gtk
import logging
import math
import matplotlib.backends.backend_agg
import numpy
import os
import pango
import pickle
import sys
import threading
import time

__log_section__ = 'mxdc.imagewidget'
img_logger = logging.getLogger(__log_section__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data') 
COLORMAPS = pickle.load(file(os.path.join(DATA_DIR, 'colormaps.data')))
_COLORNAMES = ['gist_yarg','gist_gray','hot','jet','hsv','Spectral',
                     'Paired','gist_heat','PiYG','Set1','gist_ncar']

# Modify default colormap to add overloaded pixel effect
COLORMAPS['gist_yarg'][-1] = 0
COLORMAPS['gist_yarg'][-2] = 0
COLORMAPS['gist_yarg'][-3] = 255

# Modify default colormap to add overloaded pixel effect
#COLORMAPS['gist_yarg'][0] = 0
#COLORMAPS['gist_yarg'][1] = 0
#COLORMAPS['gist_yarg'][2] = 200

_GAMMA_SHIFT = 3.5        

_BUSY_CURSOR_BITS_ = "\
\x00\x00\x00\x00\x00\x00\x00\x00\x04\x00\x00\x00\
\x0c\x00\x00\x00\x1c\x00\x00\x00\x3c\x00\x00\x00\
\x7c\x00\x00\x00\xfc\x00\x00\x00\xfc\x01\x00\x00\
\xfc\x3b\x00\x00\x7c\x38\x00\x00\x6c\x54\x00\x00\
\xc4\xdc\x00\x00\xc0\x44\x00\x00\x80\x39\x00\x00\
\x80\x39\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\
\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\
\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\
\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\
\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\
\x00\x00\x00\x00\x00\x00\x00\x00"

_c_pix = gtk.gdk.bitmap_create_from_data(None, _BUSY_CURSOR_BITS_, 32, 32)
_c_color = gtk.gdk.Color()
LEFT_PTR_WATCH=gtk.gdk.Cursor(_c_pix, _c_pix, _c_color, _c_color, 2, 2)

def _load_frame_image(filename, gamma_offset = 0.0):
    image_info = {}
    image_obj = read_image(filename)
    image_info['header'] = image_obj.header
    image_info['data'] = numpy.transpose(numpy.asarray(image_obj.image)) #image_obj.image.load()
    hist = image_obj.image.histogram()
        
    disp_gamma = image_info['header']['gamma'] * numpy.exp(-gamma_offset + _GAMMA_SHIFT)/30.0
    image_info['src-image'] =  image_obj.image
    img_min, img_max =  image_obj.image.getextrema()
    lut = stretch(disp_gamma)
    
    image_info['image'] = image_obj.image.point(lut.tolist(), 'L')
    idx = range(len(hist))
    x = numpy.linspace(img_min, img_max, len(hist))
    l = 2
    r = len(hist)-1
    image_info['histogram'] = numpy.array(zip(idx[l:r],x[l:r],hist[l:r]))
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


class FileLoader(gobject.GObject):
    __gsignals__ =  { 
        "new-image": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, []),
    }

    def __init__(self):
        gobject.GObject.__init__(self)
        self.next_file = None
        self.outbox = Queue.Queue(1000)
        self._stopped = False
        self._paused = False
        self.gamma_offset = 0.0
        
    def queue_file(self, filename):
        if not self._paused and not self._stopped:
            self.next_file = filename
            img_logger.debug('Queuing for display: %s' % filename)
        else:
            self.load_file(filename)
    
    def load_file(self, filename):
        if image_loadable(filename):
            self.outbox.put( _load_frame_image(filename, self.gamma_offset))
            gobject.idle_add(self.emit, 'new-image')
        
    def reset(self):
        self.next_file = None
    
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
        _search_t = time.time()
        while not self._stopped:
            time.sleep(1.0)
            if self._paused:
                continue
            if not filename:
                filename = self.next_file
                self.next_file = None
                _search_t = time.time()
            if filename and image_loadable(filename):
                try:
                    img_info = _load_frame_image(filename, self.gamma_offset)
                except:
                    pass
                else:
                    self.outbox.put(img_info)
                    img_logger.debug('Loading image: %s' % filename)
                    gobject.idle_add(self.emit, 'new-image')
                    filename = None
            if filename and (time.time()-_search_t > 10.0):
                img_logger.debug('Error loading image: %s' % filename)
                filename = None


class ImageWidget(gtk.DrawingArea):
    __gsignals__ =  { 
        "image-loaded": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, []),
    }
    def __init__(self, size):
        gtk.DrawingArea.__init__(self)
        self.pixbuf = None
        self._rubber_band=False
        self._shifting=False
        self._measuring=False
        self._colorize = False
        self._palette = None
        self.image_loaded = False
        self._draw_histogram = False
        self._best_interp = gtk.gdk.INTERP_TILES
        self._saturation_factor = 1.0
        self._canvas_is_clean = False

        self.display_gamma = 1.0
        self.scale = 1.0

        self.extents_back = []
        self.extents_forward = []
        self.extents = None
        self.set_spots()
        
        self.set_events(gtk.gdk.EXPOSURE_MASK |
                gtk.gdk.LEAVE_NOTIFY_MASK |
                gtk.gdk.BUTTON_PRESS_MASK |
                gtk.gdk.BUTTON_RELEASE_MASK |
                gtk.gdk.POINTER_MOTION_MASK |
                gtk.gdk.POINTER_MOTION_HINT_MASK|
                gtk.gdk.VISIBILITY_NOTIFY_MASK|
                gtk.gdk.SCROLL_MASK)  

        self.connect('visibility-notify-event', self.on_visibility_notify)
        self.connect('unmap', self.on_unmap)
        self.connect('expose_event',self.on_expose)
        self.connect('realize', self.on_realized)
        self.connect('configure-event', self.on_configure)        
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
            index =  int(index)
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
        self._set_cursor_mode(gtk.gdk.WATCH)
        self.img_info = obj.outbox.get(block=True)
        self.beam_x, self.beam_y = self.img_info['header']['beam_center']
        self.pixel_size = self.img_info['header']['pixel_size']
        self.distance = self.img_info['header']['distance']
        self.wavelength = self.img_info['header']['wavelength']
        self.gamma = self.img_info['header']['gamma']
        self.pixel_data = self.img_info['data']
        self.raw_img = self.img_info['image']
        self.filename = self.img_info['header']['filename']
        self._create_pixbuf()
        self.queue_draw()
        self.image_loaded = True
        self.emit('image-loaded')
        self.src_image = self.img_info['src-image']
        self.histogram = self.img_info['histogram']
        #self._plot_histogram(self.histogram, show_axis=['xzero',], distance=False)
        gc.collect()
        self._set_cursor_mode()        
    
    def _create_pixbuf(self):
        gc.collect()
        if self._colorize and self.raw_img.mode in ['L','P']:
            self.raw_img.putpalette(self._palette)
        self.image = self.raw_img.convert('RGB')
        self.image_width, self.image_height = self.image.size
        if self.extents is None:
            self.extents = (0,0, self.image_width, self.image_height)
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
        self.pixbuf =  gtk.gdk.pixbuf_new_from_data(self.image.tobytes(),
                                                    gtk.gdk.COLORSPACE_RGB, 
                                                    False, 8, 
                                                    self.image_width, 
                                                    self.image_height, 
                                                    3 * self.image_width)
    
    def get_image_info(self):
        if not self.image_loaded:
            return {}
        return self.img_info['header']
       
    def _calc_bounds(self, x0, y0, x1, y1):
        x = int(min(x0, x1))
        y = int(min(y0, y1))
        w = int(abs(x0 - x1))
        h = int(abs(y0 - y1))
        return (x,y,w,h)
          
    def _get_intensity_line(self, x,y,x2,y2, lw=1):
        """Bresenham's line algorithm"""
        
        x, y, res0, val0 = self.get_position(x, y)
        x2, y2, res1, val1 = self.get_position(x2, y2)
        
        steep = 0
        coords = []
        dx = abs(x2 - x)
        if (x2 - x) > 0: sx = 1
        else: sx = -1
        dy = abs(y2 - y)
        if (y2 - y) > 0: sy = 1
        else: sy = -1
        if dy > dx:
            steep = 1
            x,y = y,x
            dx,dy = dy,dx
            sx,sy = sy,sx
        d = (2 * dy) - dx
        for i in range(0,dx):
            if steep: coords.append((y,x))
            else: coords.append((x,y))
            while d >= 0:
                y = y + sy
                d = d - (2 * dx)
            x = x + sx
            d = d + (2 * dy)
        coords.append((x2,y2))
   
        data = numpy.zeros((len(coords),3))
        n = 0
        for ix, iy in coords:
            ix = max(1, ix)
            iy = max(1, iy)
            data[n][0] = n
            val = self.pixel_data[ix-lw:ix+lw, iy-lw:iy+lw].mean()
            data[n][2] = val
            data[n][1] = self._rdist(ix, iy, coords[0][0], coords[0][1])
            n += 1
        return data

    def _plot_histogram(self, data, show_axis=None, distance=True):
        def _adjust_spines(ax,spines):
            for loc, spine in ax.spines.items():
                if loc in spines:
                    spine.set_position(('outward',10)) # outward by 10 points
                    spine.set_smart_bounds(True)
                else:
                    spine.set_color('none') # don't draw spine
        
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

        old_fontsize = matplotlib.rcParams['font.size']
        matplotlib.rcParams.update({'font.size': 8.5})
        figure = matplotlib.figure.Figure(frameon=False,figsize=(4, 2), dpi=80, facecolor='w' )
        plot = figure.add_subplot(111)
        _adjust_spines(plot, ['left'])
        figure.subplots_adjust(left=0.18, right=0.95)
        formatter = FormatStrFormatter('%g')
        plot.yaxis.set_major_formatter(formatter)
        plot.yaxis.set_major_locator(MaxNLocator(5))

        if distance:
            plot.plot(data[:,1], data[:,2])
        else:
            plot.vlines(data[:,1], 0, data[:,2])

        if distance:
            peaks = find_peaks(data[:,1], data[:,2], sensitivity=0.05)            
            if len(peaks) > 1:
                d1 = peaks[1][0] - peaks[0][0]
                y1 = max(peaks[0][1], peaks[1][1])
                r1 = (self.wavelength * self.distance/d1)
                x1 = (peaks[1][0] + peaks[0][0])/2
                plot.text((peaks[1][0]+peaks[0][0])/2, y1, '%0.0f A' % r1,
                          horizontalalignment='center',
                          verticalalignment='bottom',
                          color='black', rotation=90)        
            
            if len(peaks) > 2:
                d2 = peaks[2][0] - peaks[1][0]
                r2 = (self.wavelength * self.distance/d2)
                y2 = max(peaks[1][1], peaks[2][1])
                x2 = (peaks[2][0] + peaks[1][0])/2
                plot.text((peaks[2][0]+peaks[1][0])/2, y2, '%0.0f A' % r2,
                          horizontalalignment='center', 
                          verticalalignment='bottom',
                          color='black', rotation=90)
            
        # Ask matplotlib to render the figure to a bitmap using the Agg backend
        plot.set_xlim(min(data[:,1]), max(data[:,1]))
        canvas = matplotlib.backends.backend_agg.FigureCanvasAgg(figure)
        canvas.draw()
        matplotlib.rcParams.update({'font.size': old_fontsize})
        
        # Get the buffer from the bitmap
        stringImage = canvas.tostring_rgb()
        
        # Convert the RGBA buffer to a pixbuf
        try:
            l,b,w,h = canvas.figure.bbox.get_bounds()
        except:
            l,b,w,h = canvas.figure.bbox.bounds
        self.plot_pixbuf =  gtk.gdk.pixbuf_new_from_data(stringImage,
                                                    gtk.gdk.COLORSPACE_RGB, 
                                                    False, 8, 
                                                    int(w), int(h), 3*int(w))
        self._draw_histogram = True
            
    def _calc_palette(self, percent):
        frac = percent/100.0
        cdict = {
                 'red'  :  ((0., 1., 1.), (frac, 0.9, 0.9), (1., 0., 0.)),
                 'green':  ((0., 1., 1.), (frac, 0.9, 0.9), (1., 0., 0.)),
                 'blue' :  ((0., 1., 1.), (frac, 0.9, 0.9), (1., 0., 0.))
                 }
        cmap = LinearSegmentedColormap('_tmp_cmap', cdict)
        a = numpy.arange(256)
        tpal = cmap(a)[:,:-1].reshape((-1,1))
        rpal = [int(round(v[0]*255)) for v in tpal]
        return rpal

    def draw_overlay_cairo(self, cr):
        # rubberband
        cr.set_line_width(1.5)
        cr.set_source_rgb(0.0, 0.5, 1.0)
        if self._rubber_band:
            x, y, w, h = self._calc_bounds(self.rubber_x0,
                                           self.rubber_y0,
                                           self.rubber_x1,
                                           self.rubber_y1)    
            cr.rectangle(x, y, w, h)
            cr.stroke()
        
        # cross
        x, y, w, h = self.extents
        if (0 < (self.beam_x-x) < x+w) and (0 < (self.beam_y-y) < y+h):
            cx = int((self.beam_x-x)*self.scale)
            cy = int((self.beam_y-y)*self.scale)
            cr.move_to(cx-4, cy)
            cr.line_to(cx+4, cy)
            cr.stroke()
            cr.move_to(cx, cy-4)
            cr.line_to(cx, cy+4)
            cr.stroke()
        # measuring
        if self._measuring:
            cr.set_source_rgba(0.0, 0.5, 1.0,0.5)
            cr.set_line_width(4)
            cr.move_to(self.meas_x0, self.meas_y0)
            cr.line_to(self.meas_x1, self.meas_y1)
            cr.stroke()
        
        # Filename
        pcontext = self.get_pango_context()
        x, y, w, h = self.get_allocation()
        font_desc = pcontext.get_font_description()
        cr.select_font_face(font_desc.get_family(), cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12)
        cr.set_line_width(0.85)
        cr.move_to(6, h-6)
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
                if (0 < (sx-x) < x+w) and (0 < (sy-y) < y+h):
                    cx = int((sx-x)*self.scale)
                    cy = int((sy-y)*self.scale)
                    cr.arc(cx, cy, 16*self.scale, 0, 2.0 * numpy.pi)
                    cr.stroke()
            
            
    def go_back(self, full=False):
        if len(self.extents_back)> 0 and not full:
            self.extents = self.extents_back.pop()
        else:
            self.extents = (0,0,self.image_width, self.image_height)
            self.extents_back = []
        self.queue_draw()
        return len(self.extents_back) > 0

    def set_contrast(self, value):
        self._palette = self._calc_palette(value)
        self._colorize = True
        self._create_pixbuf()
        self.queue_draw()
    
    def set_brightness(self, value):
        # new images need to respect this so file_loader should be informed
        if (value == self.file_loader.gamma_offset) or (not self._canvas_is_clean):
            return 
        self.file_loader.gamma_offset = value
        gamma = self.gamma * numpy.exp(-self.file_loader.gamma_offset+_GAMMA_SHIFT)/30.0
        if gamma != self.display_gamma:
            lut = stretch(gamma)
            self.raw_img = self.src_image.point(lut.tolist(), 'L')
            self._create_pixbuf()
            self._canvas_is_clean = False
            self.queue_draw()
            self.display_gamma = gamma

    def colorize(self, value):
        self.set_colormap(index=value)
        self._canvas_is_clean = False
        self._create_pixbuf()
        self.queue_draw()

    def reset_filters(self):
        self.set_colormap('gist_yarg')
        self.display_gamma = self.gamma
        self.file_loader.gamma_offset = 0.0
        lut = stretch(self.gamma)
        self.raw_img = self.src_image.point(lut.tolist(), 'L')
        self._create_pixbuf()
        self.queue_draw()
       
    def _res(self,x,y):
        displacement = self.pixel_size * math.sqrt ( (x -self.beam_x)**2 + (y -self.beam_y)**2 )
        try:
            angle = 0.5 * math.atan(displacement/self.distance)
            if angle < 1e-3:
                angle = 1e-3
            return self.wavelength / (2.0 * math.sin(angle) )
        except:
            return 0.0
    
    def _rdist(self, x0, y0, x1, y1 ):
        d = math.sqrt((x0 - x1)**2 + (y0 - y1)**2) * self.pixel_size
        return d #(self.wavelength * self.distance/d)

    def get_position(self, x, y):
        if not self.image_loaded:
            return 0, 0, 0.0, 0
        ox,oy,ow,oh = self.extents
        Ix = int(x/self.scale)+ox
        Iy = int(y/self.scale)+oy
        Ix = max(0, min(Ix, self.image_width-1))
        Iy = max(0, min(Iy, self.image_height-1))
        Res = self._res(Ix, Iy)
        return Ix, Iy, Res, self.pixel_data[Ix, Iy]

    def _set_cursor_mode(self, cursor=None ):
        window = self.get_window()
        if window is None:
            return
        if cursor is None:
            window.set_cursor(None)
        else:
            if cursor == gtk.gdk.WATCH:
                _cur = LEFT_PTR_WATCH
            else:
                _cur = gtk.gdk.Cursor(cursor)
            window.set_cursor(_cur)
        gtk.main_iteration()
            
    def _clear_extents(self):
        self.extents_back = []
        self.back_btn.set_sensitive(False)
               
    def on_configure(self, widget, event):
        width, height = event.width, event.height
        if width > height:
            width = height
        else:
            height = width
        #self.queue_draw()
               
    def on_mouse_motion(self, widget, event):
        if not self.image_loaded:
            return False
        if event.is_hint:
            x, y, state = event.window.get_pointer()
        else:
            x = event.x; y = event.y
        #print event.state.value_names
        wx, wy, w, h = widget.get_allocation()
        if 'GDK_BUTTON1_MASK' in event.state.value_names and self._rubber_band:
            self.rubber_x1 = max(min(w-1, event.x), 0)
            self.rubber_y1 = max(min(h-1, event.y), 0)
            self.queue_draw()
        elif 'GDK_BUTTON2_MASK' in event.state.value_names and self._shifting:           
            self.shift_x1 = event.x
            self.shift_y1 = event.y
            ox,oy,ow,oh = self.extents
            nx = int((self.shift_x0-self.shift_x1)/self.scale)+ox
            ny = int((self.shift_y0-self.shift_y1)/self.scale)+oy
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
        elif 'GDK_BUTTON3_MASK' in event.state.value_names and self._measuring:
            self.meas_x1 = int(max(min(w-1, event.x), 0))
            self.meas_y1 = int(max(min(h-1, event.y), 0))
            self.queue_draw()
            
        return False
    
    def on_mouse_scroll(self, widget, event):
        if not self.image_loaded:
            return False
        if event.direction == gtk.gdk.SCROLL_UP:
            self.set_brightness(min(5, self.file_loader.gamma_offset + 0.2))
        elif event.direction == gtk.gdk.SCROLL_DOWN:
            self.set_brightness(max(-5, self.file_loader.gamma_offset - 0.2))
 
    def on_mouse_press(self, widget, event):
        self._draw_histogram = False
        if not self.image_loaded:
            return False
        wx, wy, w, h = widget.get_allocation()
        if event.button == 1:
            self.rubber_x0 = max(min(w, event.x), 0)
            self.rubber_y0 = max(min(h, event.y), 0)
            self.rubber_x1, self.rubber_y1 = self.rubber_x0, self.rubber_y0
            self._rubber_band = True
            self._set_cursor_mode(gtk.gdk.TCROSS)
        elif event.button == 2:
            self._set_cursor_mode(gtk.gdk.FLEUR)
            self.shift_x0 = max(min(w, event.x), 0)
            self.shift_y0 = max(min(w, event.y), 0)
            self.shift_x1, self.shift_y1 = self.shift_x0, self.shift_y0
            self._shift_start_extents = self.extents
            self._shifting = True
            self._set_cursor_mode(gtk.gdk.FLEUR)
        elif event.button == 3:
            self.meas_x0 = int(max(min(w, event.x), 0))
            self.meas_y0 = int(max(min(h, event.y), 0))
            self.meas_x1, self.meas_y1 = self.meas_x0, self.meas_y0
            self._measuring = True
            self._set_cursor_mode(gtk.gdk.TCROSS)
            
            
            
    def on_mouse_release(self, widget, event):
        if not self.image_loaded:
            return False        
        if self._rubber_band:
            self._rubber_band = False
            x,y,w,h = self._calc_bounds(self.rubber_x0,
                                  self.rubber_y0,
                                  self.rubber_x1,
                                  self.rubber_y1)
            if w < 5 and h < 5: return
            ox,oy,ow,oh = self.extents
            nx = int(x/self.scale)+ox
            ny = int(y/self.scale)+oy
            nw = int(w/self.scale)
            nh = int(h/self.scale)
            if nx + nw > self.image_width:
                nw = self.image_width - nx
            if ny + nh > self.image_height:
                nh = self.image_height - ny
            
            nw = max(16, min(nw, nh))
            nh = nw
            self.extents_back.append(self.extents)
            self.extents = (nx, ny, nw, nh)
            self.queue_draw()
        elif self._measuring:
            self._measuring = False
            # prevent zero-length lines
            self._histogram_data = self._get_intensity_line(self.meas_x0, self.meas_y0, 
                                           self.meas_x1, self.meas_y1, 2)
            if len(self._histogram_data) > 4:
                self._plot_histogram(self._histogram_data, show_axis=['left',])
                self.queue_draw()
        elif self._shifting:
            self._shifting = False
            
            self.extents_back.append(self._shift_start_extents)

        self._set_cursor_mode()
            
  
    def on_expose(self, widget, event):
        if self.pixbuf is not None:
            x, y, w, h = self.get_allocation()
            disp_pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, w, h)
            self.scale = float(w)/self.extents[2]
            if self.scale >= 1.0:
                interp = gtk.gdk.INTERP_NEAREST
            else:
                interp = self._best_interp
            src_pixbuf = self.pixbuf.subpixbuf(self.extents[0], self.extents[1],
                                     self.extents[2], self.extents[3])
            src_pixbuf.scale(disp_pixbuf, 0, 0, w, h, 0,
                              0, self.scale, self.scale, interp)
            if self._draw_histogram:
                hw = self.plot_pixbuf.get_width()
                hh = self.plot_pixbuf.get_height()
                self.plot_pixbuf.composite(disp_pixbuf,
                                           (w-hw-6), (h-hh-6), hw, hh, 
                                           (w-hw-6), (h-hh-6), 1.0, 1.0, self._best_interp,
                                           150)
            window = self.get_window()
            window.draw_pixbuf(self.gc, disp_pixbuf, 0, 0, 0, 0)

            context = window.cairo_create()
            context.rectangle(event.area.x, event.area.y, event.area.width, event.area.height)
            context.clip()
            
            pcontext = self.get_pango_context()
            font_desc = pcontext.get_font_description()
            style = self.get_style()
            context.set_source_color(style.fg[self.state])
            context.set_font_size( font_desc.get_size()/pango.SCALE )
            
            self.draw_overlay_cairo(context)
            self.draw_spots(context)
            self._canvas_is_clean = True
                
    def on_realized(self, obj):
        window = self.get_window()
        self.gc = window.new_gc()
        self.pl_gc = window.new_gc()
        self.pl_gc.foreground = self.get_colormap().alloc_color("#007fff")
        self.ol_gc = window.new_gc()
        self.ol_gc.foreground = self.get_colormap().alloc_color("green")
        self.ol_gc.set_function(gtk.gdk.XOR)
        self.ol_gc.set_line_attributes(1,gtk.gdk.LINE_SOLID,gtk.gdk.CAP_BUTT,gtk.gdk.JOIN_MITER)
 
    def on_visibility_notify(self, obj, event):
        if event.state == gtk.gdk.VISIBILITY_FULLY_OBSCURED:
            self.stopped = True
        else:
            self.stopped = False

    def on_unmap(self, obj):
        self.stopped = True
        
      
def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(6)
    win.set_title("Diffraction Image Viewer")
    myview = ImageWidget(512)
    gobject.idle_add(myview.load_frame, '/archive/users/decode/2009sep16_clsi/005/005_1/005_1_001.img')
    
    hbox = gtk.AspectFrame(ratio=1.0)
    hbox.set_shadow_type(gtk.SHADOW_NONE)
    hbox.add(myview)
    win.add(hbox)
    win.show_all()

    if len(sys.argv) == 2:
        myview.load_frame(sys.argv[1])
    
    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()

if __name__ == '__main__':
    main()
