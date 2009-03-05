# -*- coding: UTF8 -*-

import sys
import re, os, time, gc, stat
import gtk
import gtk.glade
import gobject, pango
import math, re, struct
from dialogs import select_image
from mxdc.widgets.imagewidget import ImageWidget
import logging

__log_section__ = 'mxdc.imgview'
img_logger = logging.getLogger(__log_section__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data') 

class ImgViewer(gtk.Frame):
    def __init__(self):
        gtk.Frame.__init__(self)

        self._create_widgets()
        self.show_all()
        
        self._brightness = 1.0
        self._contrast = 1.0
        self._follow = False

#        #self.load_pck_image('FRAME.pck')
#        #self.display()

    def _create_widgets(self):
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                  'image_viewer')
        self._xml2 = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                  'adjuster_popup')
        self._xml3 = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                  'info_dialog')
        
        self._widget = self._xml.get_widget('image_viewer')
        self.info_dialog = self._xml3.get_widget('info_dialog')
        self.image_frame = self._xml.get_widget('image_frame')
        self.image_canvas = ImageWidget(512)
        self.image_frame.add(self.image_canvas)
        self.image_canvas.connect('motion_notify_event', self.on_mouse_motion)
        
        self.open_btn = self._xml.get_widget('open_btn')
        self.next_btn = self._xml.get_widget('next_btn')
        self.prev_btn = self._xml.get_widget('prev_btn')
        self.back_btn = self._xml.get_widget('back_btn')
        self.zoom_fit_btn = self._xml.get_widget('zoom_fit_btn')
        self.follow_tbtn = self._xml.get_widget('follow_tbtn')
        self.contrast_tbtn = self._xml.get_widget('contrast_tbtn')
        self.brightness_tbtn = self._xml.get_widget('brightness_tbtn')
        self.reset_btn = self._xml.get_widget('reset_btn')
        
        self.adjuster = self._xml2.get_widget('adjuster_popup')
        self.adjuster_scale = self._xml2.get_widget('adjustment')
        self.adjuster_scale.connect('value-changed', self.on_brightness_changed)
        
        self.info_label = self._xml.get_widget('info_label')
        self.extra_label = self._xml.get_widget('extra_label')
        
        # signals
        self.open_btn.connect('clicked',self.on_file_open)
        self.prev_btn.connect('clicked', self.on_prev_frame)
        self.next_btn.connect('clicked', self.on_next_frame)
        self.back_btn.connect('clicked', self.on_go_back, False)      
        self.zoom_fit_btn.connect('clicked', self.on_go_back, True)
        self.brightness_tbtn.connect('toggled', self.on_brightness_toggled)  
      
        self.add(self._widget)         

    def __set_busy(self, busy ):
        if busy:
            self.cursor = gtk.gdk.Cursor(gtk.gdk.WATCH)
            self.image_canvas.window.set_cursor( self.cursor )
        else:
            self.cursor = None
            self.image_canvas.window.set_cursor( self.cursor )
        while gtk.events_pending():
            gtk.main_iteration()

    def log(self, msg):
        img_logger.info('(ImageViewer) %s' % msg)
       
    
    def open_image(self, filename):
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
        
        # test next
        self.next_filename = self.file_template % (self.frame_number + 1)
        if not os.access(self.next_filename, os.R_OK):
            self.next_btn.set_sensitive(False)
        else:
            self.next_btn.set_sensitive(True)

        # test prev
        self.prev_filename = self.file_template % (self.frame_number - 1)
        if not os.access(self.prev_filename, os.R_OK):
            self.prev_btn.set_sensitive(False)
        else:
            self.prev_btn.set_sensitive(True)
        
        self.log("Loading image %s" % (self.filename))
        self.image_canvas.load_frame(self.filename)
        self.back_btn.set_sensitive(True)
        self.zoom_fit_btn.set_sensitive(True)
        self.contrast_tbtn.set_sensitive(True)
        self.brightness_tbtn.set_sensitive(True)
        self.reset_btn.set_sensitive(True)
        self.follow_tbtn.set_sensitive(True)
            
    def apply_filters(self, image):       
        #using auto_contrast
        #pc = self.contrast_factor / 5.0
        #new_img = ImageOps.autocontrast(image,cutoff=pc)
        
        #print self.contrast_factor
        enhancer = ImageEnhance.Contrast(image)
        return enhancer.enhance(self.contrast_factor)
        
        #f = (1.0 - self.contrast_factor) * 100
        #print f
        #return self.adjust_level(image, f)
        
                        
    def adjust_level(self, img, shift):     
        return img.point(lambda x: x * 1 + shift)
    
    def poll_for_file(self):
        if len(self.image_queue) == 0:
            if self.collecting_data == True:
                return True
            else:
                self.follow_toggle.set_active(False)
                return False
        else:
            next_filename = self.image_queue[0]
        
        self.__set_busy(True)
        if os.path.isfile(next_filename) and (os.stat(next_filename)[stat.ST_SIZE] == 18878464) and os.access(next_filename, os.R_OK):
            self.set_filename( next_filename )
            self.image_queue.pop(0) # delete loaded image from queue item
            self.load_image()
            self.display()
            self.__set_busy(False)
            return True
        else:
            self.__set_busy(False)
            return True     

    def auto_follow(self):
        # prevent chainloading by only loading images 4 seconds appart
        if time.time() - self.last_displayed < 3:
            return True
        if not (self.frame_number and self.file_template):
            return False
        self.frame_number = self.frame_number + 1
        filename = self.file_template % (self.frame_number)
        self.image_queue = []
        self.image_queue.append(filename)
        self.poll_for_file()
        return True        
    
    def set_collect_mode(self, state=True):
        self.collecting_data = state
        if self.collecting_data:
            self.follow_toggle.set_active(state)
            self.follow_frames = True
            self.image_queue = []
            if self.follow_id is not None:
                gobject.source_remove(self.follow_id)
            gobject.timeout_add(500, self.poll_for_file)

    def show_detector_image(self, filename):
        if self.collecting_data and self.follow_frames:
            self.image_queue.append(filename)
            self.log("%d images in queue" % len(self.image_queue) )
        return True     
        
    def zoom(self, size):
        old_size = self.image_size
        self.image_size = size
        if self.image_size < self.disp_size:
            self.image_size = self.disp_size
        if self.image_size > self.orig_size:
            interpolation = self.os_interp
        else:
            interpolation = self.ds_interp
        self.work_img = self.img.resize((self.image_size,self.image_size),interpolation)
        scale = float(self.image_size) / old_size
        self.x_center = int(scale * self.x_center) 
        self.y_center = int(scale * self.y_center)

    def autolevel(self, img, lo, hi):        
        scale = 256.0/(hi - lo)
        offset = -lo * scale
        return img.point(lambda x: x * scale + offset)

    
    # callbacks
    def on_configure(self, obj, event):
        width, height = obj.window.get_size()
        self.pixmap = gtk.gdk.Pixmap(self.image_canvas.window, width, height)
        self.width, self.height = width, height
        return True

    def on_realize(self, obj):
        self.gc = self.image_canvas.window.new_gc()
        self.pl_gc = self.image_canvas.window.new_gc()
        self.pl_gc.foreground = self.image_canvas.get_colormap().alloc_color("green")
        self.ol_gc = self.image_canvas.window.new_gc()
        self.ol_gc.foreground = self.image_canvas.get_colormap().alloc_color("green")
        self.ol_gc.set_function(gtk.gdk.XOR)
        self.ol_gc.set_line_attributes(2,gtk.gdk.LINE_SOLID,gtk.gdk.CAP_BUTT,gtk.gdk.JOIN_MITER)
        self.banner_pl = self.image_canvas.create_pango_layout("")
        self.banner_pl.set_font_description(pango.FontDescription("Monospace 7"))
        return True

    def on_brightness_changed(self, obj):
        self.image_canvas.set_brightness(obj.get_value())
    
    def on_incr_contrast(self,widget):
        self.contrast_factor = min(10, self.contrast_factor + 0.1)
        self.display()
        return True    

    def on_decr_contrast(self,widget):
        self.contrast_factor = max(0, self.contrast_factor - 0.1)
        self.display()
        return True    
    
    def on_reset_filters(self,widget):
        self.brightness_factor = 1.0
        self.contrast_factor = 1.0
        self.image_size = self.disp_size
        self.work_img = self.img.resize((self.image_size,self.image_size),self.ds_interp)
        self.display()
        return True    
    
    def on_go_back(self, widget, full):
        b = self.image_canvas.go_back(full)
        return True
    
    def on_mouse_motion(self,widget,event):
        ix, iy, ires, ivalue = self.image_canvas.get_position(event.x, event.y)
        self.info_label.set_markup("<small><tt>%5d %4d \n%5d %4.1f Å</tt></small>"% (ix, iy, ivalue, ires))

    def on_next_frame(self,widget):
        if os.access(self.next_filename, os.R_OK):
            self.open_image(self.next_filename)
        else:
            self.log("File not found: %s" % (filename))
        return True

    def on_prev_frame(self,widget):
        if os.access(self.prev_filename, os.R_OK):
            self.open_image(self.prev_filename)
        else:
            self.log("File not found: %s" % (filename))
        return True

    def on_file_open(self,widget):
        filename = select_image()
        self.open_image(filename)
        return True

    def on_brightness_toggled(self, widget):
        if widget.get_active():
            self.adjuster.show_all()
        else:
            self.adjuster.hide()
        
        
    def on_follow_toggled(self,widget):
        if widget.get_active():
            self.follow_frames = True
            if not self.collecting_data:
                self.follow_id = gobject.timeout_add(500, self.auto_follow)
        else:
            if self.follow_id is not None:
                gobject.source_remove(self.follow_id)
                self.follow_id = None
            self.follow_frames = False
        return True

def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(6)
    win.set_title("Diffraction Image Viewer")
    myview = ImgViewer()
    hbox = gtk.HBox(False)
    hbox.pack_start(myview)
    win.add(hbox)
    win.show_all()

    if len(sys.argv) == 2:
        myview.set_filename(sys.argv[1])
        myview.load_image()
        myview.display()
    
    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()

if __name__ == '__main__':
    main()
