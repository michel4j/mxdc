#!/usr/bin/env python

import gtk, gobject
import sys, time, os
import numpy
import EPICS as CA
from Dialogs import save_selector
from Beamline import beamline
from LogServer import LogServer
from VideoThread import VideoThread

        
class HutchViewer(gtk.HBox):
    def __init__(self,size=1.0):
        gtk.HBox.__init__(self,False,6)
        
        self.timeout_id = None
        self.max_fps = 20
        self.source_height = 480.
        self.source_width = 640.
        self.display_size = size   # [0.5,0.75, 1.0] (image_pixels / display_pixel)
        self.video_realized = False
        self.ready = True
        self.click_centering  = False
        self.contrast = 0        
        
        self.camera = beamline['cameras']['hutch']
         
        self.width = int(self.source_width * self.display_size)
        self.height = int(self.source_height * self.display_size)


        self.create_widgets()
        
        self.tick_size = self.width / 55
        
        self.video.set_events(gtk.gdk.EXPOSURE_MASK |
                gtk.gdk.LEAVE_NOTIFY_MASK |
                gtk.gdk.BUTTON_PRESS_MASK |
                gtk.gdk.POINTER_MOTION_MASK |
                gtk.gdk.POINTER_MOTION_HINT_MASK|
                gtk.gdk.VISIBILITY_NOTIFY_MASK)  
        
        self.video.connect('configure_event', self.on_configure)
                       
        self.gonio_state = 0
        self.connect("destroy", lambda x: self.stop())
        self.video.connect('visibility-notify-event', self.on_visibility_notify)
        self.video.connect('button_press_event', self.on_image_click)
        self.video.connect('unmap', self.on_unmap)
        self.videothread = None

    def __del__(self):
        self.videothread.stop()
                                        
    def stop(self, win=None):
        self.videothread.stop()

    def get_size(self):
        return self.width, self.height
                   
    def display(self,widget=None):
        self.pixmap.draw_pixbuf(self.othergc, self.video_frame, 0, 0, 0, 0, self.width, self.height, 0,0,0)
        self.pangolayout.set_text("%5.0f FPS" % self.videothread.fps)
        self.pixmap.draw_layout(self.gc, self.width-70, self.height-20, self.pangolayout)
        self.video.queue_draw()

        return True     
                
    def save_image(self, filename):
        ftype = filename.split('.')[-1]
        if ftype == 'jpg': 
            ftype = 'jpeg'
        self.video_frame.save(filename, ftype)
        
    # callbacks
    def on_realized(self,widget):
        self.video_realized = True
        self.videothread = VideoThread(self, self.camera)
        self.videothread.connect('image-updated', self.display)
        self.connect('destroy', self.on_delete)
        self.videothread.start()
        self.videothread.pause()
        return True
        
    def on_visibility_notify(self, widget, event):
        if event.state == gtk.gdk.VISIBILITY_FULLY_OBSCURED:
            self.videothread.pause()
        else:
            self.videothread.resume()
        return True

    def on_save(self, obj=None, arg=None):
        img_filename = save_selector()
        if os.access(os.path.split(img_filename)[0], os.W_OK):
            LogServer.log('Saving sample image to: %s' % img_filename)
            self.save_image(img_filename)
        else:
            LogServer.log("Could not save %s." % img_filename)
    
    def on_unmap(self, widget):
        self.videothread.pause()
        return True

    def on_no_expose(self, widget, event):
        return True
        
    def on_delete(self,widget):
        self.videothread.stop()
        return True
        
    def on_expose(self, videoarea, event):        
        videoarea.window.draw_drawable(self.othergc, self.pixmap, 0, 0, 0, 0, 
            self.width, self.height)
        return True

    def on_configure(self,widget,event):
        width, height = widget.window.get_size()
        self.pixmap = gtk.gdk.Pixmap(self.video.window, width,height)
        self.gc = self.pixmap.new_gc()
        self.othergc = self.video.window.new_gc()
        self.gc.foreground = self.video.get_colormap().alloc_color("green")
        self.gc.set_function(gtk.gdk.XOR)
        self.gc.set_line_attributes(1,gtk.gdk.LINE_SOLID,gtk.gdk.CAP_NOT_LAST,gtk.gdk.JOIN_MITER)
        self.pangolayout = self.video.create_pango_layout("")
        return True
    
    def on_zoom_in(self,widget):
        if self.camera.controller:
            self.camera.controller.zoom(150)
        return True

    def on_zoom_out(self,widget):
        if self.camera.controller:
            self.camera.controller.zoom(-150)
        return True

    def on_unzoom(self,widget):
        if self.camera.controller:
            self.camera.controller.zoom( self.camera.controller.rzoom )
        return True
                
    def on_contrast_changed(self,widget):
        self.contrast = self.contrast_scale.get_value()
        return True
                
    def stop(self):
        if self.videothread is not None:
            self.videothread.stop()
            
    def on_image_click(self, widget, event):

        if event.button == 1:
            im_x, im_y = int(event.x/self.display_size), int(event.y/self.display_size)

            if self.camera.controller:
                self.camera.controller.center(im_x, im_y)
        return True

    def on_view_changed(self, widget):
        iter = widget.get_active_iter()
        model = widget.get_model()
        value = model.get_value(iter,0)
        if self.camera.controller:
            self.camera.controller.goto(value)
                                
    def create_widgets(self):
        # side-panel
        vbox = gtk.VBox(False, 6)
        self.set_border_width(6)
        
        # zoom section
        zoomframe = gtk.Frame('<b>Zoom Level:</b>')
        zoomframe.set_shadow_type(gtk.SHADOW_NONE)
        zoomframe.get_label_widget().set_use_markup(True)
        zoombbox = gtk.Table(1,3,True)
        zoombbox.set_row_spacings(3)
        zoombbox.set_col_spacings(3)
        zoombbox.set_border_width(3)
        zoomalign = gtk.Alignment()
        zoomalign.set(0.5,0.5,1,1)
        zoomalign.set_padding(0,0,12,0)
        self.zoom_out_btn = gtk.Button()
        self.zoom_in_btn = gtk.Button()
        self.zoom_100_btn = gtk.Button()
        self.zoom_out_btn.add( gtk.image_new_from_stock('gtk-zoom-out',gtk.ICON_SIZE_MENU))
        self.zoom_in_btn.add( gtk.image_new_from_stock('gtk-zoom-in',gtk.ICON_SIZE_MENU))
        self.zoom_100_btn.add( gtk.image_new_from_stock('gtk-zoom-100',gtk.ICON_SIZE_MENU))
        zoombbox.attach(self.zoom_out_btn, 0, 1, 0, 1)
        zoombbox.attach(self.zoom_100_btn, 1, 2, 0, 1)
        zoombbox.attach(self.zoom_in_btn, 2,3,0,1)
        zoomalign.add(zoombbox)
        zoomframe.add(zoomalign)
        vbox.pack_start(zoomframe,expand=False, fill=False)
        self.pack_start(vbox, expand=False, fill=False)
        self.zoom_out_btn.connect('clicked', self.on_zoom_out)
        self.zoom_in_btn.connect('clicked', self.on_zoom_in)
        self.zoom_100_btn.connect('clicked', self.on_unzoom)
        #zoomframe.set_sensitive(False)
        
        # Predefined positions
        select_view_frame = gtk.Frame('<b>Select View:</b>')
        select_view_frame.set_shadow_type(gtk.SHADOW_NONE)
        select_view_frame.get_label_widget().set_use_markup(True)
        self.views_cbox = gtk.combo_box_new_text()
        self.views_cbox.set_border_width(3)
        select_view_align = gtk.Alignment()
        select_view_align.set(0.5,0.5,1,1)
        select_view_align.set_padding(0,0,12,0)
        select_view_align.add(self.views_cbox)
        select_view_frame.add(select_view_align)
        vbox.pack_start(select_view_frame,expand=False, fill=False)
        
        self.views_cbox.append_text('Hutch')
        self.views_cbox.append_text('Sample Position')
        self.views_cbox.append_text('picoAmpmeters')
        self.views_cbox.append_text('Flouresence Screen') # Fluorescence  
        self.views_cbox.append_text('Attenuators')
        
        self.views_cbox.connect('changed', self.on_view_changed)
        
        #Video Area
        vbox2 = gtk.VBox(False,2)
        videoframe = gtk.Frame()
        videoframe.set_shadow_type(gtk.SHADOW_IN)
        self.video_frame = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, self.width, self.height)
        self.video = gtk.DrawingArea()
        self.video.set_size_request(self.width, self.height)
        self.video.connect('expose_event',self.on_expose)
        self.video.connect_after('realize',self.on_realized)

        videoframe.add(self.video)
        vbox2.pack_start(videoframe, expand=False, fill=False)
        
        self.pack_end(vbox2, expand=False, fill=False)
        self.show_all()


def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("HutchViewer")
    book = gtk.Notebook()
    win.add(book)
    myviewer = HutchViewer()
    book.append_page(myviewer, tab_label=gtk.Label('Hutch Viewer') )
    #book.append_page(gtk.DrawingArea(), tab_label=gtk.Label('Hutch Viewer') )

    win.show_all()

    try:
        gtk.gdk.threads_enter()
        gtk.main()
        gtk.gdk.threads_leave()
    finally:
        myviewer.videothread.stop()


if __name__ == '__main__':
    main()
