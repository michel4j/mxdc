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
        self._colorize = False
        self.frame_queue = Queue.Queue() 
        self.banner_text = "Video"
        self.width, self.height = self.camera.size
    
    def set_colormap(self, name=None):
        if name:
            self._colormap = name
            self._palette = COLORMAPS[self._colormap]
            self._colorize = True
        else:
            self._colorize = False
   
    def colorize_frame(self, img):
        img.putpalette(self._palette)

    def resize(self, w, h):
        self.width, self.height = w, h
        self.scale_factor = float(self.width) / self.camera.size[0]
        
        
    def start(self):
        self.worker_thread = threading.Thread(target=self._run)
        self.worker_thread.setDaemon(True)
        self.worker_thread.start()
                
    def _draw_banner(self, img):
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(os.path.join(WIDGET_DIR, 'data/miso.otf'), 14)
        except:
            font = ImageFont.load_default()
        w,h = img.size
        draw.rectangle([0, 0, w, 13], outline='#000000', fill='#000000')
        draw.text( (4, 0), self.banner_text, font=font, fill= '#aaffaa')
        
    def _run(self):
        ca.threads_init()
        count = 0
        start_time = time.time()
        while not self._stopped:
            #if self.camera.get_frame() is None: continue
            while self._paused and not self._stopped:
                time.sleep(0.1)
                
            if count % 100 == 0:
                start_time = time.time()
                count = 0
            self.fps = count/(time.time() - start_time + 0.0001)
            count += 1
            self.banner_text = '%s: %s, %0.0f fps' % (self.camera.name, time.strftime('%x %X'), self.fps)
            img = self.camera.get_frame()
            self.source_w, self.source_h = img.size
            img = ImageOps.autocontrast(img, cutoff=self.contrast)
            img = img.resize((self.width,self.height),Image.ANTIALIAS)
            if self._colorize and img.mode == 'L':
                self.colorize_frame(img)
            img = img.convert('RGB')
            self._draw_banner(img)
            gtk.gdk.threads_enter()
            pixbuf = gtk.gdk.pixbuf_new_from_data(img.tostring(),gtk.gdk.COLORSPACE_RGB, 
                False, 8, self.width, self.height, 3 * self.width )
            gtk.gdk.threads_leave()
            self.frame_queue.put(pixbuf)  
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
        self.pixbuf = None
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
        self.pixbuf = self.transformer.frame_queue.get_nowait()
        self.queue_draw()        
        return True
    
    def set_colormap(self, colormap=None):
        self.transformer.set_colormap(colormap)
        
    def on_expose(self, widget, event):
        w, h = self.get_size_request()
        if self.pixbuf is not None:
            self.pixmap.draw_pixbuf(self.gc, self.pixbuf, 0, 0, 0, 0, w, h, 0,0,0)
            if self.overlay_func is not None:
                    self.overlay_func(self.pixmap)
            self.window.draw_drawable(self.gc, self.pixmap, 0, 0, 0, 0, 
                w, h)

    def on_configure(self, obj, event):
        width, height = obj.window.get_size()
        self.pixmap = gtk.gdk.Pixmap(obj.window, width, height)
        self.transformer.resize(width, height)
        #self.width, self.height = self.transformer.width, self.transformer.height
        self.scale_factor = self.transformer.scale_factor                    
        return True
    
    def on_realized(self, obj):
        self.gc = self.window.new_gc()
        self.pl_gc = self.window.new_gc()
        self.pl_gc.foreground = self.get_colormap().alloc_color("#ffaaff")
        self.ol_gc = self.window.new_gc()
        self.ol_gc.foreground = self.get_colormap().alloc_color("green")
        self.ol_gc.set_function(gtk.gdk.XOR)
        self.ol_gc.set_line_attributes(1,gtk.gdk.LINE_SOLID,gtk.gdk.CAP_BUTT,gtk.gdk.JOIN_MITER)
        self.transformer.start()
        return True

    def on_visibility_notify(self, obj, event):
        if event.state == gtk.gdk.VISIBILITY_FULLY_OBSCURED:
            self.transformer.pause()
        else:
            self.transformer.resume()
        return True

    def on_unmap(self, obj):
        self.transformer.pause()

    def stop(self):
        self.transformer.stop()

    def start(self):
        self.transformer.start()
