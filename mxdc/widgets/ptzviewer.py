import sys
import time
import os
import gtk
import gtk.glade
import gobject
from mxdc.widgets.dialogs import save_selector
from mxdc.widgets.video import VideoWidget
from bcm.protocol import ca
from bcm.utils.log import get_module_logger

_logger = get_module_logger('mxdc.ptzviewer')
_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

        
class AxisViewer(gtk.Frame):
    def __init__(self, ptz_camera):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        
        self.timeout_id = None
        self.max_fps = 20     
        self.camera = ptz_camera
        
        self._create_widgets()                  
        self.video.connect('button_press_event', self.on_image_click)
                                        
    def save_image(self, filename):
        ftype = filename.split('.')[-1]
        if ftype == 'jpg': 
            ftype = 'jpeg'
        img = self.camera.get_frame()
        img.save(filename)
        
    # callbacks
    def on_save(self, obj=None, arg=None):
        img_filename = save_selector()
        if os.access(os.path.split(img_filename)[0], os.W_OK):
            _logger.info('Saving sample image to: %s' % img_filename)
            self.save_image(img_filename)
        else:
            _logger.error("Could not save %s." % img_filename)
                    
    def on_zoom_in(self,widget):
        self.camera.zoom(600)
        return True

    def on_zoom_out(self,widget):
        self.camera.zoom(-600)
        return True

    def on_unzoom(self,widget):
        self.camera.zoom( 0 )
        return True
                
    def on_image_click(self, widget, event):
        if event.button == 1:
            im_x, im_y = int(event.x/self.video.scale), int(event.y/self.video.scale)
            self.camera.center(im_x, im_y)
        return True

    def on_view_changed(self, widget):
        iter = widget.get_active_iter()
        model = widget.get_model()
        value = model.get_value(iter,0)
        self.camera.goto(value)
                                
    def _create_widgets(self):
        self._xml = gtk.glade.XML(os.path.join(_DATA_DIR, 'ptz_viewer.glade'), 
                                  'ptz_viewer')
        widget = self._xml.get_widget('ptz_viewer')
        
        self.add(widget)
        
        self.side_panel = self._xml.get_widget('side_panel')
        
        #zoom
        self.zoom_out_btn = self._xml.get_widget('zoom_out_btn')
        self.zoom_in_btn = self._xml.get_widget('zoom_in_btn')
        self.zoom_100_btn = self._xml.get_widget('zoom_100_btn')
        self.zoom_out_btn.connect('clicked', self.on_zoom_out)
        self.zoom_in_btn.connect('clicked', self.on_zoom_in)
        self.zoom_100_btn.connect('clicked', self.on_unzoom)
        
        # presets
        presets_frame = self._xml.get_widget('presets_frame')
        self.presets_btn = gtk.combo_box_new_text()
        for val in self.camera.get_presets():
            self.presets_btn.append_text(val)     
        self.presets_btn.connect('changed', self.on_view_changed)
        presets_frame.pack_start(self.presets_btn, expand=False, fill=False)
                

        # status, save, etc
        self.pos_label = self._xml.get_widget('status_label')
        self.meas_label = self._xml.get_widget('meas_label')
        self.save_btn = self._xml.get_widget('save_btn')
        self.save_btn.connect('clicked', self.on_save)
        
        #Video Area
        self.video_frame = self._xml.get_widget('video_frame')
        self.video = VideoWidget(self.camera)
        self.video.set_size_request(416,312)
        self.video_frame.pack_start(self.video, expand=True, fill=True)
        self.show_all()
        


def main():
    import bcm.device.video
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("HutchViewer")
    book = gtk.Notebook()
    win.add(book)
    
    
    cam = bcm.device.video.AxisCamera('10.52.4.102') #ccd1608-201
    
    myviewer = AxisViewer(cam)
    book.append_page(myviewer, tab_label=gtk.Label('Hutch Viewer') )
    win.show_all()

    gtk.main()


if __name__ == '__main__':
    main()
