import threading, gc
import gtk, gobject
gobject.threads_init()
import sys, time, os
import Image
import ImageEnhance
import ImageOps
import numpy
import EPICS as CA

class VideoThread(threading.Thread, gobject.GObject):
    __gsignals__ =  { 
                    "image-updated": (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
                    }
    
    def __init__(self, parent, source, *args):
        threading.Thread.__init__(self)
        gobject.GObject.__init__(self)
        self.parent = parent
        self.width, self.height = self.parent.get_size()
        self.count = 0
        self.fps = 0
        self.stopped = False
        self.paused = False
        self.camera = source

    def __del__(self):
        self.stop()
                
    def run(self):
        CA.thread_init()
        self.start_time = time.time()
        while not self.stopped:
            time.sleep(1./self.parent.max_fps)
            if not self.paused:
                self.count += 1
                if self.count == 10:
                    gc.collect()
                    self.fps = self.count/(time.time() - self.start_time)
                    self.count = 0
                    self.start_time = time.time()
                img = self.camera.get_frame()
                self.contrast_factor = self.parent.contrast/3.
                img = ImageOps.autocontrast(img,cutoff=self.contrast_factor)
                img = img.resize((self.width,self.height),Image.ANTIALIAS).convert('RGB')
                self.parent.video_frame = gtk.gdk.pixbuf_new_from_data(img.tostring(),gtk.gdk.COLORSPACE_RGB, 
                    False, 8, self.width, self.height, 3 * self.width )
                gobject.idle_add(self.emit, "image-updated")
            
    def stop(self):
        self.camera.set_visible(False)
        self.stopped = True
        
    def pause(self):
        self.paused = True
        self.camera.set_visible(False)
    
    def resume(self):
        self.camera.set_visible(True)
        self.paused = False

# Register objects with signals
gobject.type_register(VideoThread)
