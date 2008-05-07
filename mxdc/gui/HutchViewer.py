import gtk, gobject
import sys, time, os
from Dialogs import save_selector
from VideoWidget import VideoWidget
from bcm.tools.scripting import Script
from bcm.scripts.misc import center_sample 
from bcm.protocols import ca

        
class HutchViewer(gtk.HBox):
    def __init__(self, bl):
        gtk.HBox.__init__(self,False,6)
        
        self.timeout_id = None
        self.max_fps = 20
        self.video_realized = False
        self.ready = True
        self.click_centering  = False
        self.contrast = 0        
        
        self.camera = bl.hutch_cam        
        self.tick_size = 5
        
        self.create_widgets()        
                
        self.connect("destroy", lambda x: self.stop())
        self.video.connect('button_press_event', self.on_image_click)

    def __del__(self):
        self.video.stop()
                                        
    def stop(self, win=None):
        self.video.stop()                
                
    def save_image(self, filename):
        ftype = filename.split('.')[-1]
        if ftype == 'jpg': 
            ftype = 'jpeg'
        self.camera.save(filename)
        
    # callbacks
    def on_save(self, obj=None, arg=None):
        img_filename = save_selector()
        if os.access(os.path.split(img_filename)[0], os.W_OK):
            LogServer.log('Saving sample image to: %s' % img_filename)
            self.save_image(img_filename)
        else:
            LogServer.log("Could not save %s." % img_filename)
            
    def on_delete(self,widget):
        self.video.stop()
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
        if self.video is not None:
            self.video.stop()
            
    def on_image_click(self, widget, event):

        if event.button == 1:
            im_x, im_y = int(event.x/self.video.scale_factor), int(event.y/self.video.scale_factor)

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
        videoframe = gtk.AspectFrame( ratio=640.0/480.0, obey_child=False)
        videoframe.set_shadow_type(gtk.SHADOW_IN)
        self.video = VideoWidget(self.camera)
        self.video.set_size_request(400, 300)
        videoframe.add(self.video)
        vbox2.pack_start(videoframe, expand=True, fill=True)   
        self.pack_end(vbox2, expand=True, fill=True)
        
        self.show_all()


def main():
    import bcm.devices.cameras
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("HutchViewer")
    book = gtk.Notebook()
    win.add(book)
    
    class junk(object):
        pass
    
    bl = junk()
    
    bl.hutch_cam = bcm.devices.cameras.AxisCamera('ccd1608-201.cs.cls')
    
    myviewer = HutchViewer(bl)
    book.append_page(myviewer, tab_label=gtk.Label('Hutch Viewer') )
    win.show_all()

    try:
        gtk.main()
    finally:
        myviewer.video.stop()


if __name__ == '__main__':
    main()
