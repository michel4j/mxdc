import gtk
import gobject
import pango
import time
import threading, thread
import Image
import ImageOps
import bcm.utils
from bcm.protocols import ca

class VideoTransformer(gobject.GObject):
    __gsignals__ =  { 
                    "changed": (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
                    }
    
    def __init__(self, camera, maxfps=10):
        gobject.GObject.__init__(self)
        self.camera = camera
        self.maxfps = maxfps
        self.fps = 0
        self.contrast = 0
        self.scale_factor = 1.0
        self.pixbuf = None
        self._stopped = False
        self._paused = True
        self._lock = thread.allocate_lock()
    
    def resize(self, w, h):
        self._lock.acquire()
        self.width, self.height = w, h
        self.scale_factor = float(self.width) / self.camera.size[0]
        self._lock.release()
        
        
    def start(self):
        self.worker_thread = threading.Thread(target=self._run)
        self.worker_thread.start()
                
    def _run(self):
        ca.thread_init()
        count = 0
        start_time = time.time()
        while not self._stopped:
            while self.camera.get_frame() is None or self._paused:
                time.sleep(0.5)
                
            if count % 100 == 0:
                start_time = time.time()
                count = 0
            self.fps = count/(time.time() - start_time + 0.0001)
            count += 1
            
             
            img = self.camera.get_frame()
            self.source_w, self.source_h = img.size
            img = ImageOps.autocontrast(img, cutoff=self.contrast)
            self._lock.acquire()
            img = img.resize((self.width,self.height),Image.ANTIALIAS).convert('RGB')
            self.pixbuf = gtk.gdk.pixbuf_new_from_data(img.tostring(),gtk.gdk.COLORSPACE_RGB, 
                False, 8, self.width, self.height, 3 * self.width )
            self._lock.release()
            
            gobject.idle_add(self.emit, "changed")
            time.sleep(1.0/self.maxfps)
                 
    def stop(self):
        self._stopped = True
        
    def pause(self):
        self._paused = True
    
    def resume(self):
        self._paused = False
            
# Register objects with signals
gobject.type_register(VideoTransformer)

class VideoWidget(gtk.DrawingArea):
    def __init__(self, camera):
        gtk.DrawingArea.__init__(self)
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
        self.connect('realize', self.on_realized)
        self.connect('configure-event', self.on_configure)
        self.connect("destroy", lambda x: self.transformer.stop())
        self.transformer.connect('changed', self.display)
       
    def set_overlay_func(self, func):
        self.overlay_func = func
        
    def display(self, obj):
        self.pixmap.draw_pixbuf(self.gc, self.transformer.pixbuf, 0, 0, 0, 0, self.width, self.height, 0,0,0)
        if self.overlay_func is not None:
            self.overlay_func(self.pixmap)
        #self._draw_banner()
        self.queue_draw()        
        return True
    
    def _draw_banner(self):
        self.banner_pl.set_text('%2.0f FPS, %s' % (self.transformer.fps, time.strftime('%x %X %Z')))
        self.pixmap.draw_layout(self.pl_gc, 0, 0, self.banner_pl)

    def on_configure(self, obj, event):
        width, height = obj.window.get_size()
        self.pixmap = gtk.gdk.Pixmap(obj.window, width, height)
        self.transformer.resize(width, height)
        self.gc = self.window.new_gc()
        self.pl_gc = self.window.new_gc()
        self.pl_gc.foreground = self.get_colormap().alloc_color("black")
        self.ol_gc = self.window.new_gc()
        self.ol_gc.foreground = self.get_colormap().alloc_color("green")
        self.ol_gc.set_function(gtk.gdk.XOR)
        self.ol_gc.set_line_attributes(2,gtk.gdk.LINE_SOLID,gtk.gdk.CAP_BUTT,gtk.gdk.JOIN_MITER)
        self.width, self.height = self.transformer.width, self.transformer.height
        self.scale_factor = self.transformer.scale_factor                    
        return True
    
    def on_realized(self, obj):
        self.transformer.start()
        self.banner_pl = self.create_pango_layout("")
        self.banner_pl.set_font_description(pango.FontDescription("Monospace 7"))
        return True

    def on_visibility_notify(self, obj, event):
        if event.state == gtk.gdk.VISIBILITY_FULLY_OBSCURED:
            self.transformer.pause()
        else:
            self.transformer.resume()
        return True

    def on_unmap(self, obj):
        self.transformer.pause()

    def on_expose(self, obj, event):        
        obj.window.draw_drawable(self.gc, self.pixmap, 0, 0, 0, 0, 
            self.width, self.height)
        return True

    def stop(self):
        self.transformer.stop()

    def start(self):
        self.transformer.start()

if __name__ == '__main__':
    from bcm.devices import cameras
    win = gtk.Window()
    fr = gtk.AspectFrame(obey_child=False, ratio=640.0/480.0)
    win.set_size_request(320,240)
    win.connect('destroy', lambda x: gtk.main_quit() )
    cam = cameras.AxisCamera('ccd1608-201.cs.cls')
    vid = VideoWidget(cam)
    win.add(fr)
    fr.add(vid)
    win.show_all()
    try:
        gtk.main()
    finally:
        vid.stop()
