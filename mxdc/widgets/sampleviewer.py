from bcm.beamline.interfaces import IBeamline
from bcm.engine.scripting import get_scripts
from bcm.protocol import ca
from bcm.utils.decorators import async
from bcm.utils.log import get_module_logger
from bcm.utils.ordereddict import OrderedDict
# from bcm.utils.video import add_decorations
from mxdc.utils import gui, colors
from mxdc.widgets import dialogs
from mxdc.widgets.misc import ActiveHScale, ScriptButton
from mxdc.widgets.video import VideoWidget
from twisted.python.components import globalRegistry
import gtk
import math
import numpy
import pango
import os

_logger = get_module_logger('mxdc.sampleviewer')

COLOR_MAPS = [None, 'Spectral', 'hsv', 'jet', 'RdYlGn', 'hot', 'PuBu']
_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


def activate_action(action):
    print 'Action "%s" activated' % action.get_name()


POPUP_ACTIONS = (
    ('cmap_default', None, 'Default', None, None, activate_action),
    ('cmap_spectral', None, 'Spectral', None, None, activate_action),
    ('cmap_hsv', None, 'HSV', None, None, activate_action),
    ('cmap_jet', None, 'Jet', None, None, activate_action),
    ('cmap_ryg', None, 'RdYlGn', None, None, activate_action),
    ('cmap_hot', None, 'Hot', None, None, activate_action),
    ('cmap_pubu', None, 'PuBu', None, None, activate_action),
)
POPUP_UI = """
<ui>
<popup name="PopupMenu">
    <menu name="Grid" action="grid_action">
      <menuitem name="Clear Grid" action="grid_clear"/>
      <separator/>
      <menuitem name="Reset Grid" action="grid_reset"/>
    </menu>
    <menu name="Color Mapping" action="cmap_action">
      <menuitem name="Default" action="cmap_default"/>
      <separator/>
      <menuitem name="Spectral" action="cmap_spectral"/>
      <menuitem name="HSV" action="cmap_hsv"/>
      <menuitem name="Jet" action="cmap_jet"/>
      <menuitem name="RdYlGn" action="cmap_ryg"/>
      <menuitem name="Hot" action="cmap_hot"/>
      <menuitem name="PuBu" action="cmap_pubu"/>
    </menu>
</popup>
</ui>
"""


