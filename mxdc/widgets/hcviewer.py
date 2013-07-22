from bcm.beamline.interfaces import IBeamline
from bcm.engine.scripting import get_scripts 
from bcm.utils.log import get_module_logger
from bcm.utils.video import add_hc_decorations
from mxdc.utils import gui
from mxdc.widgets.misc import ActiveEntry, HealthDisplay, ScriptButton
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.video import VideoWidget
from twisted.python.components import globalRegistry
import gobject
import gtk
import math
import os
import pango


_logger = get_module_logger('mxdc.hcviewer')

_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class HCViewer(SampleViewer):
    __gsignals__ = {
        'plot-changed': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT, gobject.TYPE_BOOLEAN]),
        'plot-paused': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT, gobject.TYPE_BOOLEAN]),
        'plot-cleared': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT]),
    }
    def __init__(self):
        gtk.Alignment.__init__(self, 0.5, 0.5, 1, 1)
        self._xml = gui.GUIFile(os.path.join(_DATA_DIR, 'hc_viewer'), 
                                  'hc_viewer')
        self._xml_popup = gui.GUIFile(os.path.join(_DATA_DIR, 'hc_viewer'), 
                                  'colormap_popup')
        
        self._timeout_id = None
        self._disp_time = 0
        self._colormap = 0
        self.paused = False
                
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
            self.hc = self.beamline.humidifier
        except:
            self.beamline = None
            _logger.warning('No registered beamline found.')
            return
        
        self.labels = ['Temp','Drop Size']
        
        self.entries = {
            'state':           HealthDisplay(self.hc, label='Status'), 
            'rel_humidity':    ActiveEntry(self.hc.humidity, 'Relative Humidity', fmt="%0.2f", width=20),
            'dewpoint_temp':   ActiveEntry(self.hc.dew_point, 'Dew Point Temperature', fmt="%0.1f"),
        }
                       
        self.scripts = get_scripts()
        self._create_widgets()
        
        self.video.connect('realize', self.on_realize)
        self.video.connect('motion_notify_event', self.on_mouse_motion)
        self.video.connect('button_press_event', self.on_image_click)
        self.video.connect('button_release_event', self.on_drag_motion)
        self.video.set_overlay_func(self._overlay_function)

        self.temp_btn.connect('clicked', self.on_plot_change)
        self.roi_btn.connect('clicked', self.toggle_define_roi)
        self.reset_btn.connect('clicked', self.on_reset_roi)
        self.pause_btn.connect('clicked', self.on_pause)
        self.clear_btn.connect('clicked', self.on_clear)
        self.time_btn.connect('changed', self.on_set_time)

        self.hc.ROI.connect('changed', self._get_roi)
        self.hc.drop_coords.connect('changed', self._get_drop_coords)
        self.hc.drop_size.connect('changed', self._get_drop_size)

        self.hc1_active = False        
        self.on_hc1_active()
        self.beamline.humidifier.status.connect('active', self.on_hc1_active)

        self.drop_coords = None
        self._define_roi = False
        self.xtime = 5
        self.on_plot_change(self.temp_btn)

    def __getattr__(self, key):
        try:
            return super(HCViewer).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def do_plot_changed(self, obj, data):
        pass
    
    def do_plot_paused(self, obj, data):
        pass
    
    def do_plot_cleared(self, obj):
        pass
        
    def _create_widgets(self):

        self.add(self.hc_viewer)
                
        # status, save, etc
        self.save_btn.connect('clicked', self.on_save)
        
        #Video Area
        self.video_frame = self.video_adjuster
        w, h = map(float, self.beamline.sample_video.size)
        self.video_frame.set(xalign=0.5, yalign=0.5, ratio=(w/h), obey_child=False)
        self.video = VideoWidget(self.beamline.sample_video)
        self.video_frame.add(self.video)
        
        pango_font = pango.FontDescription('Monospace 8')
        self.pos_label.modify_font(pango_font)
        self.meas_label.modify_font(pango_font)
        
        entry_box = gtk.VBox(False,0)
        stat_box = gtk.VBox(True,0)
        for key in ['state']:
            stat_box.pack_start(self.entries[key], expand=True, fill=False)
        for key in ['rel_humidity']:
            entry_box.pack_start(self.entries[key], expand=True, fill=False)
        self.stat_panel.pack_start(stat_box, expand=True, fill=False) 
        self.hc_panel.pack_start(entry_box, expand=True, fill=False)
        
        
        store = gtk.ListStore(gobject.TYPE_STRING)
        for t in ['5', '10', '20']:
            store.append(['%s min' % t])
        self.time_btn.set_model(store)
        cell = gtk.CellRendererText()
        self.time_btn.pack_start(cell, True)
        self.time_btn.add_attribute(cell, 'text', 0)
        self.time_btn.set_active(0)
        
        self.cent_btn = ScriptButton(self.scripts['SetCenteringMode'], 'Center')
        msg = "This procedure involves both switching the endstation to Mounting Mode and moving"
        msg += " the mounted sample to a near-vertical orientation.  Be aware that the sample can fall "
        msg += " out of the drop if the drop size is too large. Are you sure you want to proceed?"
        self.freeze_btn = ScriptButton(self.scripts['SetFreezeMode'], 'Freeze', confirm=True, message=msg)
        self.mode_tbl.attach(self.cent_btn, 0, 1, 0, 1)
        self.mode_tbl.attach(self.freeze_btn, 1, 2, 0, 1)
            
        self.temp_btn.set_label(self.labels[0])    
        self.roi_btn.set_label('Define ROI')
        self.reset_btn.set_label('Reset ROI')
        self.roi_btn.tooltip = gtk.Tooltips()
        self.roi_btn.tooltip.set_tip(self.roi_btn, 'Click and drag on the image to define a Region of Interest.')
        self.reset_btn.tooltip = gtk.Tooltips()
        self.reset_btn.tooltip.set_tip(self.reset_btn, 'Reset the current Region of Interest')
        
        
    def on_plot_change(self, widget):
        if widget.get_label() == self.labels[0]:
            state = True
            label = self.labels[1]
        else:
            state = False
            label = self.labels[0]
        gobject.idle_add(self.emit, 'plot-changed', widget, state)
        self.temp_btn.set_label(label)

    def on_hc1_active(self, obj=None, active=False):
        self.hc1_active = active
        if not active:
            self.paused = True
            self.on_pause()
        self.side_panel.set_sensitive(active)
        
    def on_pause(self, widget=None):
        if self.paused:
            self.paused = False
            self.pause_img.set_from_stock('gtk-media-pause', gtk.ICON_SIZE_MENU)
            self.pause_lbl.set_text('Pause')
        else:
            self.paused = True
            self.pause_img.set_from_stock('gtk-media-play', gtk.ICON_SIZE_MENU)
            self.pause_lbl.set_text('Track')
        gobject.idle_add(self.emit, 'plot-paused', widget, self.paused)

    def on_clear(self, widget):
        gobject.idle_add(self.emit, 'plot-cleared', widget)
        
    def on_set_time(self, widget):
        self.xtime = int(self.time_btn.get_active_text().split(' ')[0])

    def _get_roi(self, obj=None, state=None):
        self.dragging = False
        if self.hc1_active:
            self.roi = list(state)     
 
    def _get_drop_coords(self, obj, pv):
        drop_coords = [val for val in list(pv)[:4] if val < 770 and val > 0]
        if len(drop_coords) is 4: self.drop_coords = drop_coords 
        
    def _get_drop_size(self, obj, val):
        self.drop_size = val
 
    def save_image(self, filename):
        img = self.beamline.sample_video.get_frame()
        
        [x1, y1, x2, y2] = self.roi

        img = add_hc_decorations(img, x1, x2, y1, y2)
        img.save(filename)
      
    def on_mouse_motion(self, widget, event):
        if event.is_hint:
            x, y, _ = event.window.get_pointer()
        else:
            x = event.x; y = event.y
        im_x, im_y, xmm, ymm = self._img_position(x,y)
        self.pos_label.set_markup("%4d,%4d [%6.3f, %6.3f mm]" % (im_x, im_y, xmm, ymm))
        if 'GDK_BUTTON1_MASK' in event.state.value_names and self._define_roi:
            self.roi[2], self.roi[3], = int(event.x / float(self.video.scale)), int(event.y / float(self.video.scale))
        elif 'GDK_BUTTON2_MASK' in event.state.value_names:
            self.measure_x2, self.measure_y2, = event.x, event.y
        else:
            self.measuring = False
            self.dragging = False

    def on_image_click(self, widget, event):
        if event.button == 1 and self._define_roi:
            self.dragging = True
            self.roi[0], self.roi[1] = int(event.x / float(self.video.scale)), int(event.y / float(self.video.scale))
            self.roi[2], self.roi[3] = int(event.x / float(self.video.scale)), int(event.y / float(self.video.scale))
        elif event.button == 2:
            self.measuring = True
            self.measure_x1, self.measure_y1 = event.x, event.y
            self.measure_x2, self.measure_y2 = event.x, event.y

    def on_drag_motion(self, widget, event):
        if self._define_roi:
            self.hc.ROI.set(self.roi)
               
    def toggle_define_roi(self, widget=None):
        if self._define_roi == True:
            self._define_roi = False
        else:
            self._define_roi = True
        return False
    
    def on_reset_roi(self, widget=None):
        self.hc.ROI.set([-2147483648, -2147483648, 2147483647, 2147483647])
        self.roi_btn.set_active(False)
        self._get_roi()
        
    def _overlay_function(self, pixmap):
        if self.hc1_active:
            self.draw_roi_overlay(pixmap)
            self.draw_drop_coords(pixmap)
        self.draw_meas_overlay(pixmap)
        return True        
    
    def draw_roi_overlay(self, pixmap):
        coords = []
        for i in range(4):
            coords.append(int(self.roi[i] * float(self.video.scale)))
        [x1, y1, x2, y2] = coords

        cr = pixmap.cairo_create()
        cr.set_source_rgba(0.1, 1.0, 0.0, 1.0)
        cr.set_line_width(0.5)
        cr.rectangle(x1, y1, x2-x1, y2-y1)
        cr.stroke()
        self.meas_label.set_markup("FPS: %0.1f" % self.video.fps)

        return True

    def draw_meas_overlay(self, pixmap):
        pix_size = self.beamline.sample_video.resolution
        if self.measuring:
            x1 = self.measure_x1
            x2 = self.measure_x2
            y1 = self.measure_y1
            y2 = self.measure_y2        
        
            dist = pix_size * math.sqrt((x2 - x1) ** 2.0 + (y2 - y1) ** 2.0) / self.video.scale * 1000
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            cr = pixmap.cairo_create()
            cr.set_source_rgba(0.1, 1.0, 0.0, 1.0)
            cr.set_line_width(0.5)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()
            self.meas_label.set_markup("Length: %0.1f um" % dist)
            
    def draw_drop_coords(self, pixmap):
        if self.drop_coords and self.drop_size > 0:
            [x1, y1, x2, y2] = [val * float(self.video.scale) for val in self.drop_coords]

            cr = pixmap.cairo_create()
            cr.set_source_rgba(0.0, 0.0, 1.0, 1.0)
            cr.set_line_width(1)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

        pix_size = self.beamline.sample_video.resolution
        dist = pix_size * self.drop_size * 1000
        self.meas_label.set_markup("Drop Size: %0.1f um" % dist)
        return True
