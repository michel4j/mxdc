import gtk, gobject, pango
import sys, time, os
import math
from mxdc.widgets.dialogs import save_selector
from mxdc.widgets.video import VideoWidget
from bcm.engine.scripting import get_scripts 
from bcm.protocol import ca
from bcm.utils.video import add_decorations

COLOR_MAPS = [None, 'Spectral','hsv','jet', 'RdYlGn','hot', 'PuBu']        

class SampleViewer(gtk.HBox):
    def __init__(self, beamline):
        gtk.HBox.__init__(self,False,6)
        self.__register_icons()
        self._timeout_id = None
        self._click_centering  = False
        self._colormap = 0

        self.contrast = 0   
        self.beamline = beamline

        # assign devices
        self.omega = self.beamline.goniometer.omega
        self.sample_x = self.beamline.sample_stage.x
        self.sample_y1 = self.beamline.sample_stage.y
        self.sample_y2 = self.beamline.sample_stage.z
        self.beam_width = self.beamline.collimator.width
        self.beam_height = self.beamline.collimator.height
        self.beam_x = self.beamline.collimator.x
        self.beam_y = self.beamline.collimator.y
        self.cross_x = self.beamline.registry['camera_center_x']
        self.cross_y = self.beamline.registry['camera_center_y']
        self.zoom = self.beamline.registry['sample_zoom']
        self.camera = self.beamline.sample_video
        
        self.backlight = self.beamline.sample_backlight
        self.sidelight = self.beamline.sample_sidelight

        #self.on_change() #initialize display variables
        self.create_widgets()
        
        self._tick_size = 8
         
        # initialize measurement variables
        self.measuring = False
        self.measure_x1 = 0
        self.measure_x2 = 0
        self.measure_y1 = 0
        self.measure_y2 = 0
        
        self.video.connect('motion_notify_event', self.on_mouse_motion)
        self.video.connect('button_press_event', self.on_image_click)
        self.video.set_overlay_func(self._overlay_function)
        self.video.connect('realize', self.on_realize)
        self.zoom.connect('changed', self.on_change)              
        self.connect("destroy", lambda x: self.stop())
        

    def _gonio_is_moving(self):
        return ( self.sample_x.is_moving() or self.sample_y1.is_moving() or self.sample_y2.is_moving() or self.omega.is_moving() )
    
    def __del__(self):
        self.video.stop()

    def __register_icons(self):
        items = [('sv-save', '_Save Snapshot', 0, 0, None),]

        # We're too lazy to make our own icons, so we use regular stock icons.
        aliases = [('sv-save', gtk.STOCK_SAVE),]

        gtk.stock_add(items)
        factory = gtk.IconFactory()
        factory.add_default()
        for new_stock, alias in aliases:
            icon_set = gtk.icon_factory_lookup_default(alias)
            factory.add(new_stock, icon_set)
                                        
    def stop(self, win=None):
        self.video.stop()
                   
    def save_image(self, filename):
        ftype = filename.split('.')[-1]
        if ftype == 'jpg': 
            ftype = 'jpeg'
        img = add_decorations(self.beamline, self.camera.get_frame())
        img.save(filename)
            
    def draw_cross(self, pixmap):
        x = int(self.cross_x.get() * self.video.scale_factor)
        y = int(self.cross_y.get() * self.video.scale_factor)
        pixmap.draw_line(self.video.ol_gc, x-self._tick_size, y, x+self._tick_size, y)
        pixmap.draw_line(self.video.ol_gc, x, y-self._tick_size, x, y+self._tick_size)
        return

    def draw_slits(self, pixmap):
        
        beam_width = self.beam_width.get_position()
        beam_height = self.beam_height.get_position()
        slits_x = self.beam_x.get_position()
        slits_y = self.beam_y.get_position()
        cross_x = self.cross_x.get()
        cross_y = self.cross_y.get()
        
        self.slits_width  = beam_width / self.pixel_size
        self.slits_height = beam_height / self.pixel_size
        if self.slits_width  >= self.video.width:
            return
        if self.slits_height  >= self.video.height:
            return
        x = int((cross_x - (slits_x / self.pixel_size)) * self.video.scale_factor)
        y = int((cross_y - (slits_y / self.pixel_size)) * self.video.scale_factor)
        hw = int(0.5 * self.slits_width * self.video.scale_factor)
        hh = int(0.5 * self.slits_height * self.video.scale_factor)
        pixmap.draw_line(self.video.ol_gc, x-hw, y-hh, x-hw, y-hh+self._tick_size)
        pixmap.draw_line(self.video.ol_gc, x-hw, y-hh, x-hw+self._tick_size, y-hh)
        pixmap.draw_line(self.video.ol_gc, x+hw, y+hh, x+hw, y+hh-self._tick_size)
        pixmap.draw_line(self.video.ol_gc, x+hw, y+hh, x+hw-self._tick_size, y+hh)

        pixmap.draw_line(self.video.ol_gc, x-hw, y+hh, x-hw, y+hh-self._tick_size)
        pixmap.draw_line(self.video.ol_gc, x-hw, y+hh, x-hw+self._tick_size, y+hh)
        pixmap.draw_line(self.video.ol_gc, x+hw, y-hh, x+hw, y-hh+self._tick_size)
        pixmap.draw_line(self.video.ol_gc, x+hw, y-hh, x+hw-self._tick_size, y-hh)
        return
        
    def draw_measurement(self, pixmap):
        if self.measuring == True:
            x1 = self.measure_x1
            y1 = self.measure_y1
            x2 = self.measure_x2
            y2 = self.measure_y2
            dist = self.pixel_size * math.sqrt((x2 - x1) ** 2.0 + (y2 - y1) ** 2.0) / self.video.scale_factor
            x1, x2, y1, y2 = int(x1), int(y1), int(x2), int(y2)
            pixmap.draw_line(self.video.ol_gc, x1, x2, y1, y2)
            self.pango_layout.set_text("%5.4f mm" % dist)
            w,h = self.pango_layout.get_pixel_size()
            pixmap.draw_layout(self.video.pl_gc, self.video.width -w-4, 0, self.pango_layout)      
        else:
            self.pango_layout.set_text("")
        return True

    def calc_position(self,x,y):
        im_x = int( float(x)/self.video.scale_factor)
        im_y = int( float(y)/self.video.scale_factor)
        x_offset = self.cross_x.get() - im_x
        y_offset = self.cross_y.get() - im_y
        xmm = x_offset * self.pixel_size
        ymm = y_offset * self.pixel_size
        return (im_x, im_y, xmm, ymm)

    def toggle_click_centering(self, widget=None):
        if self._click_centering == True:
            self._click_centering = False
        else:
            self._click_centering = True
        return False

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
        self.side_panel = gtk.VBox(False, 2)
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
        zoomalign.set_padding(0,0,6,0)
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
        move_sample_align.set_padding(0,0,6,0)
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
        move_gonio_align.set_padding(0,0,6,0)
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
        align_align.set_padding(0,0,6,0)
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

        # light/save section
        hline = gtk.HSeparator()
        hline.set_size_request(-1,24)
        self.side_panel.pack_start(hline, expand=False, fill=False)

        # status area
        self.pos_label = gtk.Label("<tt>%4d,%4d [%6.3f, %6.3f mm]</tt>" % (0,0,0,0))
        self.pos_label.set_use_markup(True)
        self.pos_label.set_alignment(1,0.5)        
        
        #Video Area
        vbox2 = gtk.VBox(False,2)
        videoframe = gtk.AspectFrame( ratio=640.0/480.0, obey_child=False)
        videoframe.set_shadow_type(gtk.SHADOW_IN)
        self.video = VideoWidget(self.camera)
        self.video.set_size_request(420, 315)
        videoframe.add(self.video)
        self.save_btn = gtk.Button(stock='sv-save')
        self.save_btn.connect('clicked', self.on_save)
        vbox2.pack_start(videoframe, expand=True, fill=True)
        vbox2.pack_end(self.pos_label, expand=False, fill=False)
        
        # Adjustment area         
        self.lighting_scale = gtk.HScale()
        self.lighting_scale.set_value_pos(gtk.POS_RIGHT)
        self.lighting_scale.set_digits(1)
        self.lighting_scale.set_adjustment(gtk.Adjustment(0.0,0,5, 0.1,0,0))
        self.lighting_scale.set_update_policy(gtk.UPDATE_CONTINUOUS)
        
        self.contrast_scale = gtk.HScale()
        self.contrast_scale.set_value_pos(gtk.POS_RIGHT)
        self.contrast_scale.set_digits(0)
        self.contrast_scale.set_adjustment(gtk.Adjustment(self.contrast,0,100,1,0,0))
        self.contrast_scale.set_update_policy(gtk.UPDATE_CONTINUOUS)
        
        adjustment_box = gtk.HBox(False, 2)
        adjustment_box.pack_start(gtk.Label('Lighting: '), expand=False, fill=False)
        adjustment_box.pack_start(self.lighting_scale, expand=True, fill=True)
        #adjustment_box.pack_start(gtk.Label('Contrast: '), expand=False, fill=False)
        #adjustment_box.pack_start(self.contrast_scale,expand=True, fill=True)
        
        self.contrast_scale.connect('value-changed',self.on_contrast_changed)
        self.lighting_scale.connect('value-changed',self.on_lighting_changed)
        self.side_panel.pack_start(adjustment_box,expand=False,fill=False)
        self.side_panel.pack_end(self.save_btn, expand=False, fill=False)
        self.pack_end(vbox2, expand=True, fill=True)
        self.show_all()
        
        self._scripts = get_scripts()

    def _overlay_function(self, pixmap):
        self.draw_cross(pixmap)
        self.draw_slits(pixmap)
        self.draw_measurement(pixmap)
        return True     
        
    
    # callbacks
    def on_realize(self, obj):
        self.pango_layout = self.video.create_pango_layout("")
        self.pango_layout.set_font_description(pango.FontDescription('Monospace 8'))
        
    def on_change(self, obj=None, arg=None):
        self.zoom_factor = self.zoom.get_position()
        self.pixel_size = 5.34e-3 * math.exp( -0.18 * self.zoom_factor)

    def on_save(self, obj=None, arg=None):
        img_filename = save_selector()
        if not img_filename:
            return
        if os.access(os.path.split(img_filename)[0], os.W_OK):
            self.save_image(img_filename)
    
    def on_center_loop(self,widget):
        script = self._scripts['CenterSample']
        self.side_panel.set_sensitive(False)
        script.connect('done', self.done_centering)
        script.connect('error', self.done_centering)
        script.start(crystal=False)
        return True
              
    def on_center_crystal(self, widget):
        script = self._scripts['CenterSample']
        self.side_panel.set_sensitive(False)
        script.connect('done', self.done_centering)
        script.connect('error', self.done_centering)
        script.start(crystal=True)
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
        #print event.state.value_names
        if 'GDK_BUTTON2_MASK' in event.state.value_names:
            self.measure_x2, self.measure_y2, = event.x, event.y
        else:
            self.measuring = False
        return True

    def on_image_click(self, widget, event):

        if event.button == 1:
            if self._click_centering == False or self._gonio_is_moving():
                return True
            self.center_pixel(event.x, event.y)
        elif event.button == 2:
            self.measuring = True
            self.measure_x1, self.measure_y1 = event.x,event.y
            self.measure_x2, self.measure_y2 = event.x,event.y
        elif event.button == 3:
            self._colormap = (self._colormap + 1) % len( COLOR_MAPS)
            self.video.set_colormap(COLOR_MAPS[self._colormap])
            print COLOR_MAPS[self._colormap]

        return True
    
                
    def on_fine_up(self,widget):
        tmp_omega = int(round(self.omega.get_position()))
        sin_w = math.sin(tmp_omega * math.pi / 180)
        cos_w = math.cos(tmp_omega * math.pi / 180)
        step_size = self.pixel_size * 10.0
        self.sample_y1.move_by( step_size * sin_w * 0.5 )
        self.sample_y2.move_by( -step_size * cos_w * 0.5 )   
        return True
        
    def on_fine_down(self,widget):
        tmp_omega = int(round(self.omega.get_position()))
        sin_w = math.sin(tmp_omega * math.pi / 180)
        cos_w = math.cos(tmp_omega * math.pi / 180)
        step_size = self.pixel_size * 10.0
        self.sample_y1.move_by( -step_size * sin_w * 0.5 )
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
        self.sample_x.move_to( 0.0 )
        return True
                
    
    def on_contrast_changed(self,widget):
        self.contrast = self.contrast_scale.get_value()
        return True
        
    def on_lighting_changed(self,widget):
        self.lighting = self.lighting_scale.get_value()
        self.light.move_to( self.lighting )
        return True
                    
