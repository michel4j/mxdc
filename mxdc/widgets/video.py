
from PIL import Image 
from gi.repository import GObject
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gtk
from gi.repository import Pango
from mxdc.interface.devices import IVideoSink
from mxdc.utils.video import image_to_surface
from zope.interface import implements
import os
import pickle
import time

WIDGET_DIR = os.path.dirname(__file__)
COLORMAPS = pickle.load(file(os.path.join(WIDGET_DIR, 'data/colormaps.data')))

    
class VideoWidget(Gtk.DrawingArea):
    implements(IVideoSink)    
    def __init__(self, camera):
        super(VideoWidget, self).__init__()
        self.camera = camera
        self.scale = 1
        self.surface = None
        self.stopped = False
        self._colorize = False
        self._palette = None
        self.fps = 0
        self._last_frame = 0
        self.overlay_func = None
        self.display_func = None
        
        self.set_events(Gdk.EventMask.EXPOSURE_MASK |
                Gdk.EventMask.LEAVE_NOTIFY_MASK |
                Gdk.EventMask.BUTTON_PRESS_MASK |
                Gdk.EventMask.POINTER_MOTION_MASK |
                Gdk.EventMask.POINTER_MOTION_HINT_MASK|
                Gdk.EventMask.VISIBILITY_NOTIFY_MASK | 
                Gdk.EventMask.BUTTON_RELEASE_MASK)  

        self.connect('visibility-notify-event', self.on_visibility_notify)
        self.connect('unmap', self.on_unmap)
        self.connect('draw',self.on_draw)
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
        w, h = map(float, self.camera.size)
        ratio = w/h
        if width < w/4: width = w/4
        if height < h/4: height = h/4
        if width < ratio * height:
            height = int(width/ratio)
        else:
            width = int(ratio * height)
        self.scale = float(width)/self.camera.size[0]
        self._img_width, self._img_height = width, height
        self.set_size_request(width, height)       
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
        self.surface = image_to_surface(img)
        GObject.idle_add(self.queue_draw)
        if self.display_func is not None:
            self.display_func(img, scale=self.scale)
    
    def set_colormap(self, colormap=None):
        if colormap is not None:
            self._colorize = True
            self._palette = COLORMAPS[colormap]
        else:
            self._colorize = False
        
    def on_draw(self, widget, ctx):
        if self.surface is not None:
            ctx.set_source_surface(self.surface, 0, 0)       
            ctx.paint()
            if self.overlay_func is not None:
                self.overlay_func(ctx)
            self.fps = 1.0/(time.time() - self._last_frame)
            self._last_frame = time.time()
    
    def on_realized(self, obj):
        self.camera.add_sink(self)
        return True

    def on_visibility_notify(self, obj, event):
        if event.get_state() == Gdk.VisibilityState.FULLY_OBSCURED:
            self.stopped = True
        else:
            self.stopped = False
        return True

    def on_unmap(self, obj):
        self.stopped = True
        
    def save_image(self, filename):
        window = self.get_window()
        colormap = window.get_colormap()
        pixbuf = GdkPixbuf.Pixbuf(GdkPixbuf.Colorspace.RGB, 0, 8, *window.get_size())
        pixbuf = pixbuf.get_from_drawable(window, colormap, 0,0,0,0, *window.get_size())
        ftype = os.path.splitext(filename)[-1]
        ftype = ftype.lower()
        if ftype in ['.jpg', '.jpeg']: 
            ftype = 'jpeg'
        else:
            ftype = 'png'
        pixbuf.save(filename, ftype)
