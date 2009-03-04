# -*- coding: UTF8 -*-
import os
import sys
import Queue
import gtk
import gobject
import pango
import time
import threading
import Image 
import ImageOps
import ImageDraw
import ImageFont

import sys
import re, os, time, gc, stat
import gtk, gobject, pango
import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw, ImageFont
import numpy, re, struct
from scipy.misc import toimage, fromimage
import pickle
from dialogs import select_image
import logging

__log_section__ = 'mxdc.imgview'
img_logger = logging.getLogger(__log_section__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data') 
COLORMAPS = pickle.load(file(os.path.join(DATA_DIR, 'colormaps.data')))


class ImageWidget(gtk.DrawingArea):
    def __init__(self, size):
        gtk.DrawingArea.__init__(self)
        self.img = None
        self.pixbuf = None
        self.stopped = False
        self._colorize = False
        self._palette = None
        self.overlay_func = None
        self.img_size = size
        self.extents_back = []
        self.extents = None
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
        self.rubber_band=False
        #self.set_colormap('Spectral')
    
    def read_header(self, filename):
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
        myfile.close()

        # extract some values from the header
        self.beam_x, self.beam_y = self.goniostat_pars[1]/1e3, self.goniostat_pars[2]/1e3
        self.distance = self.goniostat_pars[0] / 1e3
        self.wavelength = self.source_pars[3] / 1e5
        self.pixel_size = self.detector_pars[1] / 1e6
        self.delta = self.goniostat_pars[24] / 1e3
        self.phi_start =  self.goniostat_pars[(7 + self.goniostat_pars[23])] / 1e3
        self.delta_time = self.goniostat_pars[4] / 1e3
        self.min_intensity = self.statistics_pars[3]
        self.max_intensity = self.statistics_pars[4]
        self.rms_intensity = self.statistics_pars[6] / 1e3
        self.average_intensity = max(80, self.statistics_pars[5] / 1e3)
        self.overloads = self.statistics_pars[8]
        self.saturated_value = self.header_pars[23]

    def set_colormap(self, colormap=None):
        if colormap is not None:
            self._colorize = True
            self._palette = COLORMAPS[colormap]
        else:
            self._colorize = False

    def set_filename(self, filename):
        self.filename = filename
        # determine file template and frame_number
        file_pattern = re.compile('^(.*)([_.])(\d+)(\..+)?$')
        fm = file_pattern.search(self.filename)
        parts = fm.groups()
        if len(parts) == 4:
            prefix = parts[0] + parts[1]
            if parts[3]:
                file_extension = parts[3]
            else:
                file_extension = ""
            self.file_template = "%s%s0%dd%s" % (prefix, '%', len(parts[2]), file_extension)
            self.frame_number = int (parts[2])
        else:
            self.file_template = None
            self.frame_number = None

    
    def load_frame(self, filename):
        self.set_filename(filename)
        self.display()
            
    def display(self):
        self.read_header(self.filename)
        raw_img = Image.open(self.filename)        
        self.gamma_factor = 80.0 / self.average_intensity     
        img = raw_img.point(lambda x: x * self.gamma_factor).convert('L')
        
        # invert the image to get black spots on white background and resize
        img = img.point(lambda x: x * -1 + 255)

        if self._colorize and img.mode == 'L':
            img.putpalette(self._palette)
        self.image = img.convert('RGB')
        self.image_width, self.image_height = self.image.size
        if self.extents is None:
            self.extents = (0,0, self.image_width, self.image_height)
        self.pixbuf =  gtk.gdk.pixbuf_new_from_data(self.image.tostring(),
                                                    gtk.gdk.COLORSPACE_RGB, 
                                                    False, 8, 
                                                    self.image_width, 
                                                    self.image_height, 
                                                    3 * self.image_width )
        self.queue_draw()
       
    def _calc_bounds(self, x0, y0, x1, y1):
        x = int(min(x0, x1))
        y = int(min(y0, y1))
        w = int(abs(x0 - x1))
        h = int(abs(y0 - y1))
        return (x,y,w,h)      
        
    def draw_rubberband(self):
        if not self.rubber_band:
            return
        drawable = self.window
        gc = self.pl_gc        
        x, y, w, h = self._calc_bounds(self.rubber_x0,
                                  self.rubber_y0,
                                  self.rubber_x1,
                                  self.rubber_y1)    
        drawable.draw_rectangle(gc, False, x, y, w,  h)

    def draw_cross(self):
        drawable = self.window
        gc = self.pl_gc        
        x, y, w, h = self.extents
        if (0 < (self.beam_x-x) < x+w) and (0 < (self.beam_y-y) < y+h):
            cx = int((self.beam_x-x)*self.scale)
            cy = int((self.beam_y-y)*self.scale)
            drawable.draw_line(gc, cx-4, cy, cx+4, cy)
            drawable.draw_line(gc, cx, cy-4, cx, cy+4)
        return

    def on_configure(self, widget, event):
        width, height = event.width, event.height
        if width > height:
            width = height
        else:
            height = width
        self.queue_draw()
               
    def on_mouse_motion(self, widget, event):
        if event.is_hint:
            x, y, state = event.window.get_pointer()
        else:
            x = event.x; y = event.y
        #print event.state.value_names
        if 'GDK_BUTTON1_MASK' in event.state.value_names:
            wx, wy, w, h = widget.get_allocation()
            self.rubber_x1 = max(min(w-1, event.x), 0)
            self.rubber_y1 = max(min(h-1, event.y), 0)
            self.queue_draw()
        #ix, iy = self._calc_position(x, y)
        #print ix, iy, self.extents
        return True
    
    def _calc_position(self, x, y):
        ox,oy,ow,oh = self.extents
        Ix = int(x/self.scale)+ox
        Iy = int(y/self.scale)+oy
        return Ix, Iy
        

    def on_mouse_press(self, widget, event):
        if event.button == 1:
            self.rubber_band = True
            wx, wy, w, h = widget.get_allocation()
            self.rubber_x0 = max(min(w, event.x), 0)
            self.rubber_y0 = max(min(h, event.y), 0)
            self.rubber_x1, self.rubber_y1 = self.rubber_x0, self.rubber_y0
        elif event.button == 2:
            if len(self.extents_back)>1:
                self.extents = self.extents_back.pop()
            else:
                self.extents = (0,0,self.image_width, self.image_height)
            self.queue_draw()
        return True

    def on_mouse_release(self, widget, event):
        if self.rubber_band:
            self.rubber_band = False
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
            nw = min(nw, nh)
            nh = nw
            self.extents_back.append(self.extents)
            self.extents = (nx, ny, nw, nh)
            self.queue_draw()
        return True  
  
    def on_expose(self, widget, event):
        if self.pixbuf is not None:
            x, y, w, h = self.get_allocation()
            src_pixbuf = self.pixbuf.subpixbuf(self.extents[0], self.extents[1],
                                     self.extents[2], self.extents[3])
            disp_pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, w, h)
            self.scale = float(w)/self.extents[2]
            if self.scale < 1.0:
                interp = gtk.gdk.INTERP_HYPER
            else:
                interp = gtk.gdk.INTERP_NEAREST
            src_pixbuf.scale(disp_pixbuf, 0, 0, w, h, 0,
                              0, self.scale, self.scale, interp)
            self.window.draw_pixbuf(self.gc, disp_pixbuf, 0, 0, 0, 0)
            self.draw_rubberband()
            self.draw_cross()
                
    def on_realized(self, obj):
        self.gc = self.window.new_gc()
        self.pl_gc = self.window.new_gc()
        self.pl_gc.foreground = self.get_colormap().alloc_color("black")
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
    gobject.idle_add(myview.load_frame, '/home/michel/data/h14/h14_1_peak_0302.img')
    
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
