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
        self.pixmap = None
        self.video_src = None
        self.pixbuf = None
        self._colorize = False
        self._palette = None
        self.overlay_func = None 
        self.set_events(gtk.gdk.EXPOSURE_MASK |
                gtk.gdk.LEAVE_NOTIFY_MASK |
                gtk.gdk.BUTTON_PRESS_MASK |
                gtk.gdk.POINTER_MOTION_MASK |
                gtk.gdk.POINTER_MOTION_HINT_MASK|
                gtk.gdk.VISIBILITY_NOTIFY_MASK)  

        self.connect('visibility-notify-event', self.on_visibility_notify)
        self.connect('unmap', self.on_unmap)
        self.connect('expose_event',self.on_expose)
        self.connect('realize', self.on_realized)
        self.connect('configure-event', self.on_configure)        
        self.connect("destroy", lambda x: self.video_src.del_sink(self))
    
    def set_src(self, src):
        self.video_src = src
        self.video_src.start()
        
    def on_configure(self, widget, event):
        width, height = widget.window.get_size()
        self.pixmap = gtk.gdk.Pixmap(widget.window, width,height)
        return True
    
    def set_overlay_func(self, func):
        self.overlay_func = func
        
    def display(self, img):
        if self._colorize and img.mode == 'L':
            img.putpalette(self._palette)
        img = img.convert('RGB')
        w, h = img.size
        self.pixbuf = gtk.gdk.pixbuf_new_from_data(img.tostring(),gtk.gdk.COLORSPACE_RGB, 
            False, 8, w, h, 3 * w )
        gobject.idle_add(self.queue_draw)
    
    def set_colormap(self, colormap=None):
        if colormap is not None:
            self._colorize = True
            self._palette = COLORMAPS[colormap]
        else:
            self._colorize = False
        self.vid_src.set_colormap(colormap)
        
    def on_expose(self, widget, event):
        w, h = self.get_size_request()
        if self.pixbuf is not None:
            self.pixmap.draw_pixbuf(self.gc, self.pixbuf, 0, 0, 0, 0, w, h, 0,0,0)
            if self.overlay_func is not None:
                    self.overlay_func(self.pixmap)
            self.window.draw_drawable(self.gc, self.pixmap, 0, 0, 0, 0, 
                w, h)
    
    def on_realized(self, obj):
        self.gc = self.window.new_gc()
        self.pl_gc = self.window.new_gc()
        self.pl_gc.foreground = self.get_colormap().alloc_color("#ffaaff")
        self.ol_gc = self.window.new_gc()
        self.ol_gc.foreground = self.get_colormap().alloc_color("green")
        self.ol_gc.set_function(gtk.gdk.XOR)
        self.ol_gc.set_line_attributes(1,gtk.gdk.LINE_SOLID,gtk.gdk.CAP_BUTT,gtk.gdk.JOIN_MITER)
        self.camera.add_sink(self)
        return True

    def on_visibility_notify(self, obj, event):
        if event.state == gtk.gdk.VISIBILITY_FULLY_OBSCURED:
            self._pause = True
        else:
            self._pause = False
        return True

    def on_unmap(self, obj):
        self._pause = True
