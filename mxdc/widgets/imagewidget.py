# -*- coding: UTF8 -*-
import os
import sys
import math
import re
import gc
import struct
import pickle
import gtk
import logging
import gobject
import time
import threading
import Image 
import ImageOps
import ImageDraw
import ImageFont
import numpy
import ctypes
from scipy.misc import toimage, fromimage
from dialogs import select_image
from matplotlib.colors import LinearSegmentedColormap
import matplotlib, matplotlib.backends.backend_agg
from matplotlib.pylab import loadtxt
from bcm.utils.science import peak_search

try:
    import cairo
    USE_CAIRO = True
except:
    USE_CAIRO = False

__log_section__ = 'mxdc.imgview'
img_logger = logging.getLogger(__log_section__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data') 
COLORMAPS = pickle.load(file(os.path.join(DATA_DIR, 'colormaps.data')))
_COLORNAMES = ['gist_yarg','gist_gray','hot','jet','hsv','Spectral',
                     'Paired','gist_heat','PiYG','Set1','gist_ncar']
        
        

class ImageWidget(gtk.DrawingArea):
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
        self.gamma_factor = 1.0

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
                gtk.gdk.VISIBILITY_NOTIFY_MASK)  

        self.connect('visibility-notify-event', self.on_visibility_notify)
        self.connect('unmap', self.on_unmap)
        self.connect('expose_event',self.on_expose)
        self.connect('realize', self.on_realized)
        self.connect('configure-event', self.on_configure)        
        self.connect('motion_notify_event', self.on_mouse_motion)
        self.connect('button_press_event', self.on_mouse_press)
        self.connect('button_release_event', self.on_mouse_release)
        self.set_size_request(size, size)
        self.set_colormap('gist_yarg')

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
        
    def _read_header(self, filename):
        # Read MarCCD header
        header_format = 'I16s39I80x' # 256 bytes
        statistics_format = '3Q7I9I40x128H' #128 + 256 bytes
        goniostat_format = '28i16x' #128 bytes
        detector_format = '5i9i9i9i' #128 bytes
        source_format = '10i16x10i32x' #128 bytes
        file_format = '128s128s64s32s32s32s512s96x' # 1024 bytes
        dataset_format = '512s' # 512 bytes
        image_format = '9437184H'
        marccd_header_format = header_format + statistics_format 
        marccd_header_format +=  goniostat_format + detector_format + source_format 
        marccd_header_format +=  file_format + dataset_format + '512x'
        myfile = open(filename,'rb')
        self.tiff_header = myfile.read(1024)
        self.header_pars = struct.unpack(header_format,myfile.read(256))
        self.statistics_pars = struct.unpack(statistics_format,myfile.read(128+256))
        self.goniostat_pars  = struct.unpack(goniostat_format,myfile.read(128))
        self.detector_pars = struct.unpack(detector_format, myfile.read(128))
        self.source_pars = struct.unpack(source_format, myfile.read(128))
        self.file_pars = struct.unpack(file_format, myfile.read(1024))
        self.dataset_pars = struct.unpack(dataset_format, myfile.read(512))
        # extract some values from the header
        self.beam_x, self.beam_y = self.goniostat_pars[1]/1e3, self.goniostat_pars[2]/1e3
        self.distance = self.goniostat_pars[0] / 1e3
        self.wavelength = self.source_pars[3] / 1e5
        self.pixel_size = self.detector_pars[1] / 1e6
        self.delta = self.goniostat_pars[24] / 1e3
        self.angle_start =  self.goniostat_pars[(7 + self.goniostat_pars[23])] / 1e3
        self.delta_time = self.goniostat_pars[4] / 1e3
        self.min_intensity = self.statistics_pars[3]
        self.max_intensity = self.statistics_pars[4]
        self.rms_intensity = self.statistics_pars[6] / 1e3
        self.average_intensity = self.statistics_pars[5] / 1e3
        self.overloads = self.statistics_pars[8]
        self.saturated_value = self.header_pars[23]
        self.two_theta = (self.goniostat_pars[7] / 1e3) * math.pi / -180.0

        if self.average_intensity < 0.1:
            self.gamma_factor = 1.0
        else:
            self.gamma_factor = 29.378 * self.average_intensity**-0.86
        myfile.close()

    def _read_pck_header(self, filename):
        header_format = '70s' # 40 bytes
        myfile = open(filename,'rb')
        header = myfile.readline()
        while header[0:17] != 'CCP4 packed image':
            header = myfile.readline()
        tokens = header.strip().split(',')
        self.image_width = int((tokens[1].split(':'))[1])
        self.image_height= int((tokens[2].split(':'))[1])
        self.beam_x, self.beam_y = self.image_width/2, self.image_height/2
        
        myfile.close()
        self.distance = 999.9
        self.wavelength = 0.99
        self.delta = 0.99
        self.pixel_size = 0.99
        self.angle_start = 99.9
        self.delta_time = 9.9
        self.min_intensity = 0
        self.max_intensity = 999
        self.overloads = 999
        self.two_theta = 0
        
        
    def load_frame(self, filename):
        self._set_cursor_mode(gtk.gdk.WATCH)
        self._read_header(filename)
        self.orig_img = Image.open(filename)
        self.pixel_data = self.orig_img.load()
        self._create_pixbuf()
        self.queue_draw()
        self._set_cursor_mode()
        self.image_loaded = True
        self.filename = filename
    
    def load_pck(self, filename):
        libpck = ctypes.cdll.LoadLibrary(os.path.join(DATA_DIR, 'libpck.so'))
        libpck.openfile.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
        libpck.openfile.restype = ctypes.c_int
        self._read_pck_header(filename)
        size = self.image_width * self.image_height
        data = ctypes.create_string_buffer( ctypes.sizeof(ctypes.c_ushort) * size )
        libpck.openfile(filename, ctypes.byref(data))
        self.pixel_data = numpy.fromstring(data, numpy.ushort)
        self.pixel_data.resize((self.image_width, self.image_height))
        self.orig_img = toimage(self.pixel_data)
        self.average_intensity = numpy.mean(self.pixel_data)
        if self.average_intensity < 0.1:
            self.gamma_factor = 1.0
        elif self.average_intensity < 2000.0:
            self.gamma_factor = 29.378 * self.average_intensity**-0.86
        else:
            self.gamma_factor = 5.0
        self._create_pixbuf()
        self.queue_draw()
        self._set_cursor_mode()
        self.image_loaded = True
        self.filename = filename
        
    
    def _create_pixbuf(self):
        gc.collect()
        self.raw_img = self.orig_img.point(lambda x: x * self.gamma_factor).convert('L')

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
                nh = self.image_height - nw
            nw = max(16, min(nh, nw))
            nh = nw
            self.extents = (nx, ny, nw, nh)
        #print self.average_intensity, self.gamma_factor
        self.pixbuf =  gtk.gdk.pixbuf_new_from_data(self.image.tostring(),
                                                    gtk.gdk.COLORSPACE_RGB, 
                                                    False, 8, 
                                                    self.image_width, 
                                                    self.image_height, 
                                                    3 * self.image_width)
    
    def get_image_info(self):
        info = {
            'img_size': (self.image_width, self.image_height),
            'pix_size': self.pixel_size,
            'exp_time': self.delta_time,
            'distance': self.distance,
            'angle': self.angle_start,
            'delta': self.delta,
            'two_theta': self.two_theta,
            'beam_center': (self.beam_x, self.beam_y),
            'wavelength': self.wavelength,
            'max_int': self.max_intensity,
            'avg_int': self.average_intensity,
            'overloads': self.overloads,
            'file': self.filename
            }
        return info
       
    def _calc_bounds(self, x0, y0, x1, y1):
        x = int(min(x0, x1))
        y = int(min(y0, y1))
        w = int(abs(x0 - x1))
        h = int(abs(y0 - y1))
        return (x,y,w,h)
          
    def _get_intensity_line(self, x,y,x2,y2):
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
            data[n][0] = n
            data[n][1] = self.pixel_data[ix, iy]
            data[n][2] = self._rdist(ix, iy, coords[0][0], coords[0][1])
            n += 1
        return data

    def _plot_histogram(self, data):
        figure = matplotlib.figure.Figure(frameon=False, figsize=( 3.5, 2), dpi=80, facecolor='w' )
        plot = figure.add_subplot(111)
        plot.axison = False
        plot.plot(data[:,2], data[:,1])
        peaks = peak_search(data[:,2], data[:,1], w=9, threshold=0.3, min_peak=0.1)

        if len(peaks) > 1:
            d1 = peaks[1][0] - peaks[0][0]
            y1 = max(peaks[0][1], peaks[1][1])/2
            r1 = (self.wavelength * self.distance/d1)
            x1 = (peaks[1][0] + peaks[0][0])/2
            plot.text((peaks[1][0]+peaks[0][0])/2, y1, '% 0.1f A' % r1,
                      horizontalalignment='center', 
                      color='black', rotation=90)        
        
        if len(peaks) > 2:
            d2 = peaks[2][0] - peaks[1][0]
            r2 = (self.wavelength * self.distance/d2)
            x2 = (peaks[2][0] + peaks[1][0])/2
            plot.text((peaks[2][0]+peaks[1][0])/2, y1, '% 0.1f' % r2,
                      horizontalalignment='center', 
                      color='black', rotation=90)
        
        # Ask matplotlib to render the figure to a bitmap using the Agg backend
        canvas = matplotlib.backends.backend_agg.FigureCanvasAgg(figure)
        canvas.draw()
        
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

    def draw_overlay(self):
        drawable = self.window
        gc = self.pl_gc        
        if self._rubber_band:
            x, y, w, h = self._calc_bounds(self.rubber_x0,
                                      self.rubber_y0,
                                      self.rubber_x1,
                                      self.rubber_y1)    
            drawable.draw_rectangle(gc, False, x, y, w, h)
        
        # cross
        x, y, w, h = self.extents
        if (0 < (self.beam_x-x) < x+w) and (0 < (self.beam_y-y) < y+h):
            cx = int((self.beam_x-x)*self.scale)
            cy = int((self.beam_y-y)*self.scale)
            drawable.draw_line(gc, cx-4, cy, cx+4, cy)
            drawable.draw_line(gc, cx, cy-4, cx, cy+4)
                   
        # measuring
        if self._measuring:
            drawable.draw_line(gc, self.meas_x0, self.meas_y0,
                               self.meas_x1, self.meas_y1)
        return True


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
            cr.move_to(self.meas_x0, self.meas_y0)
            cr.line_to(self.meas_x1, self.meas_y1)
            cr.stroke()

    def draw_spots(self, cr):
        # draw spots
        x, y, w, h = self.extents
        cr.set_line_width(1.0)
        cr.set_source_rgba(1.0, 0.0, 0.0, 1.0)
        for i, spots in enumerate([self.indexed_spots, self.unindexed_spots]):
            if i == 0:
                cr.set_source_rgb(0.0, 1.0, 0.0)
            else:
                cr.set_source_rgb(1.0, 0.0, 0.0)
            for spot in spots:
                sx, sy = spot[:2]
                if (0 < (sx-x) < x+w) and (0 < (sy-y) < y+h):
                    cx = int((sx-x)*self.scale)
                    cy = int((sy-y)*self.scale)
                    cr.move_to(cx-4, cy)
                    cr.line_to(cx+4, cy)
                    cr.stroke()
                    cr.move_to(cx, cy-4)
                    cr.line_to(cx, cy+4)
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
        if self.gamma_factor != value:
            self.gamma_factor = value
            self._create_pixbuf()
            self.queue_draw()

    def colorize(self, value):
        self.set_colormap(index=value)
        self._create_pixbuf()
        self.queue_draw()

    def reset_filters(self):
        self.set_colormap('gist_yarg')
        if self.average_intensity < 0.1:
            self.gamma_factor = 1.0
        else:
            self.gamma_factor = 29.378 * self.average_intensity**-0.86
        self._create_pixbuf()
        self.queue_draw()
       
    def _res(self,x,y):
        displacement = self.pixel_size * math.sqrt ( (x -self.beam_x)**2 + (y -self.beam_y)**2 )
        angle = 0.5 * math.atan(displacement/self.distance)
        if angle < 1e-3:
            angle = 1e-3
        return self.wavelength / (2.0 * math.sin(angle) )
    
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
        if cursor is None:
            self.window.set_cursor(None)
        else:
            self.window.set_cursor(gtk.gdk.Cursor(cursor))            
        while gtk.events_pending():
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
    
    def on_mouse_press(self, widget, event):
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
            self._histogram_data = self._get_intensity_line(self.meas_x0, self.meas_y0, 
                                           self.meas_x1, self.meas_y1)
            self._plot_histogram(self._histogram_data)
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
                                           (w-hw-24), (h-hh-24), hw, hh, 
                                           (w-hw-24), (h-hh-24), 1.0, 1.0, self._best_interp,
                                           125)
                self._draw_histogram = False

            self.window.draw_pixbuf(self.gc, disp_pixbuf, 0, 0, 0, 0)
            if USE_CAIRO:
                context = self.window.cairo_create()
                context.rectangle(event.area.x, event.area.y, event.area.width, event.area.height)
                context.clip()
                self.draw_overlay_cairo(context)
                self.draw_spots(context)
            else:
                self.draw_overlay()
                
    def on_realized(self, obj):
        self.gc = self.window.new_gc()
        self.pl_gc = self.window.new_gc()
        self.pl_gc.foreground = self.get_colormap().alloc_color("#007fff")
        self.ol_gc = self.window.new_gc()
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
    gobject.idle_add(myview.load_frame, '/home/michel/data/insulin/insulin_1_E1_0001.img')
    
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
