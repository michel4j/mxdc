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


from bcm.protocol import ca
import pickle

WIDGET_DIR = os.path.dirname(__file__)
COLORMAPS = pickle.load(file(os.path.join(WIDGET_DIR, 'data/colormaps.data')))

    
class VideoWidget(gtk.DrawingArea):
    def __init__(self, camera):
        gtk.DrawingArea.__init__(self)
        self.camera = camera
        self.pixbuf = None
        self.stopped = False
        self._colorize = False
        self._palette = None
        self.fps = 0
        self._last_frame = 0
        self.overlay_func = None
        self.display_func = None
        
        self.set_events(gtk.gdk.EXPOSURE_MASK |
                gtk.gdk.LEAVE_NOTIFY_MASK |
                gtk.gdk.BUTTON_PRESS_MASK |
                gtk.gdk.POINTER_MOTION_MASK |
                gtk.gdk.POINTER_MOTION_HINT_MASK|
                gtk.gdk.VISIBILITY_NOTIFY_MASK | 
                gtk.gdk.BUTTON_RELEASE_MASK)  

        self.connect('visibility-notify-event', self.on_visibility_notify)
        self.connect('unmap', self.on_unmap)
        self.connect('expose_event',self.on_expose)
        self.connect('realize', self.on_realized)
        self.connect('configure-event', self.on_configure)        
        self.connect("unrealize", self.on_destroy)
    
    def set_src(self, src):
        self.camera = src
        self.camera.start()
    
    def on_destroy(self, obj):
        self.camera.del_sink(self)
        self.camera.stop()
        
    def on_configure(self, widget, event):
        width, height = event.width, event.height
        ratio = float(self.camera.size[0])/self.camera.size[1]
        if width < 50: width = 50
        if height < 50: height = 50
        if width < ratio * height:
            height = int(width/ratio)
        else:
            width = int(ratio * height)
        self.scale = float(width)/self.camera.size[0]
        self._img_width, self._img_height = width, height
        self.set_size_request(-1,-1)
        return True
    
    def set_overlay_func(self, func):
        self.overlay_func = func

    def set_display_func(self, func):
        self.display_func = func
        
    def display(self, img):
        img = img.resize((self._img_width, self._img_height), Image.BICUBIC)
        if self._colorize:
            if img.mode != 'L':
                img = img.convert('L')
            img.putpalette(self._palette)
        img = img.convert('RGB')
        w, h = img.size
        self.pixbuf = gtk.gdk.pixbuf_new_from_data(img.tostring(),gtk.gdk.COLORSPACE_RGB, 
            False, 8, w, h, 3 * w )
        gobject.idle_add(self.queue_draw)
        if self.display_func is not None:
            self.display_func(img, scale=self.scale)
    
    def set_colormap(self, colormap=None):
        if colormap is not None:
            self._colorize = True
            self._palette = COLORMAPS[colormap]
        else:
            self._colorize = False
        
    def on_expose(self, widget, event):
        w, h = self.get_size_request()
        if self.pixbuf is not None:
            self.window.draw_pixbuf(self.gc, self.pixbuf, 0, 0, 0, 0, w, h, 0,0,0)
            if self.overlay_func is not None:
                    self.overlay_func(self.window)
            self.fps = 1.0/(time.time() - self._last_frame)
            self._last_frame = time.time()
    
    def on_realized(self, obj):
        self.gc = self.window.new_gc()
        self.pl_gc = self.window.new_gc()
        self.pl_gc.foreground = self.get_colormap().alloc_color("#ffaaff")
        self.ol_gc = self.window.new_gc()
        self.ol_gc.foreground = self.get_colormap().alloc_color("green")
        #self.ol_gc.set_function(gtk.gdk.XOR)
        self.ol_gc.set_line_attributes(1,gtk.gdk.LINE_SOLID,gtk.gdk.CAP_BUTT,gtk.gdk.JOIN_MITER)
        self.camera.add_sink(self)
        return True

    def on_visibility_notify(self, obj, event):
        if event.state == gtk.gdk.VISIBILITY_FULLY_OBSCURED:
            self.stopped = True
        else:
            self.stopped = False
        return True

    def on_unmap(self, obj):
        self.stopped = True
        
    def save_image(self, filename):
        colormap = self.window.get_colormap()
        pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, 0, 8, *self.window.get_size())
        pixbuf = pixbuf.get_from_drawable(self.window, colormap, 0,0,0,0, *self.window.get_size())
        ftype = os.path.splitext(filename)[-1]
        ftype = ftype.lower()
        if ftype in ['.jpg', '.jpeg']: 
            ftype = 'jpeg'
        else:
            ftype = 'png'
        pixbuf.save(filename, ftype)
