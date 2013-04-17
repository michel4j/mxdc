from bcm.utils.log import get_module_logger
from mxdc.utils import gui
from mxdc.widgets import dialogs
from mxdc.widgets.video import VideoWidget
import gtk
import math
import pango
import os

_logger = get_module_logger('mxdc.videoviewer')

COLOR_MAPS = [None, 'Spectral','hsv','jet', 'RdYlGn','hot', 'PuBu']        
_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class SimpleVideo(gtk.Frame):
    def __init__(self, camera):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        
        self._timeout_id = None
        self._colormap = 0
        self._tick_size = 10
        self.camera = camera       
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
        img = self.camera.get_frame()        
        img.save(filename)
                
    def draw_measurement(self, pixmap):
        pix_size = self.camera.resolution
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
        cx = 0.0
        cy = 0.0
        xmm = (cx - im_x) * self.camera.resolution
        ymm = (cy - im_y) * self.camera.resolution
        return (im_x, im_y, xmm, ymm)

    def _create_widgets(self):
        self._xml = gui.GUIFile(os.path.join(_DATA_DIR, 'simple_video'), 
                                  'simple_video')
        self._xml_popup = gui.GUIFile(os.path.join(_DATA_DIR, 'simple_video'), 
                                  'colormap_popup')
        widget = self._xml.get_widget('simple_video')
        self.cmap_popup = self._xml_popup.get_widget('colormap_popup')
        self.cmap_popup.set_title('Pseudo Color Mode')
        
        # connect colormap signals
        cmap_items = ['cmap_default', 'cmap_spectral','cmap_hsv','cmap_jet', 'cmap_ryg','cmap_hot', 'cmap_pubu']
        for i in range(len(cmap_items)):
            w = self._xml_popup.get_widget(cmap_items[i])
            w.connect('activate', self.on_cmap_activate, i)
        
        self.add(widget)

        # status, save, etc
        self.pos_label = self._xml.get_widget('status_label')
        self.meas_label = self._xml.get_widget('meas_label')
        self.save_btn = self._xml.get_widget('save_btn')
        self.save_btn.connect('clicked', self.on_save)
        
        #Video Area
        self.video_frame = self._xml.get_widget('video_adjuster')
        self.video = VideoWidget(self.camera)
        w, h = map(float, self.camera)
        self.video_frame.set(xalign=0.5, yalign=0.5, ratio=(w/h), obey_child=False)
        self.video_frame.set_size_request(480,360)
        self.video_frame.add(self.video)
        
    def _overlay_function(self, pixmap):
        self.draw_measurement(pixmap)
        return True     
        
    
    # callbacks
    def on_cmap_activate(self, obj, cmap):
        self.video.set_colormap(COLOR_MAPS[cmap])
        
    def on_realize(self, obj):
        self.pango_layout = self.video.create_pango_layout("")
        self.pango_layout.set_font_description(pango.FontDescription('Monospace 8'))
        
    def on_save(self, obj=None, arg=None):
        img_filename, _ = dialogs.select_save_file(
                                'Save Video Snapshot',
                                parent=self.get_toplevel(),
                                formats=[('PNG Image', 'png'), ('JPEG Image', 'jpg')])
        if not img_filename:
            return
        if os.access(os.path.split(img_filename)[0], os.W_OK):
            self.save_image(img_filename)
    
    def on_unmap(self, widget):
        self.videothread.pause()
        return True

    def on_no_expose(self, widget, event):
        return True
        
    def on_delete(self,widget):
        self.videothread.stop()
        return True
        
    def on_expose(self, videoarea, event):
        window = videoarea.get_window()     
        window.draw_drawable(self.othergc, self.pixmap, 0, 0, 0, 0, 
            self.width, self.height)
        return True
                    
    def on_mouse_motion(self, widget, event):
        if event.is_hint:
            x, y, _ = event.window.get_pointer()
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
        if event.button == 2:
            self.measuring = True
            self.measure_x1, self.measure_y1 = event.x,event.y
            self.measure_x2, self.measure_y2 = event.x,event.y
        elif event.button == 3:
            self.cmap_popup.popup(None, None, None, event.button,event.time)
        return True