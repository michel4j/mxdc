import gtk, gobject
import sys, time, os
import math
from Dialogs import save_selector
from VideoWidget import VideoWidget
from bcm.tools.scripting import Script
from bcm.scripts.misc import center_sample 
from bcm.protocols import ca

        
class SampleViewer(gtk.HBox):
    def __init__(self, bl):
        gtk.HBox.__init__(self,False,6)
        
        self._timeout_id = None
        self._click_centering  = False
        self._last_click_time = time.time()
        
        self.contrast = 0   
        
        # assign devices
        self.omega = bl.omega
        self.sample_x = bl.sample_x
        self.sample_y1 = bl.sample_y
        self.sample_y2 = bl.sample_z
        self.beam_width = bl.beam_w
        self.beam_height = bl.beam_h
        self.beam_x = bl.beam_x
        self.beam_y = bl.beam_y
        self.zoom = bl.sample_zoom
        self.light = bl.sample_light
        self.cross_x = bl.cross_x
        self.cross_y = bl.cross_y
        self.camera = bl.sample_cam
        
        self.lighting = self.light.get_position()

        self.on_change() #initialize display variables
        self.create_widgets()
        
        self._tick_size = 5
        self._gonio_state = 0
        
        # initialize measurement variables
        self.measuring = False
        self.measure_x1 = 0
        self.measure_x2 = 0
        self.measure_y1 = 0
        self.measure_y2 = 0
        
        self.video.connect('motion_notify_event', self.on_mouse_motion)
        self.video.connect('button_press_event', self.on_image_click)
        self.video.set_overlay_func(self._overlay_function)
        
        self.beam_width.connect('changed', self.on_change)
        self.beam_height.connect('changed', self.on_change)
        self.beam_x.connect('changed', self.on_change)
        self.beam_y.connect('changed', self.on_change)
        self.cross_x.connect('changed', self.on_change)
        self.cross_y.connect('changed', self.on_change)
        self.zoom.connect('changed', self.on_change)              
        self.connect("destroy", lambda x: self.stop())

    def __del__(self):
        self.video.stop()
                                        
    def stop(self, win=None):
        self.video.stop()
                   
    def save_image(self, filename):
        ftype = filename.split('.')[-1]
        if ftype == 'jpg': 
            ftype = 'jpeg'
        self.video_frame.save(filename, ftype)
            
    def draw_cross(self, pixmap):
        x = int(self.cross_x_position * self.video.scale_factor)
        y = int(self.cross_y_position * self.video.scale_factor)
        pixmap.draw_line(self.gc, x-self._tick_size, y, x+self._tick_size, y)
        pixmap.draw_line(self.gc, x, y-self._tick_size, x, y+self._tick_size)
        return

    def draw_slits(self, pixmap):
        
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
        x = int((cross_x - (slits_x / self.pixel_size)) * self.video.scale_factor)
        y = int((cross_y - (slits_y / self.pixel_size)) * self.video.scale_factor)
        hw = int(0.5 * self.slits_width * self.video.scale_factor)
        hh = int(0.5 * self.slits_height * self.video.scale_factor)
        pixmap.draw_line(self.gc, x-hw, y-hh, x-hw, y-hh+self._tick_size)
        pixmap.draw_line(self.gc, x-hw, y-hh, x-hw+self._tick_size, y-hh)
        pixmap.draw_line(self.gc, x+hw, y+hh, x+hw, y+hh-self._tick_size)
        pixmap.draw_line(self.gc, x+hw, y+hh, x+hw-self._tick_size, y+hh)

        pixmap.draw_line(self.gc, x-hw, y+hh, x-hw, y+hh-self._tick_size)
        pixmap.draw_line(self.gc, x-hw, y+hh, x-hw+self._tick_size, y+hh)
        pixmap.draw_line(self.gc, x+hw, y-hh, x+hw, y-hh+self._tick_size)
        pixmap.draw_line(self.gc, x+hw, y-hh, x+hw-self._tick_size, y-hh)
        return
        
    def draw_measurement(self, pixmap):
        if self.measuring == True:
            x1 = self.measure_x1
            y1 = self.measure_y1
            x2 = self.measure_x2
            y2 = self.measure_y2
            dist = self.pixel_size * math.sqrt((x2 - x1) ** 2.0 + (y2 - y1) ** 2.0) / self.video.scale_factor
            x1, x2, y1, y2 = int(x1), int(y1), int(x2), int(y2)
            pixmap.draw_line(self.gc, x1, x2, y1, y2)
            self.pangolayout.set_text("%5.4f mm" % dist)
        return True

    def calc_position(self,x,y):
        im_x = int( float(x)/self.video.scale_factor)
        im_y = int( float(y)/self.video.scale_factor)
        x_offset = self.cross_x_position - im_x
        y_offset = self.cross_y_position - im_y
        xmm = x_offset * self.pixel_size
        ymm = y_offset * self.pixel_size
        return (im_x, im_y, xmm, ymm)

    def toggle_click_centering(self, widget):
        if self._click_centering == True:
            self._click_centering = False
        else:
            self._click_centering = True
            self._last_click_time = time.time()
        return True

    def center_pixel(self, x, y):
        tmp_omega = int(round(self.omega.get_position()))
        sin_w = math.sin(tmp_omega * math.pi / 180)
        cos_w = math.cos(tmp_omega * math.pi / 180)
        im_x, im_y, xmm, ymm = self.calc_position(x,y)
        self.sample_x.move_by( -xmm )
        #if   abs(sin_w) == 1:
        self.sample_y1.move_by( -ymm * sin_w  )
        #elif abs(cos_w) == 1:
        self.sample_y2.move_by( ymm * cos_w  )

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
        self.zoom_out_btn.add( gtk.image_new_from_stock('gtk-zoom-out',gtk.ICON_SIZE_SMALL_TOOLBAR))
        self.zoom_in_btn.add( gtk.image_new_from_stock('gtk-zoom-in',gtk.ICON_SIZE_SMALL_TOOLBAR))
        self.zoom_100_btn.add( gtk.image_new_from_stock('gtk-zoom-100',gtk.ICON_SIZE_SMALL_TOOLBAR))
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
        videoframe = gtk.AspectFrame( ratio=640.0/480.0, obey_child=False)
        videoframe.set_shadow_type(gtk.SHADOW_IN)
        self.video = VideoWidget(self.camera)
        self.video.set_size_request(480, 360)
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
        self.lighting_scale.set_value_pos(gtk.POS_RIGHT)
        self.lighting_scale.set_digits(1)
        self.lighting_scale.set_adjustment(gtk.Adjustment(self.lighting,0,10,0.1,0,0))
        self.lighting_scale.set_update_policy(gtk.UPDATE_CONTINUOUS)
        
        self.contrast_scale = gtk.HScale()
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

    def _overlay_function(self, pixmap):
        self.draw_cross(pixmap)
        self.draw_slits(pixmap)
        self.draw_measurement(pixmap)
        return True     
        
    
    # callbacks
    def on_change(self, obj=None, arg=None):
        self.beam_width_position = self.beam_width.get_position()
        self.beam_height_position = self.beam_height.get_position()
        self.slits_x_position = self.slits_x.get_position()
        self.slits_y_position = self.slits_y.get_position()
        self.cross_x_position = self.cross_x.get_position()
        self.cross_y_position = self.cross_y.get_position()
        self.zoom_factor = self.zoom.get_position()
        self.pixel_size = 5.34e-3 * math.exp( -0.18 * self.zoom_factor)
        self.lighting = self.light.get_position()

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
              
    def on_center_crystal(self, widget):
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
    
    def on_zoom_in(self,widget):
        #cur_zoom = self.zoom.get_position()
        #next_zoom = (cur_zoom < 13) and int(cur_zoom + 1) or int(cur_zoom)
        self.zoom.move_to(10)
        return True

    def on_zoom_out(self,widget):
        #cur_zoom = self.zoom.get_position()
        #next_zoom = (cur_zoom > 1) and int(cur_zoom - 1) or int(cur_zoom)
        self.zoom.move_to(1)
        return True

    def on_unzoom(self,widget):
        self.zoom.move_to(5)
        return True

    def on_incr_omega(self,widget):
        cur_omega = int(self.omega.get_position() )
        target = (cur_omega + 90)
        target = (target > 360) and (target % 360) or target
        self.omega.move_to(target)
        return True

    def on_decr_omega(self,widget):
        cur_omega = int(self.omega.get_position() )
        target = (cur_omega - 90)
        target = (target < -180) and (target % 360) or target
        self.omega.move_to(target)
        return True

    def on_double_incr_omega(self,widget):
        cur_omega = int(self.omega.get_position() )
        target = (cur_omega + 180)
        target = (target > 360) and (target % 360) or target
        self.omega.move_to(target)
        return True
                
    def on_mouse_motion(self, widget, event):
        if event.is_hint:
            x, y, state = event.window.get_pointer()
        else:
            x = event.x; y = event.y
        im_x, im_y, xmm, ymm = self.calc_position(x,y)
        self.pos_label.set_text("<tt>%4d,%4d [%6.3f, %6.3f mm]</tt>" % (im_x, im_y, xmm, ymm))
        self.pos_label.set_use_markup(True)
        if 'GDK_BUTTON3_MASK' in event.state.value_names:
            self.measure_x2, self.measure_y2, = event.x, event.y
        else:
            self.measuring = False
        return True

    def on_image_click(self, widget, event):

        if event.button == 1:
            if self._gonio_state == 1 or self._click_centering == False:
                return True
            self._last_click_time = time.time()
            self.center_pixel(event.x, event.y)
        elif event.button == 3:
            self.measuring = True
            self.measure_x1, self.measure_y1 = event.x,event.y
            self.measure_x2, self.measure_y2 = event.x,event.y

        return True
    
                
    def on_fine_up(self,widget):
        tmp_omega = int(round(self.omega.get_position()))
        sin_w = math.sin(tmp_omega * math.pi / 180)
        cos_w = math.cos(tmp_omega * math.pi / 180)
        step_size = self.pixel_size * 10.0
        if  abs(sin_w) == 1:
            self.sample_y1.move_by( step_size * sin_w * 0.5 )
        elif abs(cos_w) == 1:
            self.sample_y2.move_by( -step_size * cos_w * 0.5 )   
        return True
        
    def on_fine_down(self,widget):
        tmp_omega = int(round(self.omega.get_position()))
        sin_w = math.sin(tmp_omega * math.pi / 180)
        cos_w = math.cos(tmp_omega * math.pi / 180)
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
                
    
    def on_contrast_changed(self,widget):
        self.contrast = self.contrast_scale.get_value()
        return True
        
    def on_lighting_changed(self,widget):
        self.lighting = 0.5 * self.lighting_scale.get_value()
        self.light.move_to( self.lighting )
        return True
                    