class SampleViewer(gtk.Alignment):
    def __init__(self):
        gtk.Alignment.__init__(self, 0.5, 0.5, 1, 1)
        self._xml = gui.GUIFile(os.path.join(_DATA_DIR, 'sample_viewer'),
                                'sample_viewer')
        self._xml_popup = gui.GUIFile(os.path.join(_DATA_DIR, 'sample_viewer'),
                                      'colormap_popup')

        self._timeout_id = None
        self._disp_time = 0
        self._click_centering = False
        self._colormap = 0
        self._tick_size = 8

        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
            _logger.warning('No registered beamline found.')

        self.scripts = get_scripts()
        self._create_widgets()

        # initialize measurement variables
        self.measuring = False
        self.measure_x1 = 0
        self.measure_x2 = 0
        self.measure_y1 = 0
        self.measure_y2 = 0

        # initialize grid variables
        self.init_grid_settings()
        self._grid_colormap = colors.ColorMapper(color_map='jet', min_val=0.2, max_val=0.8)

        self.video.connect('motion_notify_event', self.on_mouse_motion)
        self.video.connect('button_press_event', self.on_image_click)
        self.video.set_overlay_func(self._overlay_function)
        self.video.connect('realize', self.on_realize)

        script = self._scripts['CenterSample']
        script.connect('done', self.done_centering)
        script.connect('error', self.error_centering)

    def __getattr__(self, key):
        try:
            return super(SampleViewer).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def save_image(self, filename):
        self.video.save_image(filename)

    def draw_beam_overlay(self, pixmap):
        w, h = pixmap.get_size()
        pix_size = self.beamline.sample_video.resolution
        try:
            bh = self.beamline.aperture.get() * 0.001
            bx = 0  # self.beamline.beam_x.get_position()
            by = 0  # self.beamline.beam_y.get_position()
            cx = self.beamline.camera_center_x.get()
            cy = self.beamline.camera_center_y.get()
        except:
            cx = w // 2
            bx = by = 0
            cy = h // 2

        # slit sizes in pixels
        sh = bh / pix_size
        x = int((cx - (bx / pix_size)) * self.video.scale)
        y = int((cy - (by / pix_size)) * self.video.scale)
        hh = int(0.5 * sh * self.video.scale)

        cr = pixmap.cairo_create()
        cr.set_source_rgba(1, 0.2, 0.1, 0.3)
        cr.set_line_width(2.0)

        # beam size
        cr.arc(x, y, hh, 0, 2.0 * 3.14)
        cr.stroke()

        return

    def draw_meas_overlay(self, pixmap):
        pix_size = self.beamline.sample_video.resolution
        if self.measuring == True:
            x1 = self.measure_x1
            y1 = self.measure_y1
            x2 = self.measure_x2
            y2 = self.measure_y2
            dist = pix_size * math.sqrt((x2 - x1) ** 2.0 + (y2 - y1) ** 2.0) / self.video.scale
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

            cr = pixmap.cairo_create()
            cr.set_source_rgba(0.2, 1.0, 0.2, 0.3)
            cr.set_line_width(4.0)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

            self.meas_label.set_markup("Length: %0.2g mm" % dist)
        else:
            self.meas_label.set_markup("FPS: %0.1f" % self.video.fps)
        return True

    def _calc_grid_params(self):
        pix_size = self.beamline.sample_video.resolution
        gw = 0.001 * self.grid_params.get('loop_size', 200)
        cw = 0.001 * self.grid_params.get('aperture', 25)
        nX = nY = int(math.ceil(gw / cw))
        gw = nX * cw

        cx = self.beamline.camera_center_x.get()
        cy = self.beamline.camera_center_y.get()
        sx, sy = self.grid_params.get('origin', (0.0, 0.0))
        ox = self.beamline.sample_stage.x.get_position() - sx
        oy = self.beamline.sample_stage.y.get_position() - sy

        # grid xY origin
        bx = ox / pix_size
        by = oy / pix_size

        # grid sizes in pixels
        hgw = int(0.5 * gw * self.video.scale / pix_size)
        grid_size = self.video.scale * gw / pix_size
        cell_size = self.video.scale * cw / pix_size
        x0 = int((cx - bx) * self.video.scale) - hgw
        # y0 = int((cy-by) * self.video.scale) - hgw
        y0 = int((cy - by) * self.video.scale) - hgw * numpy.sqrt(1 - 0.5 ** 2)

        return (x0, y0, grid_size, cell_size, nX, nY)

    def draw_grid_overlay(self, pixmap):
        if self.show_grid:

            cell_size, nX, nY = self._calc_grid_params()[3:]
            cr = pixmap.cairo_create()
            cr.set_line_width(0.5)
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.5)
            for i in range(nX):
                for j in range(nY):

                    # x1 = x0 + i*cell_size
                    # y1 = y0 + j*cell_size
                    cell = (i, j)
                    loc = self._get_grid_center(cell)
                    if cell in self.grid_params['ignore']:
                        # cr.rectangle(x1, y1, cell_size, cell_size)
                        cr.arc(loc[0], loc[1], cell_size / 2, 0, 2.0 * 3.14)
                        cr.set_source_rgba(0.0, 0.0, 0.0, 0.5)
                        cr.stroke()
                    else:
                        score = self.grid_params['scores'].get(cell, None)
                        if self.edit_grid:
                            cr.set_source_rgba(0.0, 0.0, 1, 0.2)
                        elif score is None:
                            cr.set_source_rgba(0.9, 0.9, 0.9, 0.3)
                        else:
                            R, G, B = self._grid_colormap.get_rgb(score)
                            cr.set_source_rgba(R, G, B, 0.3)
                        # cr.rectangle(x1, y1, cell_size, cell_size)
                        cr.arc(loc[0], loc[1], cell_size / 2, 0, 2.0 * 3.14)
                        cr.fill()

                        # cr.rectangle(x1, y1, cell_size, cell_size)
                        cr.arc(loc[0], loc[1], cell_size / 2, 0, 2.0 * 3.14)

                        cr.set_source_rgba(0.1, 0.1, 0.1, 0.5)
                        cr.stroke()
        return True

    def init_grid_settings(self):
        self.grid_params = {}
        self.grid_params['ignore'] = []
        sx = self.beamline.sample_stage.x.get_position()
        sy = self.beamline.sample_stage.y.get_position()
        self.grid_params['origin'] = (sx, sy)
        self.grid_params['angle'] = self.beamline.omega.get_position()
        self.grid_params['scores'] = {}
        self.grid_params['details'] = {}
        self.show_grid = False
        self.edit_grid = False

    def apply_grid_settings(self, params):
        self.grid_params = params
        self.grid_params['ignore'] = []
        sx = self.beamline.sample_stage.x.get_position()
        sy = self.beamline.sample_stage.y.get_position()
        self.grid_params['origin'] = (sx, sy)
        self.grid_params['angle'] = self.beamline.omega.get_position()
        self.grid_params['scores'] = {}
        self.grid_params['details'] = {}
        self.show_grid = True
        self.edit_grid = True

    def add_grid_score(self, cell, score):
        self.grid_params['scores'][cell] = score
        values = [v for v in self.grid_params['scores'].values()]
        self._grid_colormap.autoscale(values)

    def apply_grid_results(self, data):
        self.grid_params = data
        self.show_grid = True
        self.edit_grid = False

    def select_grid_pixel(self, data):
        self.show_grid = True
        self.edit_grid = False

    def clear_grid(self):
        self.grid_params = {}
        self.show_grid = False
        self.edit_grid = False

    def lock_grid(self):
        self.show_grid = True
        self.edit_grid = False

    def get_grid_settings(self):
        info = {}
        info.update(self.grid_params)
        x0, y0, grid_size, cell_size, nX, nY = self._calc_grid_params()  # @UnusedVariable
        info['size'] = nX
        info['cells'] = OrderedDict()
        i_range = range(nX)
        for j in range(nY):
            for i in i_range:
                cell = i, j
                if cell in self.grid_params['ignore']: continue
                loc = self._get_grid_center(cell)
                info['cells'][cell] = loc
            i_range = i_range[::-1]
        return info

    def _get_grid_cell(self, x, y):

        x0, y0, grid_size, cell_size, nX, nY = self._calc_grid_params()  # @UnusedVariable
        # i = int((x - x0)/cell_size)
        # j = int((y - y0)/cell_size)

        yd = cell_size * numpy.sqrt(1 - 0.5 ** 2)
        j = int((y - y0) / yd)
        x0adj = x0 + cell_size * 0.25 * ((-1) ** j)
        if x < x0adj or y < y0:
            return None

        i = int((x - x0adj) / cell_size)

        if (0 <= i <= nX) and (0 <= i <= nX):
            return (i, j)
        else:
            return None

    def _get_grid_center(self, cell):
        i, j = cell
        x0, y0, grid_size, cell_size, nX, nY = self._calc_grid_params()  # @UnusedVariable

        #        x = (i * cell_size) + cell_size/2 + x0
        #        y = (j * cell_size) + cell_size/2 + y0

        yd = cell_size * numpy.sqrt(1 - 0.5 ** 2)
        x = (i * cell_size + cell_size * 0.25 * ((-1) ** j)) + cell_size / 2 + x0
        y = (j * yd) + cell_size / 2 + y0

        im_x, im_y, dx, dy = self._img_position(x, y)  # @UnusedVariable
        return int(round(x)), int(round(y)), dx, dy

    def toggle_grid_cell(self, x, y):
        if self.edit_grid and not self._click_centering:
            cell = self._get_grid_cell(x, y)
            if cell is not None:
                if cell in self.grid_params['ignore']:
                    self.grid_params['ignore'].remove(cell)
                else:
                    self.grid_params['ignore'].append(cell)

    def clear_grid_cell(self, x, y):
        if self.edit_grid:
            cell = self._get_grid_cell(x, y)
            if cell is not None:
                if not cell in self.grid_params['ignore']:
                    self.grid_params['ignore'].append(cell)

    def _img_position(self, x, y):
        im_x = int(float(x) / self.video.scale)
        im_y = int(float(y) / self.video.scale)
        try:
            cx = self.beamline.camera_center_x.get()
            cy = self.beamline.camera_center_y.get()
        except  ca.ChannelAccessError:
            cx, cy = self.beamline.sample_video.size
            cx //= 2
            cy //= 2
        xmm = (cx - im_x) * self.beamline.sample_video.resolution
        ymm = (cy - im_y) * self.beamline.sample_video.resolution
        return (im_x, im_y, xmm, ymm)

    def toggle_click_centering(self, widget=None):
        if self._click_centering == True:
            self._click_centering = False
        else:
            self._click_centering = True
        return False

    @async
    def center_pixel(self, x, y):
        im_x, im_y, xmm, ymm = self._img_position(x, y)  # @UnusedVariable
        print xmm, ymm
        if not self.beamline.sample_stage.x.is_busy():
            self.beamline.sample_stage.x.move_by(-xmm, wait=True)
        if not self.beamline.sample_stage.y.is_busy():
            self.beamline.sample_stage.y.move_by(-ymm)

    def _create_widgets(self):

        self.cmap_popup = self._xml_popup.get_widget('colormap_popup')
        # connect colormap signals
        cmap_items = ['cmap_default', 'cmap_spectral', 'cmap_hsv', 'cmap_jet', 'cmap_ryg', 'cmap_hot', 'cmap_pubu']
        for i in range(len(cmap_items)):
            w = self._xml_popup.get_widget(cmap_items[i])
            w.connect('activate', self.on_cmap_activate, i)

        self.add(self.sample_viewer)

        # zoom
        self.zoom_out_btn.connect('clicked', self.on_zoom_out)
        self.zoom_in_btn.connect('clicked', self.on_zoom_in)
        self.zoom_100_btn.connect('clicked', self.on_unzoom)

        # move sample
        self.left_btn.connect('clicked', self.on_fine_left)
        self.right_btn.connect('clicked', self.on_fine_right)
        self.home_btn.connect('clicked', self.on_home)

        # rotate sample
        self.decr_90_btn.connect('clicked', self.on_decr_omega)
        self.incr_90_btn.connect('clicked', self.on_incr_omega)
        self.incr_180_btn.connect('clicked', self.on_double_incr_omega)

        # centering 
        self.click_btn.connect('clicked', self.toggle_click_centering)
        self.loop_btn.connect('clicked', self.on_center_loop)
        self.capillary_btn.connect('clicked', self.on_center_capillary)
        self.crystal_btn.connect('clicked', self.on_center_crystal)
        self.beamline.goniometer.connect('mode', self.on_gonio_mode)

        # status, save, etc
        self.save_btn.connect('clicked', self.on_save)

        # Video Area
        self.video_frame = self.video_adjuster
        w, h = map(float, self.beamline.sample_video.size)
        self.video_frame.set(xalign=0.5, yalign=0.5, ratio=(w / h), obey_child=False)
        self.video = VideoWidget(self.beamline.sample_video)
        self.video_frame.add(self.video)

        # Lighting
        self.side_light = ActiveHScale(self.beamline.sample_frontlight)
        self.back_light = ActiveHScale(self.beamline.sample_backlight)
        self.side_light.set_update_policy(gtk.UPDATE_DELAYED)
        self.back_light.set_update_policy(gtk.UPDATE_DELAYED)
        self.lighting_box.attach(self.side_light, 1, 2, 0, 1)
        self.lighting_box.attach(self.back_light, 1, 2, 1, 2)

        self._scripts = get_scripts()
        pango_font = pango.FontDescription('Monospace 8')
        self.pos_label.modify_font(pango_font)
        self.meas_label.modify_font(pango_font)

        # mode buttons
        self.cent_btn = ScriptButton(self.scripts['SetCenteringMode'], 'Centering')
        msg = "This procedure involves both moving any mounted samples away from the beam position and"
        msg += " moving the scintillator to the beam position. It is recommended to dismount any samples "
        msg += " before switching to BEAM mode. Are you sure you want to proceed?"
        self.beam_btn = ScriptButton(self.scripts['SetBeamMode'], 'Beam', confirm=True, message=msg)
        self.mode_tbl.attach(self.cent_btn, 0, 1, 0, 1)
        self.mode_tbl.attach(self.beam_btn, 1, 2, 0, 1)

        # disable mode change buttons while automounter is busy
        self.beamline.automounter.connect('busy', self.on_automounter_busy)

        # disable key controls while scripts are running
        for sc in ['SetMountMode', 'SetCenteringMode', 'SetCollectMode', 'SetBeamMode', 'CenterSample']:
            self.scripts[sc].connect('started', self.on_scripts_started)
            self.scripts[sc].connect('done', self.on_scripts_done)

    def _overlay_function(self, pixmap):
        self.draw_beam_overlay(pixmap)
        self.draw_meas_overlay(pixmap)
        self.draw_grid_overlay(pixmap)
        return True


        # callbacks

    def on_gonio_mode(self, obj, mode):
        if mode != 'CENTERING':
            self.loop_btn.set_sensitive(False)
            self.crystal_btn.set_sensitive(False)
            self.capillary_btn.set_sensitive(False)
        else:
            self.loop_btn.set_sensitive(True)
            self.crystal_btn.set_sensitive(True)
            self.capillary_btn.set_sensitive(True)

    def on_automounter_busy(self, obj, state):
        self.cent_btn.set_sensitive(not state)
        self.beam_btn.set_sensitive(not state)

    def on_scripts_started(self, obj, event=None):
        self.side_panel.set_sensitive(False)

    def on_scripts_done(self, obj, event=None):
        self.side_panel.set_sensitive(True)

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

    def on_center_loop(self, widget):
        script = self._scripts['CenterSample']
        script.start(loop=True)
        return True

    def on_center_capillary(self, widget):
        script = self._scripts['CenterSample']
        script.start(capillary=True)
        return True

    def on_center_crystal(self, widget):
        script = self._scripts['CenterSample']
        script.start(crystal=True)
        return True

    def done_centering(self, obj, result):
        pass

    def error_centering(self, obj):
        pass

    def on_unmap(self, widget):
        self.videothread.pause()

    def on_no_expose(self, widget, event):
        return True

    def on_delete(self, widget):
        self.videothread.stop()

    def on_expose(self, videoarea, event):
        window = videoarea.get_window()
        window.draw_drawable(self.othergc, self.pixmap, 0, 0, 0, 0,
                             self.width, self.height)

    def on_zoom_in(self, widget):
        self.beamline.sample_video.zoom(8)

    def on_zoom_out(self, widget):
        self.beamline.sample_video.zoom(2)

    def on_unzoom(self, widget):
        self.beamline.sample_video.zoom(5)

    def on_incr_omega(self, widget):
        cur_omega = int(self.beamline.omega.get_position())
        target = (cur_omega + 90)
        target = (target > 360) and (target % 360) or target
        self.beamline.omega.move_to(target)

    def on_decr_omega(self, widget):
        cur_omega = int(self.beamline.omega.get_position())
        target = (cur_omega - 90)
        target = (target < -360) and (target % 360) or target
        self.beamline.omega.move_to(target)

    def on_double_incr_omega(self, widget):
        cur_omega = int(self.beamline.omega.get_position())
        target = (cur_omega + 180)
        target = (target > 360) and (target % 360) or target
        self.beamline.omega.move_to(target)

    def on_mouse_motion(self, widget, event):
        if event.is_hint:
            x, y, state = event.window.get_pointer()
        else:
            x = event.x;
            y = event.y
        im_x, im_y, xmm, ymm = self._img_position(x, y)
        self.pos_label.set_markup("%4d,%4d [%6.3f, %6.3f mm]" % (im_x, im_y, xmm, ymm))
        if 'GDK_BUTTON2_MASK' in event.state.value_names:
            self.measure_x2, self.measure_y2, = event.x, event.y
        elif 'GDK_BUTTON1_MASK' in event.state.value_names:
            if self.show_grid and self.edit_grid and not self._click_centering:
                self.clear_grid_cell(event.x, event.y)
        else:
            self.measuring = False

    def on_image_click(self, widget, event):
        if event.button == 1:
            if self._click_centering:
                self.center_pixel(event.x, event.y)
            elif self.show_grid and self.edit_grid:
                self.toggle_grid_cell(event.x, event.y)

        elif event.button == 2:
            self.measuring = True
            self.measure_x1, self.measure_y1 = event.x, event.y
            self.measure_x2, self.measure_y2 = event.x, event.y
        elif event.button == 3:
            self.cmap_popup.popup(None, None, None, event.button, event.time)

    def on_fine_left(self, widget):
        # move left by 0.2 mm
        self.beamline.sample_stage.x.move_by(0.2)

    def on_fine_right(self, widget):
        # move right by 0.2 mm
        self.beamline.sample_stage.x.move_by(-0.2)

    def on_home(self, widget):
        # move to horizontal home position
        # self.beamline.sample_stage.x.move_to( 22.0 )
        return True
