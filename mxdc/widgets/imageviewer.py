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
        self._collecting = False
        self.follow_id = None
        self.collect_id = None

#        #self.load_pck_image('FRAME.pck')
#        #self.display()

    def _create_widgets(self):
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                  'image_viewer')
        self._xml2 = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                  'adjuster_popup')
        
        self._widget = self._xml.get_widget('image_viewer')
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
        self.info_btn = self._xml.get_widget('info_btn')
        self.info_btn.connect('clicked', self.on_image_info)
        self.follow_tbtn.connect('toggled', self.on_follow_toggled)
        
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
        
        self._xml3 = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                  'info_dialog')
        self.info_dialog = self._xml3.get_widget('info_dialog')
        self.info_close_btn = self._xml3.get_widget('info_close_btn')
        self.info_close_btn.connect('clicked', lambda x: self.info_dialog.hide())
      
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
        self.info_btn.set_sensitive(True)
        self._update_info()
            
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

    def follow_frames(self):
        if os.access(self.next_filename, os.R_OK):
            self.open_image(self.next_filename)                
        return True
    
    def set_collect_mode(self, state=True):
        self._collecting = state
        if state:
            self.follow_tbtn.set_active(True)
            self.collect_queue = []
            if self.collect_id is not None:
                gobject.source_remove(self.collect_id)
            self.collect_id = gobject.timeout_add(2000, self.follow_collect)
    
    def _file_loadable(self, filename):
        if not os.path.exists(filename):
            print statinfo.st_mode
            return False
        statinfo = os.stat(filename)
        if (time.time() - statinfo.st_mtime) < 1.0:
            print statinfo.st_mode
            return False
        print statinfo.st_mode
        return True
    
    def follow_collect(self):
        if len(self.collect_queue) == 0 and self._collecting:
            return True
        elif not self._collecting:
            self.follow_tbtn.set_active(False)
            return False
        filename = self.collect_queue[0]
        # only show image if it is readable and the follow button is active
        
        if self._file_loadable(filename) and self.follow_tbtn.get_active():
            #self.open_image(filename)
            print filename, 'Loading...'
            self.collect_queue.remove(filename)
        else:
            print filename, os.access(filename, os.R_OK)
        return True
        

    def add_frame(self, filename):
        if self._collecting:
            self.collect_queue.append(filename)
            self.log("%d images in queue" % len(self.collect_queue) )
        else:
            self.open_image(filename)
        
    def on_brightness_changed(self, obj):
        self.image_canvas.set_brightness(obj.get_value())
    
    def on_contrast_changed(self, obj):
        self.contrast_factor = min(10, self.contrast_factor + 0.1)
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

    def _get_parent_window(self):
        parent = self.get_parent()
        while parent is not None:
            last_p = parent
            parent = parent.get_parent()
        return last_p

    def _update_info(self):
        info = self.image_canvas.get_image_info()
        for key, val in info.items():
            w = self._xml3.get_widget('%s_lbl' % key)
            if key in ['img_size', 'beam_center']:
                txt = "%0.0f, %0.0f" % (val[0], val[1])
            elif key in ['file']:
                txt = os.path.basename(val)
            else:
                txt = "%g" % val
            w.set_markup(txt)
        
    def on_image_info(self, obj):         
        if self.info_dialog is None:              
            self._xml3 = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                      'info_dialog')
            self.info_dialog = self._xml3.get_widget('info_dialog')
            self.info_close_btn = self._xml3.get_widget('info_close_btn')
            self.info_close_btn.connect('clicked', lambda x: self.info_dialog.hide())
        self._update_info()
        self.info_dialog.set_transient_for(self._get_parent_window())
        self.info_dialog.show()

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
            self.adjuster.set_transient_for(self._get_parent_window())
        else:
            self.adjuster.hide()

    def on_contrast_toggled(self, widget):
        if widget.get_active():
            self.adjuster.show_all()
            self.adjuster.set_transient_for(self._get_parent_window())
        else:
            self.adjuster.hide()
        
        
    def on_follow_toggled(self,widget):
        if widget.get_active():
            if not self._collecting:
                self._frames = True
                if self.follow_id is not None:
                    gobject.source_remove(self.follow_id)
                self.follow_id = gobject.timeout_add(3000, self.follow_frames)
        else:
            if self.follow_id is not None:
                gobject.source_remove(self.follow_id)
                self.follow_id = None
            self._follow = False
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
