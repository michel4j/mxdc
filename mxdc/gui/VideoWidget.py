import gtk
import gobject
import time
import threading
import bcm.utils
from bcm.protocols import ca

class VideoTransformer(threading.Thread, gobject.GObject):
    __gsignals__ =  { 
                    "changed": (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
                    }
    
    def __init__(self, camera, *args):
        threading.Thread.__init__(self)
        gobject.GObject.__init__(self)
        self.camera = camera
        self.width, self.height = self.camera.size
        self.fps = 0
        self.contrast = 0
        self.pixbuf = None
        self._stopped = True

    def resize(self, w, h):
        self.width, self.height = w, h   
        
    def run(self):
        ca.thread_init()
        self.start_time = time.time()
        count = 0
        while not self._stopped == False:
            if self.camera.is_on():
                count += 1
                if count == 10:
                    self.fps = count/(time.time() - self.start_time)
                    count = 0
                    self.start_time = time.time()
                img = self.camera.get_frame()
                img = ImageOps.autocontrast(img, cutoff=self.contrast)
                img = img.resize((self.width,self.height),Image.ANTIALIAS).convert('RGB')
                self.pixbuf = gtk.gdk.pixbuf_new_from_data(img.tostring(),gtk.gdk.COLORSPACE_RGB, 
                    False, 8, self.width, self.height, 3 * self.width )
                gobject.idle_add(self.emit, "changed")
            
    def stop(self):
        self._stopped = True
        self.camera.stop()
            
# Register objects with signals
gobject.type_register(VideoTransformer)

class VideoWidget(gtk.DrawingArea):
    def __init__(self, camera):
        self.camera = camera
        self.transformer = VideoTransformer(camera)
        self.pixmap = None
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
        self.connect_after('realize', self.on_realized)
        self.connect('configure_event', self.on_configure)
        self.connect("destroy", lambda x: self.transformer.stop())
        self.transformer.connect('changed', self.display)
       
    def set_overlay_func(self, func):
        self.overlay_func = func
        
    def display(self, obj):
        self.pixmap.draw_pixbuf(self.gc, self.transformer.pixbuf, 0, 0, 0, 0, self.width, self.height, 0,0,0)
        if self.overlay_func is not None:
            self.overlay_func(self.pixmap)
        self.queue_draw()        
        return True
       
    def on_configure(self, obj, event):
        self.width, self.height = obj.window.get_size()
        self.pixmap = gtk.gdk.Pixmap(obj.window, self.width, self.height)
        self.transformer.resize( self.width, self.height )
        self.gc = self.window.new_gc()
        self.ol_gc = self.window.new_gc()
        self.ol_gc.foreground = self.video.get_colormap().alloc_color("green")
        self.ol_gc.set_function(gtk.gdk.XOR)
        self.ol_gc.set_line_attributes(2,gtk.gdk.LINE_SOLID,gtk.gdk.CAP_BUTT,gtk.gdk.JOIN_MITER)
        
        return True
    
    def on_realized(self, obj):
        self.camera.start()
        self.transformer.start()
        return True

    def on_visibility_notify(self, obj, event):
        if event.state == gtk.gdk.VISIBILITY_FULLY_OBSCURED:
            self.camera.stop()
        else:
            self.camera.start()
        return True

    def on_unmap(self, obj):
        self.camera.stop()

    def on_expose(self, obj, event):        
        obj.window.draw_drawable(self.gc, self.pixmap, 0, 0, 0, 0, 
            self.width, self.height)
        return True
        