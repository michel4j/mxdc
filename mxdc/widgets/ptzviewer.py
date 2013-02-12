from bcm.device.interfaces import IPTZCameraController
from bcm.utils.log import get_module_logger
from mxdc.utils import gui
from mxdc.widgets.dialogs import save_selector
from mxdc.widgets.video import VideoWidget
import gtk
import os


_logger = get_module_logger('mxdc.ptzviewer')
_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

        
class AxisViewer(gtk.Alignment):
    def __init__(self, ptz_camera):
        gtk.Alignment.__init__(self, 0.5, 0.5, 1, 1)
        
        self.timeout_id = None
        self.max_fps = 20     
        self.camera = ptz_camera
        
        self._create_widgets()                  
        self.video.set_overlay_func(self._overlay_function)

    def __getattr__(self, key):
        try:
            return super(AxisViewer).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
                                        
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
        itr = widget.get_active_iter()
        model = widget.get_model()
        value = model.get_value(itr,0)
        self.camera.goto(value)
                                
    def _create_widgets(self):
        self._xml = gui.GUIFile(os.path.join(_DATA_DIR, 'ptz_viewer'), 
                                  'ptz_viewer')
        widget = self._xml.get_widget('ptz_viewer')
        
        self.add(widget)

        
        #zoom
        self.zoom_out_btn.connect('clicked', self.on_zoom_out)
        self.zoom_in_btn.connect('clicked', self.on_zoom_in)
        self.zoom_100_btn.connect('clicked', self.on_unzoom)
        
        #Video Area
        self.video = VideoWidget(self.camera)
        self.video_frame.add(self.video)

        # presets
        self.presets_btn = gtk.combo_box_new_text()
        if IPTZCameraController.providedBy(self.camera):
            self.video.connect('button_press_event', self.on_image_click)
            for val in self.camera.get_presets():
                self.presets_btn.append_text(val)
            self.presets_btn.connect('changed', self.on_view_changed)
        else:
            self.preset_box.set_sensitive(False)
            self.zoom_box.set_sensitive(False)
        self.presets_frame.pack_start(self.presets_btn, expand=False, fill=False)
                

        # status, save, etc
        self.save_btn.connect('clicked', self.on_save)
        
        self.show_all()

    def _overlay_function(self, pixmap):
        self.meas_label.set_markup("<small><tt>FPS: %0.1f</tt></small>" % self.video.fps)
        return True     
        


def main():
    import bcm.device.video
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("HutchViewer")
    book = gtk.Notebook()
    win.add(book)
    
    
    cam = bcm.device.video.AxisCamera('10.52.4.100', 4) #ccd1608-201,10.52.4.102
    
    myviewer = AxisViewer(cam)
    book.append_page(myviewer, tab_label=gtk.Label('Hutch Viewer') )
    win.show_all()

    gtk.main()


if __name__ == '__main__':
    main()
