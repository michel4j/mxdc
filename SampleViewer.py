#!/usr/bin/env python

import gtk, gobject
import sys, time, os
import numpy
import EPICS as CA
from Dialogs import save_selector
from Beamline import beamline
from LogServer import LogServer
from VideoThread import VideoThread
from Scripting import Script
import Scripts

        
class SampleViewer(gtk.HBox):
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
        
        self.omega      = beamline['motors']['omega']
        self.sample_x   = beamline['motors']['sample_x']
        self.sample_y1  = beamline['motors']['sample_y']
        self.sample_y2  = beamline['motors']['sample_z']
        self.beam_width = beamline['motors']['gslits_hgap']
        self.beam_height = beamline['motors']['gslits_vgap']
        self.slits_x    = beamline['motors']['gslits_hpos']
        self.slits_y    = beamline['motors']['gslits_vpos']
        self.zoom       = beamline['motors']['zoom']
        self.light      = beamline['variables']['sample_light']
        self.light_val  =  beamline['variables']['sample_light_val']
        self.cross_x = beamline['variables']['beam_x']
        self.cross_y = beamline['variables']['beam_y']
        self.camera = beamline['cameras']['sample']      
        
        self.width = int(self.source_width * self.display_size)
        self.height = int(self.source_height * self.display_size)
        self.lighting = self.light_val.get_position()

        self.on_change() #initialize display variables
        self.pixel_size = 5.34e-3 * numpy.exp( -0.18 * self.zoom_factor)

        self.create_widgets()
        
        self.tick_size = self.width / 55
        
        self.video.set_events(gtk.gdk.EXPOSURE_MASK |
                gtk.gdk.LEAVE_NOTIFY_MASK |
                gtk.gdk.BUTTON_PRESS_MASK |
                gtk.gdk.POINTER_MOTION_MASK |
                gtk.gdk.POINTER_MOTION_HINT_MASK|
                gtk.gdk.VISIBILITY_NOTIFY_MASK)  
        self.measuring = False
        self.measure_x1 = 0
        self.measure_x2 = 0
        self.measure_y1 = 0
        self.measure_y2 = 0
        
        self.video.connect('configure_event', self.on_configure)
        self.video.connect('motion_notify_event', self.on_mouse_motion)
        self.video.connect('button_press_event', self.on_image_click)
        
        self.beam_width.connect('changed', self.on_change)
        self.beam_height.connect('changed', self.on_change)
        self.slits_x.connect('changed', self.on_change)
        self.slits_y.connect('changed', self.on_change)
        self.cross_x.connect('changed', self.on_change)
        self.cross_y.connect('changed', self.on_change)
        self.zoom.connect('changed', self.on_change)
               
        self.gonio_state = 0
        self.connect("destroy", lambda x: self.stop())
        self.video.connect('visibility-notify-event', self.on_visibility_notify)
        self.video.connect('unmap', self.on_unmap)
        self.last_click_time = time.time()
        self.videothread = None

    def __del__(self):
        self.videothread.stop()
                                        
    def stop(self, win=None):
        self.videothread.stop()

    def get_size(self):
        return self.width, self.height
                   
    def display(self,widget=None):
        self.pixel_size = 5.34e-3 * numpy.exp( -0.18 * self.zoom_factor)
        self.pixmap.draw_pixbuf(self.othergc, self.video_frame, 0, 0, 0, 0, self.width, self.height, 0,0,0)
        self.draw_cross()
        self.draw_slits()
        self.pangolayout.set_text("%5.0f FPS" % self.videothread.fps)
        self.draw_measurement()
        self.pixmap.draw_layout(self.gc, self.width-70, self.height-20, self.pangolayout)
        self.video.queue_draw()
        if self.click_centering:
            elapsed = time.time() - self.last_click_time
            if elapsed > 60:
                self.click_btn.set_active(False)
        
        return True     
    
    def draw_cross(self):
        x = int(self.cross_x_position * self.display_size)
        y = int(self.cross_y_position * self.display_size)
        self.pixmap.draw_line(self.gc, x-self.tick_size, y, x+self.tick_size, y)
        self.pixmap.draw_line(self.gc, x, y-self.tick_size, x, y+self.tick_size)
        return

    def draw_slits(self):
        
        beam_width = self.beam_width_position
        beam_height = self.beam_height_position
        slits_x = self.slits_x_position
        slits_y = self.slits_y_position
        cross_x = self.cross_x_position
        cross_y = self.cross_y_position
        
        self.slits_width  = beam_width / self.pixel_size
        self.slits_height = beam_height / self.pixel_size
        if self.slits_width  >= self.width:
            return
        if self.slits_height  >= self.height:
            return
        x = int((cross_x - (slits_x / self.pixel_size)) * self.display_size)
        y = int((cross_y - (slits_y / self.pixel_size)) * self.display_size)
        hw = int(0.5 * self.slits_width * self.display_size)
        hh = int(0.5 * self.slits_height * self.display_size)
        self.pixmap.draw_line(self.gc, x-hw, y-hh, x-hw, y-hh+self.tick_size)
        self.pixmap.draw_line(self.gc, x-hw, y-hh, x-hw+self.tick_size, y-hh)
        self.pixmap.draw_line(self.gc, x+hw, y+hh, x+hw, y+hh-self.tick_size)
        self.pixmap.draw_line(self.gc, x+hw, y+hh, x+hw-self.tick_size, y+hh)

        self.pixmap.draw_line(self.gc, x-hw, y+hh, x-hw, y+hh-self.tick_size)
        self.pixmap.draw_line(self.gc, x-hw, y+hh, x-hw+self.tick_size, y+hh)
        self.pixmap.draw_line(self.gc, x+hw, y-hh, x+hw, y-hh+self.tick_size)
        self.pixmap.draw_line(self.gc, x+hw, y-hh, x+hw-self.tick_size, y-hh)
        return
        
    def draw_measurement(self):
        if self.measuring == True:
            x1 = self.measure_x1
            y1 = self.measure_y1
            x2 = self.measure_x2
            y2 = self.measure_y2
            dist = self.pixel_size * numpy.sqrt((x2 - x1) ** 2.0 + (y2 - y1) ** 2.0) / self.display_size
            x1, x2, y1, y2 = int(x1), int(y1), int(x2), int(y2)
            self.pixmap.draw_line(self.gc, x1, x2, y1, y2)
            self.pangolayout.set_text("%5.4f mm" % dist)
        return True
    
    def save_image(self, filename):
        self.camera.save(filename)
        
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

    def on_change(self, obj=None, arg=None):
        self.beam_width_position = self.beam_width.get_position()
        self.beam_height_position = self.beam_height.get_position()
        self.slits_x_position = self.slits_x.get_position()
        self.slits_y_position = self.slits_y.get_position()
        self.cross_x_position = self.cross_x.get_position()
        self.cross_y_position = self.cross_y.get_position()
        self.zoom_factor = self.zoom.get_position()

    def on_save(self, obj=None, arg=None):
        img_filename = save_selector()
        if os.access(os.path.split(img_filename)[0], os.W_OK):
            LogServer.log('Saving sample image to: %s' % img_filename)
            self.save_image(img_filename)
        else:
            LogServer.log("Could not save %s." % img_filename)
    
    def on_center_loop(self,widget):
        script = Script(Scripts.center_sample)
        self.side_panel.set_sensitive(False)
        script.connect('done', self.done_centering)
        script.connect('error', self.done_centering)
        script.start()
        return True
              
    def on_center_crystal(self,widget):
        script = Script(Scripts.center_sample, crystal=True)
        self.side_panel.set_sensitive(False)
        script.connect('done', self.done_centering)
        script.connect('error', self.done_centering)
        script.start()
        return True

    def done_centering(self,obj):
        self.side_panel.set_sensitive(True)
        return True
            
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
        cur_zoom = self.zoom.get_position()
        next_zoom = (cur_zoom < 13) and int(cur_zoom + 1) or int(cur_zoom)
        self.zoom.move_to(next_zoom)
        return True

    def on_zoom_out(self,widget):
        cur_zoom = self.zoom.get_position()
        next_zoom = (cur_zoom > 1) and int(cur_zoom - 1) or int(cur_zoom)
        self.zoom.move_to(next_zoom)
        return True

    def on_incr_omega(self,widget):
        cur_omega = int( self.omega.get_position() / 90) * 90
        self.omega.move_to(cur_omega + 90.0)
        return True

    def on_decr_omega(self,widget):
        cur_omega = int(self.omega.get_position() / 90) * 90
        self.omega.move_to(cur_omega - 90.0)
        return True

    def on_double_incr_omega(self,widget):
        cur_omega = int(self.omega.get_position() / 90) * 90
        self.omega.move_to(cur_omega + 180.0)
        return True

    def on_unzoom(self,widget):
        self.zoom.move_to(1)
        return True

    def position(self,x,y):
        im_x = int( float(x)/self.display_size)
        im_y = int( float(y)/self.display_size)
        x_offset = self.cross_x_position - im_x
        y_offset = self.cross_y_position - im_y
        xmm = x_offset * self.pixel_size
        ymm = y_offset * self.pixel_size
        return (im_x, im_y, xmm, ymm)
                
    def on_mouse_motion(self, widget, event):
        if event.is_hint:
            x, y, state = event.window.get_pointer()
        else:
            x = event.x; y = event.y
        im_x, im_y, xmm, ymm = self.position(x,y)
        self.pos_label.set_text("<tt>%4d,%4d [%6.3f, %6.3f mm]</tt>" % (im_x, im_y, xmm, ymm))
        self.pos_label.set_use_markup(True)
        if 'GDK_BUTTON3_MASK' in event.state.value_names:
            self.measure_x2, self.measure_y2, = event.x, event.y
        else:
            self.measuring = False
        return True

    def on_image_click(self, widget, event):

        if event.button == 1:
            if self.gonio_state == 1 or self.click_centering == False:
                return True
            self.last_click_time = time.time()
            self.center_pixel(event.x, event.y)
        elif event.button == 3:
            self.measuring = True
            self.measure_x1, self.measure_y1 = event.x,event.y
            self.measure_x2, self.measure_y2 = event.x,event.y

        return True
    
    def center_pixel(self, x, y):
        tmp_omega = int(round(self.omega.get_position()))
        sin_w = numpy.sin(tmp_omega * numpy.pi / 180)
        cos_w = numpy.cos(tmp_omega * numpy.pi / 180)
        im_x, im_y, xmm, ymm = self.position(x,y)
        self.sample_x.move_by( -xmm )
        #if   abs(sin_w) == 1:
        self.sample_y1.move_by( -ymm * sin_w  )
        #elif abs(cos_w) == 1:
        self.sample_y2.move_by( ymm * cos_w  )
                
    def on_fine_up(self,widget):
        tmp_omega = int(round(self.omega.get_position()))
        sin_w = numpy.sin(tmp_omega * numpy.pi / 180)
        cos_w = numpy.cos(tmp_omega * numpy.pi / 180)
        step_size = self.pixel_size * 10.0
        if  abs(sin_w) == 1:
            self.sample_y1.move_by( step_size * sin_w * 0.5 )
        elif abs(cos_w) == 1:
            self.sample_y2.move_by( -step_size * cos_w * 0.5 )   
        return True
        
    def on_fine_down(self,widget):
        tmp_omega = int(round(self.omega.get_position()))
        sin_w = numpy.sin(tmp_omega * numpy.pi / 180)
        cos_w = numpy.cos(tmp_omega * numpy.pi / 180)
        step_size = self.pixel_size * 10.0
        if  abs(sin_w) == 1:
            self.sample_y1.move_by( -step_size * sin_w * 0.5 )
        elif abs(cos_w) == 1:
            self.sample_y2.move_by( step_size * cos_w * 0.5 )
        return True
        
    def on_fine_left(self,widget):
        step_size = self.pixel_size * 10.0
        self.sample_x.move_by( step_size * 0.5 )
        return True
        
    def on_fine_right(self,widget):
        step_size = self.pixel_size * 10.0
        self.sample_x.move_by( -step_size * 0.5 )
        return True
        
    def on_home(self,widget):
        return True
                
    def toggle_click_centering(self, widget):
        if self.click_centering == True:
            self.click_centering = False
        else:
            self.click_centering = True
            self.last_click_time = time.time()
        return True
    
    def on_contrast_changed(self,widget):
        self.contrast = self.contrast_scale.get_value()
        return True
        
    def on_lighting_changed(self,widget):
        self.lighting = 0.5 * self.lighting_scale.get_value()
        self.light.move_to( self.lighting )
        return True
        
    def stop(self):
        if self.videothread is not None:
            self.videothread.stop()
            
    def create_widgets(self):
        # side-panel
        self.side_panel = gtk.VBox(False, 6)
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
        self.side_panel.pack_start(zoomframe,expand=False, fill=False)
        self.pack_start(self.side_panel, expand=False, fill=False)
        self.zoom_out_btn.connect('clicked', self.on_zoom_out)
        self.zoom_in_btn.connect('clicked', self.on_zoom_in)
        self.zoom_100_btn.connect('clicked', self.on_unzoom)
        
        # move sample section
        move_sample_frame = gtk.Frame('<b>Move Sample:</b>')
        move_sample_frame.set_shadow_type(gtk.SHADOW_NONE)
        move_sample_frame.get_label_widget().set_use_markup(True)
        move_sample_bbox = gtk.Table(3,3,True)
        move_sample_bbox.set_row_spacings(3)
        move_sample_bbox.set_col_spacings(3)
        move_sample_bbox.set_border_width(3)
        move_sample_align = gtk.Alignment()
        move_sample_align.set(0.5,0.5,1,1)
        move_sample_align.set_padding(0,0,12,0)
        self.up_btn = gtk.Button()
        self.up_btn.add(gtk.image_new_from_stock('gtk-go-up',gtk.ICON_SIZE_MENU))
        move_sample_bbox.attach(self.up_btn, 1,2,0,1)
        self.dn_btn = gtk.Button()
        self.dn_btn.add(gtk.image_new_from_stock('gtk-go-down',gtk.ICON_SIZE_MENU))
        move_sample_bbox.attach(self.dn_btn, 1,2,2,3)
        self.left_btn = gtk.Button()
        self.left_btn.add(gtk.image_new_from_stock('gtk-go-back',gtk.ICON_SIZE_MENU))
        move_sample_bbox.attach(self.left_btn, 0,1,1,2)
        self.right_btn = gtk.Button()
        self.right_btn.add(gtk.image_new_from_stock('gtk-go-forward',gtk.ICON_SIZE_MENU))
        move_sample_bbox.attach(self.right_btn, 2,3,1,2)
        self.home_btn = gtk.Button()
        self.home_btn.add(gtk.image_new_from_stock('gtk-home',gtk.ICON_SIZE_MENU))
        move_sample_bbox.attach(self.home_btn, 1,2,1,2)
        move_sample_align.add(move_sample_bbox)
        move_sample_frame.add(move_sample_align)
        self.side_panel.pack_start(move_sample_frame,expand=False, fill=False)
        self.up_btn.connect('clicked', self.on_fine_up)
        self.dn_btn.connect('clicked', self.on_fine_down)
        self.left_btn.connect('clicked', self.on_fine_left)
        self.right_btn.connect('clicked', self.on_fine_right)
        self.home_btn.connect('clicked', self.on_home)
        
        # rotate sample section
        move_gonio_frame = gtk.Frame('<b>Rotate Sample By:</b>')    
        move_gonio_frame.set_shadow_type(gtk.SHADOW_NONE)
        move_gonio_frame.get_label_widget().set_use_markup(True)
        move_gonio_bbox = gtk.Table(1,3,True)
        move_gonio_bbox.set_row_spacings(3)
        move_gonio_bbox.set_col_spacings(3)
        move_gonio_bbox.set_border_width(3)
        move_gonio_align = gtk.Alignment()
        move_gonio_align.set(0.5,0.5,1,1)
        move_gonio_align.set_padding(0,0,12,0)
        self.decr_90_btn = gtk.Button('-90')
        move_gonio_bbox.attach(self.decr_90_btn, 0,1,0,1)
        self.incr_90_btn = gtk.Button('+90')
        move_gonio_bbox.attach(self.incr_90_btn, 1,2,0,1)
        self.incr_180_btn = gtk.Button('+180')
        move_gonio_bbox.attach(self.incr_180_btn, 2,3,0,1)
        move_gonio_align.add(move_gonio_bbox)
        move_gonio_frame.add(move_gonio_align)
        self.side_panel.pack_start(move_gonio_frame,expand=False, fill=False)
        self.decr_90_btn.connect('clicked',self.on_decr_omega)
        self.incr_90_btn.connect('clicked',self.on_incr_omega)
        self.incr_180_btn.connect('clicked',self.on_double_incr_omega)
        
        # centering section
        align_frame = gtk.Frame('<b>Centering:</b>')    
        align_frame.set_shadow_type(gtk.SHADOW_NONE)
        align_frame.get_label_widget().set_use_markup(True)
        align_bbox = gtk.Table(1,3,True)
        align_bbox.set_row_spacings(3)
        align_bbox.set_col_spacings(3)
        align_bbox.set_border_width(3)
        align_align = gtk.Alignment()
        align_align.set(0.5,0.5,1,1)
        align_align.set_padding(0,0,12,0)
        self.loop_btn = gtk.Button('Loop')
        align_bbox.attach(self.loop_btn, 0,1,0,1)
        self.crystal_btn = gtk.Button('Crystal')
        align_bbox.attach(self.crystal_btn, 1,2,0,1)
        self.click_btn = gtk.ToggleButton('Click')
        align_bbox.attach(self.click_btn, 2,3,0,1)
        align_align.add(align_bbox)
        align_frame.add(align_align)
        self.side_panel.pack_start(align_frame,expand=False, fill=False)
        self.click_btn.connect('clicked', self.toggle_click_centering)
        self.loop_btn.connect('clicked', self.on_center_loop)
        self.crystal_btn.connect('clicked', self.on_center_crystal)
        #self.loop_btn.set_sensitive(False)
        #self.crystal_btn.set_sensitive(False)
        
        # status area
        self.pos_label = gtk.Label("<tt>%4d,%4d [%6.3f, %6.3f mm]</tt>" % (0,0,0,0))
        self.pos_label.set_use_markup(True)
        self.pos_label.set_alignment(1,0.5)        
        
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
        pos_hbox = gtk.HBox(False,6)
        pos_hbox.pack_end(self.pos_label,expand=True, fill=True)
        self.save_btn = gtk.Button(stock='gtk-save')
        self.save_btn.connect('clicked', self.on_save)
        pos_hbox.pack_start(self.save_btn, expand=False, fill=True)
        vbox2.pack_end(pos_hbox, expand=False, fill=False)
        
        # Adjustment area         
        self.lighting_scale = gtk.HScale()
        #self.lighting_scale.set_draw_value(False)
        self.lighting_scale.set_value_pos(gtk.POS_RIGHT)
        self.lighting_scale.set_digits(1)
        self.lighting_scale.set_adjustment(gtk.Adjustment(self.lighting,0,10,0.1,0,0))
        self.lighting_scale.set_update_policy(gtk.UPDATE_CONTINUOUS)
        
        self.contrast_scale = gtk.HScale()
        #self.contrast_scale.set_draw_value(False)
        self.contrast_scale.set_value_pos(gtk.POS_RIGHT)
        self.contrast_scale.set_digits(0)
        self.contrast_scale.set_adjustment(gtk.Adjustment(self.contrast,0,100,1,0,0))
        self.contrast_scale.set_update_policy(gtk.UPDATE_CONTINUOUS)
        
        adjustment_box = gtk.HBox(False, 6)
        adjustment_box.pack_start(gtk.Label('Lighting: '), expand=False, fill=False)
        adjustment_box.pack_start(self.lighting_scale, expand=True, fill=True)
        adjustment_box.pack_start(gtk.Label('Contrast: '), expand=False, fill=False)
        adjustment_box.pack_start(self.contrast_scale,expand=True, fill=True)
        
        self.contrast_scale.connect('value-changed',self.on_contrast_changed)
        self.lighting_scale.connect('value-changed',self.on_lighting_changed)
        vbox2.pack_start(adjustment_box,expand=False,fill=False)
        self.pack_end(vbox2, expand=False, fill=False)
        self.show_all()

def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("SampleViewer")
    book = gtk.Notebook()
    win.add(book)
    myviewer = SampleViewer()
    book.append_page(myviewer, tab_label=gtk.Label('Sample Viewer') )
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
