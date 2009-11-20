import sys, time, os
import math
import gtk
import gobject
import pango
import gtk.glade
from mxdc.widgets.dialogs import save_selector
from mxdc.widgets.video import VideoWidget
from mxdc.widgets.misc import ActiveHScale
from bcm.engine.scripting import get_scripts 
from bcm.protocol import ca
from bcm.beamline.interfaces import IBeamline
from bcm.utils.video import add_decorations
from bcm.utils.log import get_module_logger
from twisted.python.components import globalRegistry

_logger = get_module_logger('mxdc.sampleviewer')

COLOR_MAPS = [None, 'Spectral','hsv','jet', 'RdYlGn','hot', 'PuBu']        
_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class SampleViewer(gtk.Frame):
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        
        self._timeout_id = None
        self._click_centering  = False
        self._colormap = 0
        self._tick_size = 10
                
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
            _logger.warning('No registered beamline found.')

        self._create_widgets()

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

                                        
    def save_image(self, filename):
        ftype = filename.split('.')[-1]
        if ftype == 'jpg': 
            ftype = 'jpeg'
        img = self.beamline.sample_video.get_frame()
        try:
            bw = self.beamline.beam_w.get_position()
            bh = self.beamline.beam_h.get_position()
            bx = self.beamline.beam_x.get_position()
            by = self.beamline.beam_y.get_position()
            pix_size = self.beamline.sample_video.resolution
            cx = self.beamline.registry['camera_center_x'].get()
            cy = self.beamline.registry['camera_center_y'].get()
        except ca.ChannelAccessError:
            pass
        else:
            # slit position and sizes in pixels
            w = int(bw / pix_size) 
            h = int(bh / pix_size)
            x = int((cx - (bx / pix_size)))
            y = int((cy - (by / pix_size)))
        
            img = add_decorations(img, x, y, w, h)
        img.save(filename)
            
    def draw_slits(self, pixmap):
        w, h = pixmap.get_size()
        pix_size = self.beamline.sample_video.resolution      
        try:      
            bw = self.beamline.beam_w.get_position()
            bh = self.beamline.beam_h.get_position()
            bx = self.beamline.beam_x.get_position()
            by = self.beamline.beam_y.get_position()
            cx = self.beamline.registry['camera_center_x'].get()
            cy = self.beamline.registry['camera_center_y'].get()
        except:
            cx = w//2
            bw = bh = 1.0
            bx = by = 0
            cy = h//2
        
        # slit sizes in pixels
        sw = bw / pix_size 
        sh = bh / pix_size
        if sw  >= w or sh >= h:
            return
        x = int((cx - (bx / pix_size)) * self.video.scale)
        y = int((cy - (by / pix_size)) * self.video.scale)
        hw = int(0.5 * sw * self.video.scale)
        hh = int(0.5 * sh * self.video.scale)
        tick = int(self._tick_size * self.video.scale)
        
        pixmap.draw_line(self.video.ol_gc, x-hw, y-hh, x-hw, y-hh+tick)
        pixmap.draw_line(self.video.ol_gc, x-hw, y-hh, x-hw+tick, y-hh)
        pixmap.draw_line(self.video.ol_gc, x+hw, y+hh, x+hw, y+hh-tick)
        pixmap.draw_line(self.video.ol_gc, x+hw, y+hh, x+hw-tick, y+hh)
        pixmap.draw_line(self.video.ol_gc, x-hw, y+hh, x-hw, y+hh-tick)
        pixmap.draw_line(self.video.ol_gc, x-hw, y+hh, x-hw+tick, y+hh)
        pixmap.draw_line(self.video.ol_gc, x+hw, y-hh, x+hw, y-hh+tick)
        pixmap.draw_line(self.video.ol_gc, x+hw, y-hh, x+hw-tick, y-hh)
        pixmap.draw_line(self.video.ol_gc, x-tick, y, x+tick, y)
        pixmap.draw_line(self.video.ol_gc, x, y-tick, x, y+tick)
        return
        
    def draw_measurement(self, pixmap):
        pix_size = self.beamline.sample_video.resolution
        w, h = pixmap.get_size()
        if self.measuring == True:
            x1 = self.measure_x1
            y1 = self.measure_y1
            x2 = self.measure_x2
            y2 = self.measure_y2
            dist = pix_size * math.sqrt((x2 - x1) ** 2.0 + (y2 - y1) ** 2.0) / self.video.scale
            x1, x2, y1, y2 = int(x1), int(y1), int(x2), int(y2)
            pixmap.draw_line(self.video.ol_gc, x1, x2, y1, y2)            
            self.meas_label.set_markup("<small><tt>Measurement: %5.4f mm</tt></small>" % dist)
        else:
            self.meas_label.set_markup("<small><tt>FPS: %0.1f</tt></small>" % self.video.fps)
        return True

    def _img_position(self,x,y):
        im_x = int(float(x) / self.video.scale)
        im_y = int(float(y) / self.video.scale)
        try:
            cx = self.beamline.registry['camera_center_x'].get()
            cy = self.beamline.registry['camera_center_y'].get()
        except  ca.ChannelAccessError:
            cx, cy = self.beamline.sample_video.size
            cx //=2
            cy //=2
        xmm = (cx - im_x) * self.beamline.sample_video.resolution
        ymm = (cy - im_y) * self.beamline.sample_video.resolution
        return (im_x, im_y, xmm, ymm)

    def toggle_click_centering(self, widget=None):
        if self._click_centering == True:
            self._click_centering = False
        else:
            self._click_centering = True
        return False

    def center_pixel(self, x, y):
        tmp_omega = int(self.beamline.goniometer.omega.get_position() )
        sin_w = math.sin(tmp_omega * math.pi / 180)
        cos_w = math.cos(tmp_omega * math.pi / 180)
        im_x, im_y, xmm, ymm = self._img_position(x,y)
        self.beamline.sample_stage.x.move_by(-xmm)
        self.beamline.sample_stage.y.move_by(-ymm * sin_w)
        self.beamline.sample_stage.z.move_by(ymm * cos_w)

    def _create_widgets(self):
        self._xml = gtk.glade.XML(os.path.join(_DATA_DIR, 'sample_viewer.glade'), 
                                  'sample_viewer')
        self._xml_popup = gtk.glade.XML(os.path.join(_DATA_DIR, 'sample_viewer.glade'), 
                                  'colormap_popup')
        widget = self._xml.get_widget('sample_viewer')
        self.cmap_popup = self._xml_popup.get_widget('colormap_popup')
        self.cmap_popup.set_title('Pseudo Color Mode')
        
        # connect colormap signals
        cmap_items = ['cmap_default', 'cmap_spectral','cmap_hsv','cmap_jet', 'cmap_ryg','cmap_hot', 'cmap_pubu']
        for i in range(len(cmap_items)):
            w = self._xml_popup.get_widget(cmap_items[i])
            w.connect('activate', self.on_cmap_activate, i)
        
        self.add(widget)
        
        self.side_panel = self._xml.get_widget('side_panel')
        
        #zoom
        self.zoom_out_btn = self._xml.get_widget('zoom_out_btn')
        self.zoom_in_btn = self._xml.get_widget('zoom_in_btn')
        self.zoom_100_btn = self._xml.get_widget('zoom_100_btn')
        self.zoom_out_btn.connect('clicked', self.on_zoom_out)
        self.zoom_in_btn.connect('clicked', self.on_zoom_in)
        self.zoom_100_btn.connect('clicked', self.on_unzoom)
        
        # move sample
        self.up_btn = self._xml.get_widget('up_btn')
        self.dn_btn = self._xml.get_widget('dn_btn')
        self.left_btn = self._xml.get_widget('left_btn')
        self.right_btn = self._xml.get_widget('right_btn')
        self.home_btn = self._xml.get_widget('home_btn')
        self.up_btn.connect('clicked', self.on_fine_up)
        self.dn_btn.connect('clicked', self.on_fine_down)
        self.left_btn.connect('clicked', self.on_fine_left)
        self.right_btn.connect('clicked', self.on_fine_right)        
        self.home_btn.connect('clicked', self.on_home)
        
        # rotate sample
        self.decr_90_btn = self._xml.get_widget('decr_90_btn')
        self.incr_90_btn = self._xml.get_widget('incr_90_btn')
        self.incr_180_btn = self._xml.get_widget('incr_180_btn')
        self.decr_90_btn.connect('clicked',self.on_decr_omega)
        self.incr_90_btn.connect('clicked',self.on_incr_omega)
        self.incr_180_btn.connect('clicked',self.on_double_incr_omega)
        
        # centering 
        self.loop_btn = self._xml.get_widget('loop_btn')
        self.crystal_btn = self._xml.get_widget('crystal_btn')
        self.click_btn = self._xml.get_widget('click_btn')
        self.click_btn.connect('clicked', self.toggle_click_centering)
        self.loop_btn.connect('clicked', self.on_center_loop)
        self.crystal_btn.connect('clicked', self.on_center_crystal)


        # status, save, etc
        self.pos_label = self._xml.get_widget('status_label')
        self.meas_label = self._xml.get_widget('meas_label')
        self.save_btn = self._xml.get_widget('save_btn')
        self.save_btn.connect('clicked', self.on_save)
        
        #Video Area
        self.video_frame = self._xml.get_widget('video_adjuster')
        self.video = VideoWidget(self.beamline.sample_video)
        self.video.set_size_request(480,360)
        self.video_frame.add(self.video)
        
        # Lighting
        self.lighting_box =   self._xml.get_widget('lighting_box')       
        self.side_light = ActiveHScale(self.beamline.sample_sidelight)
        self.back_light = ActiveHScale(self.beamline.sample_backlight)
        self.side_light.set_update_policy(gtk.UPDATE_DELAYED)
        self.back_light.set_update_policy(gtk.UPDATE_DELAYED)
        self.lighting_box.attach(self.side_light, 1,2,0,1)
        self.lighting_box.attach(self.back_light, 1,2,1,2)
        
        self._scripts = get_scripts()

    def _overlay_function(self, pixmap):
        self.draw_slits(pixmap)
        self.draw_measurement(pixmap)
        return True     
        
    
    # callbacks
    def on_cmap_activate(self, obj, cmap):
        self.video.set_colormap(COLOR_MAPS[cmap])
        
    def on_realize(self, obj):
        self.pango_layout = self.video.create_pango_layout("")
        self.pango_layout.set_font_description(pango.FontDescription('Monospace 8'))
        
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
        self.beamline.sample_video.zoom(10)
        return True

    def on_zoom_out(self,widget):
        self.beamline.sample_video.zoom(1)
        return True

    def on_unzoom(self,widget):
        self.beamline.sample_video.zoom(6)
        return True

    def on_incr_omega(self,widget):
        cur_omega = int(self.beamline.goniometer.omega.get_position() )
        target = (cur_omega + 90)
        target = (target > 360) and (target % 360) or target
        self.beamline.goniometer.omega.move_to(target)
        return True

    def on_decr_omega(self,widget):
        cur_omega = int(self.beamline.goniometer.omega.get_position() )
        target = (cur_omega - 90)
        target = (target < -180) and (target % 360) or target
        self.beamline.goniometer.omega.move_to(target)
        return True

    def on_double_incr_omega(self,widget):
        cur_omega = int(self.beamline.goniometer.omega.get_position() )
        target = (cur_omega + 180)
        target = (target > 360) and (target % 360) or target
        self.beamline.goniometer.omega.move_to(target)
        return True
                
    def on_mouse_motion(self, widget, event):
        if event.is_hint:
            x, y, state = event.window.get_pointer()
        else:
            x = event.x; y = event.y
        im_x, im_y, xmm, ymm = self._img_position(x,y)
        self.pos_label.set_markup("<small><tt>%4d,%4d [%6.3f, %6.3f mm]</tt></small>" % (im_x, im_y, xmm, ymm))
        #print event.state.value_names
        if 'GDK_BUTTON2_MASK' in event.state.value_names:
            self.measure_x2, self.measure_y2, = event.x, event.y
        else:
            self.measuring = False
        return True

    def on_image_click(self, widget, event):
        if event.button == 1:
            if self._click_centering == False:
                return True
            self.center_pixel(event.x, event.y)
        elif event.button == 2:
            self.measuring = True
            self.measure_x1, self.measure_y1 = event.x,event.y
            self.measure_x2, self.measure_y2 = event.x,event.y
        elif event.button == 3:
            self.cmap_popup.popup(None, None, None, event.button,event.time)
        return True  
                
    def on_fine_up(self,widget):
        tmp_omega = int(round(self.beamline.goniometer.omega.get_position()))
        sin_w = math.sin(tmp_omega * math.pi / 180)
        cos_w = math.cos(tmp_omega * math.pi / 180)
        step_size = self.beamline.sample_video.resolution * 10.0
        self.beamline.sample_stage.y.move_by( step_size * sin_w * 0.5 )
        self.beamline.sample_stage.z.move_by( -step_size * cos_w * 0.5 )   
        return True
        
    def on_fine_down(self,widget):
        tmp_omega = int(round(self.beamline.goniometer.omega.get_position()))
        sin_w = math.sin(tmp_omega * math.pi / 180)
        cos_w = math.cos(tmp_omega * math.pi / 180)
        step_size = self.beamline.sample_video.resolution * 10.0
        self.beamline.sample_stage.y.move_by( -step_size * sin_w * 0.5)
        self.beamline.sample_stage.z.move_by( step_size * cos_w * 0.5)   
        return True
        
    def on_fine_left(self,widget):
        step_size = self.beamline.sample_video.resolution * 10.0
        self.beamline.sample_stage.x.move_by( step_size * 0.5 )
        return True
        
    def on_fine_right(self,widget):
        step_size = self.beamline.sample_video.resolution * 10.0
        self.beamline.sample_stage.x.move_by( -step_size * 0.5 )
        return True
        
    def on_home(self,widget):
        self.beamline.sample_stage.x.move_to( 22.0 )
        return True
                
                        
