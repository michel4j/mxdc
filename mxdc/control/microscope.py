import math
import os
import time
from collections import OrderedDict

import common
import numpy
from gi.repository import Gtk, Pango, Gdk
from matplotlib.path import Path
from mxdc.beamline.mx import IBeamline
from mxdc.engine.scripting import get_scripts
from mxdc.utils import colors, imgproc
from mxdc.utils.decorators import async
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs
from mxdc.widgets.video import VideoWidget
from twisted.python.components import globalRegistry

_logger = get_module_logger(__name__)


def orientation(p):
    verts = p.vertices
    orient = ((verts[1:, 0] - verts[:-1, 0]) * (verts[1:, 1] + verts[:-1, 1])).sum()
    return -numpy.sign(orient) or 1


class MicroscopeController(object):
    def __init__(self, widget):
        self.timeout_id = None
        self.max_fps = 20
        self.fps_update = 0
        self.grid = None
        self.polygon = []
        self.points = []
        self._click_centering = False
        self.create_polygon = False
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.camera = self.beamline.sample_video
        self.setup()
        self.video.set_overlay_func(self.overlay_function)

    def setup(self):
        # zoom
        self.widget.microscope_zoomout_btn.connect('clicked', self.on_zoom_out)
        self.widget.microscope_zoomin_btn.connect('clicked', self.on_zoom_in)
        self.widget.microscope_zoom100_btn.connect('clicked', self.on_unzoom)

        # # move sample
        # self.widget.microscope_left_btn.connect('clicked', self.on_fine_left)
        # self.widget.microscope_right_btn.connect('clicked', self.on_fine_right)

        # rotate sample
        self.widget.microscope_ccw90_btn.connect('clicked', self.on_ccw90)
        self.widget.microscope_cw90_btn.connect('clicked', self.on_cw90)
        self.widget.microscope_rot180_btn.connect('clicked', self.on_rot180)

        # centering
        self.widget.microscope_loop_btn.connect('clicked', self.on_center_loop)
        self.widget.microscope_crystal_btn.connect('clicked', self.on_center_crystal)
        self.widget.microscope_capillary_btn.connect('clicked', self.on_center_capillary)
        self.beamline.goniometer.connect('mode', self.on_gonio_mode)
        self.beamline.aperture.connect('changed', self.on_aperture)

        # Video Area
        self.video = VideoWidget(self.camera)
        self.widget.microscope_video_frame.add(self.video)

        # status, save, etc
        self.widget.microscope_save_btn.connect('clicked', self.on_save)
        self.widget.microscope_grid_btn.connect('toggled', self.make_grid)
        self.widget.microscope_point_btn.connect('clicked', self.add_point)
        self.widget.microscope_clear_btn.connect('clicked', self.clear_objects)

        # lighting monitors
        self.monitors = [
            common.ScaleMonitor(self.widget.microscope_backlight_scale, self.beamline.sample_backlight),
            common.ScaleMonitor(self.widget.microscope_frontlight_scale, self.beamline.sample_frontlight),
        ]
        self.widget.microscope_backlight_scale.set_adjustment(Gtk.Adjustment(0, 0.0, 100.0, 1.0, 1.0, 10))
        self.widget.microscope_frontlight_scale.set_adjustment(Gtk.Adjustment(0, 0.0, 100.0, 1.0, 1.0, 10))

        pango_font = Pango.FontDescription('Monospace 7.5')
        self.widget.microscope_pos_lbl.modify_font(pango_font)
        self.widget.microscope_meas_lbl.modify_font(pango_font)

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
        self.video.set_overlay_func(self.overlay_function)
        self.video.connect('realize', self.on_realize)

        self.scripts = get_scripts()
        script = self.scripts['CenterSample']
        script.connect('done', self.done_centering)
        script.connect('error', self.error_centering)

        toolbar_btns = [
            self.widget.microscope_zoomout_btn, self.widget.microscope_zoom100_btn,
            self.widget.microscope_zoomin_btn,
            self.widget.microscope_ccw90_btn, self.widget.microscope_cw90_btn,
            self.widget.microscope_rot180_btn, self.widget.microscope_loop_btn,
            # self.widget.microscope_crystal_btn, self.widget.microscope_click_btn,
            self.widget.microscope_capillary_btn, self.widget.microscope_save_btn
        ]
        self.size_grp = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.BOTH)
        for btn in toolbar_btns:
            self.size_grp.add_widget(btn)

        self.widget.microscope_bkg.override_background_color(
            Gtk.StateType.NORMAL, Gdk.RGBA(red=0, green=0, blue=0, alpha=1)
        )

    def save_image(self, filename):
        self.video.save_image(filename)

    def draw_beam(self, cr):
        pix_scale = self.video.scale/self.beamline.sample_video.resolution
        radius = pix_scale * 0.5e-3 * self.beamline.aperture.get()
        tick_in = radius * 0.8
        tick_out = radius * 1.2
        center = numpy.array(self.video.get_size())/2


        cr.set_source_rgba(1, 0.2, 0.1, 0.3)
        cr.set_line_width(2.0)

        # beam circle
        cr.arc(center[0], center[1], radius, 0, 2.0 * 3.14)
        cr.stroke()

        # beam target ticks
        cr.move_to(center[0], center[1] - tick_in)
        cr.line_to(center[0], center[1] - tick_out)
        cr.stroke()

        cr.move_to(center[0], center[1] + tick_in)
        cr.line_to(center[0], center[1] + tick_out)
        cr.stroke()

        cr.move_to(center[0] - tick_in, center[1])
        cr.line_to(center[0] - tick_out, center[1])
        cr.stroke()

        cr.move_to(center[0] + tick_in, center[1])
        cr.line_to(center[0] + tick_out, center[1])
        cr.stroke()

    def draw_measurement(self, cr):
        pix_size = self.beamline.sample_video.resolution
        if self.measuring == True:
            x1 = self.measure_x1
            y1 = self.measure_y1
            x2 = self.measure_x2
            y2 = self.measure_y2
            dist = pix_size * math.sqrt((x2 - x1) ** 2.0 + (y2 - y1) ** 2.0) / self.video.scale
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

            cr.set_source_rgba(0.2, 1.0, 0.2, 0.3)
            cr.set_line_width(4.0)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

            self.widget.microscope_meas_lbl.set_text("%0.2g mm" % dist)
        else:
            # Update FPS ever 5 seconds
            if time.time() - self.fps_update > 1:
                self.widget.microscope_meas_lbl.set_text("%4.1f fps" % self.video.fps)
                self.fps_update = time.time()
        return True

    def clear_objects(self, *args, **kwargs):
        self.grid = None
        self.polygon = []
        self.points = []
        self.create_polygon = False
        self.widget.microscope_grid_btn.set_active(False)

    def make_grid(self, *args, **kwargs):
        if self.widget.microscope_grid_btn.get_active():
            self.create_polygon = True
            self.widget.microscope_bkg.get_window().set_cursor(Gdk.Cursor(Gdk.CursorType.CROSSHAIR))
            self.polygon = []
        else:
            self.create_polygon = False
            self.widget.microscope_bkg.get_window().set_cursor(None)

    def bbox_grid(self, bbox):
        step_mm = self.beamline.aperture.get()
        grid_size = bbox[1] - bbox[0]
        step_size = self.video.scale * 1e-3 * step_mm / self.beamline.sample_video.resolution

        nX, nY = grid_size / step_size
        nX = numpy.ceil(nX)
        nY = numpy.ceil(numpy.sqrt(2) * nY)

        xi = numpy.linspace(bbox[0][0], bbox[1][0], nX)
        yi = numpy.linspace(bbox[0][1], bbox[1][1], nY)
        x_ij, y_ij = numpy.meshgrid(xi, yi, sparse=False, indexing='ij')
        radius = step_size * 0.5
        return numpy.array([
            (x_ij[i, j] + (j % 2) * radius, y_ij[i, j])
            for j in numpy.arange(nY).astype(int)
            for i in numpy.arange(nX).astype(int)
            if nX - i != j % 2
        ])

    def auto_grid(self, *args, **kwargs):
        img = self.beamline.sample_video.get_frame()
        bbox = self.video.scale * imgproc.get_sample_bbox2(img)
        self.grid = self.bbox_grid(bbox)

    def draw_grid(self, cr):
        if self.grid is not None:
            radius = 0.5e-3 * self.video.scale * self.beamline.aperture.get() / self.beamline.sample_video.resolution
            cr.set_source_rgba(0.2, 1.0, 0.5, 0.5)
            cr.set_line_width(1.0)
            cr.set_font_size(10)
            for i, (x, y) in enumerate(self.grid):
                cr.arc(x, y, radius, 0, 2.0 * 3.14)
                cr.stroke()
                name = '{}'.format(i)
                xb, yb, w, h = cr.text_extents(name)[:4]
                cr.move_to(x - w / 2. - xb, y - h / 2. - yb)
                cr.show_text(name)
                cr.stroke()

    def draw_polygon(self, cr):
        if self.polygon:
            cr.set_source_rgba(0.0, 1.0, 0.0, 0.5)
            cr.set_line_width(1.0)
            cr.move_to(*self.polygon[0])
            for x, y in self.polygon[1:]:
                cr.line_to(x, y)
            cr.stroke()
            cr.set_source_rgba(1.0, 0.0, 0.0, 0.5)
            first = True
            radius = 5
            for x, y in self.polygon:
                cr.arc(x, y, radius, 0, 2.0 * 3.14)
                if first:
                    cr.fill()
                    cr.set_source_rgba(1.0, 1.0, 0.0, 0.5)
                    radius = 2
                    first = False
                else:
                    cr.stroke()

    def draw_points(self, cr):
        if self.points:
            # convert coordinatets to current video pixel coordinates
            scale = self.video.scale / self.beamline.sample_video.resolution
            pos = numpy.array([
                self.beamline.sample_stage.x.get_position(),
                self.beamline.sample_stage.y.get_position(),
                self.beamline.omega.get_position()
            ])
            center = numpy.array(self.video.get_size()) / 2
            points = numpy.array(self.points) - pos
            points[:, 2] = numpy.cos(numpy.radians(points[:, 2]))
            points[:, 1] *= points[:, 2]
            points[:, :2] *= scale
            points[:, :2] += center

            cr.set_source_rgba(1.0, 0.25, 0.75, 0.5)
            for i, (x, y, a) in enumerate(points):
                cr.arc(x, y, 3 * abs(a) + 3, 0, 2.0 * 3.14)
                cr.fill()
                cr.move_to(x + 6, y)
                cr.show_text('P{}'.format(i))

    def add_point(self, *args, **kwargs):
        x = self.beamline.sample_stage.x.get_position()
        y = self.beamline.sample_stage.y.get_position()
        a = self.beamline.omega.get_position()
        self.points.append((x, y, a))
        print(self.points)

    def add_polygon_point(self, x, y):
        if not len(self.polygon):
            self.polygon.append((x, y))
        else:
            d = numpy.sqrt((x - self.polygon[0][0]) ** 2 + (y - self.polygon[0][1]))
            if d > 10:
                self.polygon.append((x, y))
            else:
                self.polygon.append(self.polygon[0])
                # make polygon clockwise
                self.make_polygon_grid()
                self.widget.microscope_grid_btn.set_active(False)

    def make_polygon_grid(self):
        step_size = 1e-3 * self.video.scale * self.beamline.aperture.get() / self.beamline.sample_video.resolution
        if len(self.polygon) == 3:
            points = numpy.array(self.polygon[:-1])
            grid_size = points[1] - points[0]
            shape = 1 + grid_size / step_size
            n = numpy.ceil(numpy.sqrt((shape ** 2).sum()))
            x = numpy.linspace(points[0][0], points[1][0], n)
            y = numpy.linspace(points[0][1], points[1][1], n)
            self.grid = numpy.array(zip(x, y))
        else:
            points = numpy.array(self.polygon)
            bbox = numpy.array([points.min(axis=0), points.max(axis=0)])
            full_grid = self.bbox_grid(bbox)
            poly = Path(points)
            radius = orientation(poly) * step_size

            self.grid = full_grid[poly.contains_points(full_grid, radius=radius)]

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
        y0 = int((cy - by) * self.video.scale) - hgw * math.sqrt(1 - 0.5 ** 2)

        return (x0, y0, grid_size, cell_size, nX, nY)

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

        yd = cell_size * math.sqrt(1 - 0.5 ** 2)
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

        yd = cell_size * math.sqrt(1 - 0.5 ** 2)
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
        except:
            cx, cy = self.beamline.sample_video.size
            cx //= 2
            cy //= 2
        xmm = (cx - im_x) * self.beamline.sample_video.resolution
        ymm = (cy - im_y) * self.beamline.sample_video.resolution
        return (im_x, im_y, xmm, ymm)

    @async
    def center_pixel(self, x, y):
        im_x, im_y, xmm, ymm = self._img_position(x, y)  # @UnusedVariable
        if not self.beamline.sample_stage.x.is_busy():
            self.beamline.sample_stage.x.move_by(-xmm, wait=True)
        if not self.beamline.sample_stage.y.is_busy():
            self.beamline.sample_stage.y.move_by(-ymm)

    def overlay_function(self, cr):
        self.draw_beam(cr)
        self.draw_measurement(cr)
        self.draw_grid(cr)
        self.draw_polygon(cr)
        self.draw_points(cr)
        return True

        # callbacks

    def on_aperture(self, obj, val):
        if self.grid is not None and self.polygon:
            self.make_polygon_grid()

    def on_gonio_mode(self, obj, mode):
        if mode != 'CENTERING':
            self.widget.microscope_loop_btn.set_sensitive(False)
            self.widget.microscope_crystal_btn.set_sensitive(False)
        else:
            self.widget.microscope_loop_btn.set_sensitive(True)
            self.widget.microscope_crystal_btn.set_sensitive(True)

    def on_scripts_started(self, obj, event=None):
        self.widget.microscope_toolbar.set_sensitive(False)

    def on_scripts_done(self, obj, event=None):
        self.widget.microscope_toolbar.set_sensitive(True)

    def on_realize(self, obj):
        self.pango_layout = self.video.create_pango_layout("")
        self.pango_layout.set_font_description(Pango.FontDescription('Monospace 8'))

    def on_configure(self, widget, event):
        frame_width, frame_height = event.width, event.height
        video_width, video_height = self.camera.size

        video_ratio = float(video_width) / video_height
        frame_ratio = float(frame_width) / frame_height

        if frame_ratio < video_ratio:
            width = frame_width
            height = int(width / video_ratio)
        else:
            height = frame_height
            width = int(video_ratio * height)

        self.video.scale = float(width) / video_width
        self._img_width, self._img_height = width, height
        self.set_size_request(width, height)
        # return True

    def on_save(self, obj=None, arg=None):
        img_filename, _ = dialogs.select_save_file(
            'Save Video Snapshot',
            formats=[('PNG Image', 'png'), ('JPEG Image', 'jpg')])
        if not img_filename:
            return
        if os.access(os.path.split(img_filename)[0], os.W_OK):
            self.save_image(img_filename)

    def on_center_loop(self, widget):
        script = self.scripts['CenterSample']
        script.start(crystal=False)
        return True

    def on_center_crystal(self, widget):
        script = self.scripts['CenterSample']
        script.start(crystal=True)
        return True

    def on_center_capillary(self, widget):
        script = self.scripts['CenterSample']
        script.start(capillary=True)
        return True

    def done_centering(self, obj, result):
        pass

    def error_centering(self, obj):
        pass

    def on_zoom_in(self, widget):
        self.beamline.sample_video.zoom(8)

    def on_zoom_out(self, widget):
        self.beamline.sample_video.zoom(2)

    def on_unzoom(self, widget):
        self.beamline.sample_video.zoom(5)

    def on_cw90(self, widget):
        cur_omega = int(self.beamline.omega.get_position())
        target = (cur_omega + 90)
        target = (target > 360) and (target % 360) or target
        self.beamline.omega.move_to(target)

    def on_ccw90(self, widget):
        cur_omega = int(self.beamline.omega.get_position())
        target = (cur_omega - 90)
        target = (target < -360) and (target % 360) or target
        self.beamline.omega.move_to(target)

    def on_rot180(self, widget):
        cur_omega = int(self.beamline.omega.get_position())
        target = (cur_omega + 180)
        target = (target > 360) and (target % 360) or target
        self.beamline.omega.move_to(target)

    def on_mouse_motion(self, widget, event):
        if event.is_hint:
            _, x, y, state = event.window.get_pointer()
        else:
            x = event.x
            y = event.y
        im_x, im_y, xmm, ymm = self._img_position(x, y)
        self.widget.microscope_pos_lbl.set_markup("%4d,%4d [%6.3f, %6.3f mm]" % (im_x, im_y, xmm, ymm))
        if 'GDK_BUTTON2_MASK' in event.get_state().value_names:
            self.measure_x2, self.measure_y2, = event.x, event.y
        elif 'GDK_BUTTON1_MASK' in event.get_state().value_names:
            if self.show_grid and self.edit_grid and not self._click_centering:
                self.clear_grid_cell(event.x, event.y)
        else:
            self.measuring = False

    def on_image_click(self, widget, event):
        if event.button == 1:
            if self.create_polygon:
                self.add_polygon_point(event.x, event.y)
            else:
                self.center_pixel(event.x, event.y)
        elif event.button == 2:
            self.measuring = True
            self.measure_x1, self.measure_y1 = event.x, event.y
            self.measure_x2, self.measure_y2 = event.x, event.y

    def on_fine_left(self, widget):
        # move left by 0.2 mm
        self.beamline.sample_stage.x.move_by(0.2)

    def on_fine_right(self, widget):
        # move right by 0.2 mm
        self.beamline.sample_stage.x.move_by(-0.2)
