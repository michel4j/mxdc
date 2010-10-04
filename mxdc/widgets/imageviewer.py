# -*- coding: UTF8 -*-

import sys
import re, os, time, gc, stat
import threading
import gtk
import gtk.glade
import gobject, pango
import math, re, struct
from dialogs import select_image
from mxdc.widgets.imagewidget import ImageWidget, image_loadable
from matplotlib.pylab import loadtxt
import logging

__log_section__ = 'mxdc.imageviewer'
img_logger = logging.getLogger(__log_section__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data') 

class ImageViewer(gtk.Frame):
    def __init__(self, size=512):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_OUT)
        self._canvas_size = size
        self._brightness = 1.0
        self._contrast = 1.0
        self._following = False
        self._collecting = False
        self._br_hide_id = None
        self._co_hide_id = None
        self._cl_hide_id = None
        self._follow_id = None
        self.next_filename = ''
        self.prev_filename = ''
        self.all_spots = []
        self._create_widgets()
        
    def _create_widgets(self):
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                  'image_viewer')
        self._xml2 = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                  'brightness_popup')
        self._xml4 = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                  'contrast_popup')
        self._xml5 = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                  'colorize_popup')
        
        self._widget = self._xml.get_widget('image_viewer')
        self.image_frame = self._xml.get_widget('image_frame')
        self.image_canvas = ImageWidget(self._canvas_size)
        self.image_canvas.connect('image-loaded', self._update_info)
        self.image_frame.add(self.image_canvas)
        self.image_canvas.connect('motion_notify_event', self.on_mouse_motion)
        
        self.open_btn = self._xml.get_widget('open_btn')
        self.image_label = self._xml.get_widget('image_label')
        self.next_btn = self._xml.get_widget('next_btn')
        self.prev_btn = self._xml.get_widget('prev_btn')
        self.back_btn = self._xml.get_widget('back_btn')
        self.zoom_fit_btn = self._xml.get_widget('zoom_fit_btn')
        self.follow_tbtn = self._xml.get_widget('follow_tbtn')
        self.reset_btn = self._xml.get_widget('reset_btn')
        self.info_btn = self._xml.get_widget('info_btn')
        self.info_btn.connect('clicked', self.on_image_info)
        self.follow_tbtn.connect('toggled', self.on_follow_toggled)
        
        self.contrast_tbtn = self._xml.get_widget('contrast_tbtn')
        self.contrast_popup = self._xml4.get_widget('contrast_popup')
        self.contrast = self._xml4.get_widget('contrast')
        self.contrast_tbtn.connect('toggled', self.on_contrast_toggled)     
        self.contrast.connect('value-changed', self.on_contrast_changed)
        
        self.brightness_tbtn = self._xml.get_widget('brightness_tbtn')
        self.brightness_popup = self._xml2.get_widget('brightness_popup')
        self.brightness = self._xml2.get_widget('brightness')
        self.brightness_tbtn.connect('toggled', self.on_brightness_toggled)
        self.brightness.connect('value-changed', self.on_brightness_changed)

        self.colorize_tbtn = self._xml.get_widget('colorize_tbtn')
        self.colorize_popup = self._xml5.get_widget('colorize_popup')
        self.colormap = self._xml5.get_widget('colormap')
        self.colorize_tbtn.connect('toggled', self.on_colorize_toggled)
        self.colormap.connect('value-changed', self.on_colormap_changed)
       
        self.reset_btn.connect('clicked', self.on_reset_filters)
        
        self.info_label = self._xml.get_widget('info_label')
        self.extra_label = self._xml.get_widget('extra_label')
        
        # signals
        self.open_btn.connect('clicked',self.on_file_open)
        self.prev_btn.connect('clicked', self.on_prev_frame)
        self.next_btn.connect('clicked', self.on_next_frame)
        self.back_btn.connect('clicked', self.on_go_back, False)      
        self.zoom_fit_btn.connect('clicked', self.on_go_back, True)
        
        self._xml3 = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                  'info_dialog')
        self.info_dialog = None
        
        self.image_canvas.connect('configure-event', self.on_configure)      
        self.add(self._widget)         
        self.show_all()

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
        img_logger.info(msg)
       
    def _load_spots(self, filename):
        try:
            self.all_spots = loadtxt(filename)
        except:
            img_logger.error('Could not load spots from %s' % filename)
   
    def _select_spots(self, spots):
        def _zeros(a):
            for v in a:
                if abs(v)<0.01:
                    return False
            return True
        indexed = [sp for sp in spots if _zeros(sp[4:])]
        unindexed = [sp for sp in spots if not _zeros(sp[4:])]
        return indexed, unindexed
                    
    def _select_image_spots(self, spots):
        image_spots = [sp for sp in spots if abs(self.frame_number - sp[2]) <= 1]
        return image_spots

    def _set_file_specs(self, filename):
        self.filename = filename
        # determine file template and frame_number
        file_pattern = re.compile('^(.*)([_.])(\d+)(\..+)?$')
        fm = file_pattern.search(self.filename)
        if fm:
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
            
            self.next_filename = self.file_template % (self.frame_number + 1)
            self.prev_filename = self.file_template % (self.frame_number - 1)
        else:
            self.next_filename = ''
            self.prev_filename = ''
        # test next
        if not image_loadable(self.next_filename):
            self.next_btn.set_sensitive(False)
        else:
            self.next_btn.set_sensitive(True)
        # test prev
        if not image_loadable(self.prev_filename):
            self.prev_btn.set_sensitive(False)
        else:
            self.prev_btn.set_sensitive(True)
        self.image_label.set_markup('<small>%s</small>' % self.filename)
        self.back_btn.set_sensitive(True)
        self.zoom_fit_btn.set_sensitive(True)
        self.contrast_tbtn.set_sensitive(True)
        self.brightness_tbtn.set_sensitive(True)
        self.colorize_tbtn.set_sensitive(True)
        self.reset_btn.set_sensitive(True)
        self.follow_tbtn.set_sensitive(True)
        self.info_btn.set_sensitive(True)
    
    def open_image(self, filename):
        if not image_loadable(filename):
            img_logger.error("File '%s' not readable!" % filename)
            return
                
        # select spots and display for current image
        if len(self.all_spots) > 0:
            image_spots = self._select_image_spots(self.all_spots)
            indexed, unindexed = self._select_spots(image_spots)
            self.image_canvas.set_spots(indexed, unindexed)

        file_extension = os.path.splitext(filename)[1].lower()                
        if file_extension in ['.pck']:
            img_logger.info("Loading packed image %s" % (filename))
            self.image_canvas.load_pck(self.filename)
        else:
            img_logger.info("Loading image %s" % (filename))
            self.image_canvas.load_frame(filename)
        #self._set_file_specs(filename)
        
    def set_collect_mode(self, state=True):
        self._collecting = state
        self.follow_tbtn.set_active(state)
    

    def _get_parent_window(self):
        parent = self.get_parent()
        last_parent = parent
        while parent is not None:
            last_parent = parent
            parent = last_parent.get_parent()
        return last_parent

    def _position_popups(self):
        ox, oy = self.window.get_origin()
        ix,iy,iw,ih,ib = self.image_canvas.window.get_geometry()
        cx = ox + ix + iw/2 - 100
        cy = oy + iy + ih/2 + 50
        self.contrast_popup.move(cx, cy)
        self.brightness_popup.move(cx, cy)
        self.colorize_popup.move(cx, cy)
        

    # signal handlers
    def on_focus_out(self, obj, event, btn):
        btn.set_active(False)
        
    def on_configure(self, obj, event):
        self._position_popups()
        return False

    def on_brightness_changed(self, obj):
        self.image_canvas.set_brightness(obj.get_value())
        if self._br_hide_id is not None:
            gobject.source_remove(self._br_hide_id)
            self._br_hide_id = gobject.timeout_add(6000, self._timed_hide, self.brightness_tbtn)
    
    def on_contrast_changed(self, obj):
        self.image_canvas.set_contrast(obj.get_value())
        if self._co_hide_id is not None:
            gobject.source_remove(self._co_hide_id)
            self._co_hide_id = gobject.timeout_add(6000, self._timed_hide, self.contrast_tbtn)

    def on_colormap_changed(self, obj):
        self.image_canvas.colorize(obj.get_value())
        if self._cl_hide_id is not None:
            gobject.source_remove(self._cl_hide_id)
            self._cl_hide_id = gobject.timeout_add(6000, self._timed_hide, self.colorize_tbtn)
    
    def on_reset_filters(self,widget):
        self.contrast_tbtn.set_active(False)
        self.brightness_tbtn.set_active(False)
        self.colorize_tbtn.set_active(False)
        self.image_canvas.reset_filters()
        return True    
    
    def on_go_back(self, widget, full):
        b = self.image_canvas.go_back(full)
        return True
    
    def on_mouse_motion(self,widget,event):
        ix, iy, ires, ivalue = self.image_canvas.get_position(event.x, event.y)
        self.info_label.set_markup("<small><tt>%5d %4d \n%5d %4.1f Å</tt></small>"% (ix, iy, ivalue, ires))


    def _update_info(self, obj=None):
        info = self.image_canvas.get_image_info()
        self._set_file_specs(info['file'])
        for key, val in info.items():
            w = self._xml3.get_widget('%s_lbl' % key)
            if not w:
                break
            if key in ['img_size', 'beam_center']:
                txt = "%0.0f, %0.0f" % (val[0], val[1])
            elif key in ['file']:
                txt = os.path.basename(val)
            else:
                txt = "%g" % val
            w.set_markup(txt)
            
    def add_frame(self, filename):
        if self._collecting and self._following:
            self.image_canvas.queue_frame(filename)

    def _follow_frames(self):
        if image_loadable(self.next_filename) and self._following:
            self.image_canvas.queue_frame(self.next_filename)
            gobject.timeout_add(1000, self._follow_frames)
        return False
          
    def on_image_info(self, obj):         
        if self.info_dialog is None:
            self._xml3 = gtk.glade.XML(os.path.join(DATA_DIR, 'image_viewer.glade'), 
                                      'info_dialog')
            self.info_dialog = self._xml3.get_widget('info_dialog')
            self.info_close_btn = self._xml3.get_widget('info_close_btn')
            self.info_close_btn.connect('clicked', self.on_info_destroy)
            self.info_dialog.set_transient_for(self._get_parent_window())
        self._update_info()
        self.info_dialog.show()

    def on_info_destroy(self, obj):
        self.info_dialog.destroy()
        self.info_dialog = None

    def on_next_frame(self,widget):
        if os.access(self.next_filename, os.R_OK):
            self.open_image(self.next_filename)
        else:
            img_logger.warning("File not found: %s" % (filename))
        return True

    def on_prev_frame(self,widget):
        if os.access(self.prev_filename, os.R_OK):
            self.open_image(self.prev_filename)
        else:
            img_logger.warning("File not found: %s" % (filename))
        return True

    def on_file_open(self,widget):
        filter, filename = select_image()
        if filename is not None and os.path.isfile(filename):
            if filter.get_name() == 'XDS SPOT Files':
                self._load_spots(filename)
                # if spot information is available  and an image is loaded display it
                if self.image_canvas.image_loaded:
                    image_spots = self._select_image_spots(self.all_spots)
                    indexed, unindexed = self._select_spots(image_spots)
                    self.image_canvas.set_spots(indexed, unindexed)
                    gobject.idle_add(self.image_canvas.queue_draw)
            else:
                self.open_image(filename)
        return True

    def _timed_hide(self, obj):
        obj.set_active(False)
        return False

    def on_brightness_toggled(self, widget):
        if self.brightness_tbtn.get_active():
            self.contrast_tbtn.set_active(False)
            self.colorize_tbtn.set_active(False)
            self._position_popups()
            self.brightness_popup.set_transient_for(self._get_parent_window())
            self.brightness_popup.show_all()
            self._br_hide_id = gobject.timeout_add(5000, self._timed_hide, self.brightness_tbtn)
        else:
            if self._br_hide_id is not None:
                gobject.source_remove(self._br_hide_id)
                self._br_hide_id = None
            self.brightness_popup.hide()

    def on_contrast_toggled(self, widget):
        if self.contrast_tbtn.get_active():
            self.brightness_tbtn.set_active(False)
            self.colorize_tbtn.set_active(False)
            self._position_popups()
            self.contrast_popup.set_transient_for(self._get_parent_window())
            self.contrast_popup.show_all()
            self._co_hide_id = gobject.timeout_add(5000, self._timed_hide, self.contrast_tbtn)
            
        else:
            if self._co_hide_id is not None:
                gobject.source_remove(self._co_hide_id)
                self._co_hide_id = None
            self.contrast_popup.hide()
        
    def on_colorize_toggled(self, widget):
        if self.colorize_tbtn.get_active():
            self.brightness_tbtn.set_active(False)
            self.contrast_tbtn.set_active(False)
            self._position_popups()
            self.colorize_popup.set_transient_for(self._get_parent_window())
            self.colorize_popup.show_all()
            self._cl_hide_id = gobject.timeout_add(5000, self._timed_hide, self.colorize_tbtn)
            
        else:
            if self._cl_hide_id is not None:
                gobject.source_remove(self._cl_hide_id)
                self._cl_hide_id = None
            self.colorize_popup.hide()
        
    def on_follow_toggled(self,widget):
        self._following = widget.get_active()
        if not self._collecting:
            gobject.timeout_add(1000, self._follow_frames)
        return True

def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(6)
    win.set_title("Diffraction Image Viewer")
    myview = ImageViewer(800)
    hbox = gtk.HBox(False)
    hbox.pack_start(myview)
    win.add(hbox)
    win.show_all()

    if len(sys.argv) == 2:
        myview.open_image(sys.argv[1])
    
    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()

if __name__ == '__main__':
    main()
