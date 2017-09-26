import math
import os
import time

import common
import numpy
from gi.repository import Gtk, Pango, Gdk, GObject
from matplotlib.path import Path
from mxdc.beamline.mx import IBeamline
from mxdc.engines.scripting import get_scripts
from mxdc.utils import imgproc, colors
from mxdc.utils.decorators import async_call
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs
from mxdc.widgets.video import VideoWidget
from twisted.python.components import globalRegistry
from zope.interface import Interface, Attribute, implements

logger = get_module_logger(__name__)


def orientation(p):
    verts = p.vertices
    orient = ((verts[1:, 0] - verts[:-1, 0]) * (verts[1:, 1] + verts[:-1, 1])).sum()
    return -numpy.sign(orient) or 1


class IMicroscope(Interface):
    """Sample information database."""
    grid = Attribute("A list of x, y points for the grid in screen coordinates")
    grid_xyz = Attribute("A list of x, y, z points for the grid in local coordinates")
    grid_state = Attribute("State of the grid, PENDING, COMPLETE ")
    grid_params = Attribute("A dictionary of grid reference parameters")
    grid_scores = Attribute("An integer-keyed dictionary of floats")
    polygon = Attribute("A list of points")
    points = Attribute("A list of points")


class Microscope(GObject.GObject):
    implements(IMicroscope)

    class GridState:
        PENDING, COMPLETE = range(2)

    grid = GObject.Property(type=object)
    grid_xyz = GObject.Property(type=object)
    grid_state = GObject.Property(type=int, default=GridState.PENDING)
    grid_params = GObject.Property(type=object)
    grid_scores = GObject.Property(type=object)
    grid_cmap = GObject.Property(type=object)
    points = GObject.Property(type=object)
    polygon = GObject.Property(type=object)

    def __init__(self, widget):
        super(Microscope, self).__init__()
        self.timeout_id = None
        self.max_fps = 20
        self.fps_update = 0

        self.props.grid = None
        self.props.grid_xyz = None
        self.props.points = []
        self.props.polygon = []
        self.props.grid_scores = {}
        self.props.grid_params = {}
        self.props.grid_state = self.GridState.PENDING
        self.props.grid_cmap = colors.ColorMapper(min_val=0, max_val=100)

        self.allow_centering = False
        self.create_polygon = False
        self.measuring = False
        self.measurement = numpy.array([[0, 0], [0, 0]])

        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.camera = self.beamline.sample_video
        self.setup()
        self.video.set_overlay_func(self.overlay_function)
        globalRegistry.register([], IMicroscope, '', self)

    def setup(self):
        # zoom
        self.widget.microscope_zoomout_btn.connect('clicked', self.on_zoom, 2)
        self.widget.microscope_zoomin_btn.connect('clicked', self.on_zoom, 8)
        self.widget.microscope_zoom100_btn.connect('clicked', self.on_zoom, 5)

        # rotate sample
        self.widget.microscope_ccw90_btn.connect('clicked', self.on_rotate, -90)
        self.widget.microscope_cw90_btn.connect('clicked', self.on_rotate, 90)
        self.widget.microscope_rot180_btn.connect('clicked', self.on_rotate, 180)

        # centering
        self.widget.microscope_loop_btn.connect('clicked', self.on_center_loop)
        self.widget.microscope_crystal_btn.connect('clicked', self.on_center_crystal)
        self.widget.microscope_capillary_btn.connect('clicked', self.on_center_capillary)
        self.beamline.goniometer.connect('mode', self.on_gonio_mode)
        self.beamline.sample_stage.connect('changed', self.update_grid)
        self.beamline.sample_zoom.connect('changed', self.update_grid)
        self.connect('notify::grid-xyz', self.update_grid)

        # Video Area
        self.video = VideoWidget(self.camera)
        self.widget.microscope_video_frame.add(self.video)

        # status, save, etc
        self.widget.microscope_save_btn.connect('clicked', self.on_save)
        self.widget.microscope_grid_btn.connect('toggled', self.make_grid)
        self.widget.microscope_point_btn.connect('clicked', self.add_point)
        self.widget.microscope_clear_btn.connect('clicked', self.clear_objects)

        # lighting monitors
        self.monitors = []
        for key in ['backlight', 'frontlight', 'uvlight']:
            light = getattr(self.beamline, 'sample_{}'.format(key), None)
            scale = getattr(self.widget, 'microscope_{}_scale'.format(key), None)
            box = getattr(self.widget, '{}_box'.format(key), None)
            if all([light, scale, box]):
                self.monitors.append(
                    common.ScaleMonitor(scale, light),
                )
                scale.set_adjustment(Gtk.Adjustment(0, 0.0, 100.0, 1.0, 1.0, 10))
                box.set_sensitive(True)
            else:
                box.destroy()
            if key == 'uvlight':
                color = Gdk.RGBA(red=0.5, green=0.1, blue=0.9, alpha=0.75)
                box.override_color(Gtk.StateFlags.NORMAL, color)

        self.video.connect('motion-notify-event', self.on_mouse_motion)
        self.video.connect('button-press-event', self.on_image_click)
        self.video.set_overlay_func(self.overlay_function)
        self.video.connect('realize', self.on_realize)

        self.scripts = get_scripts()

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
        radius = 0.5e-3*self.beamline.aperture.get()/self.video.mm_scale()
        tick_in = radius * 0.8
        tick_out = radius * 1.2
        center = numpy.array(self.video.get_size()) / 2

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
        if self.measuring:
            (x1, y1), (x2, y2) = self.measurement
            dist = self.video.mm_scale() * math.sqrt((x2 - x1) ** 2.0 + (y2 - y1) ** 2.0)
            cr.set_source_rgba(0.2, 1.0, 0.2, 0.3)
            cr.set_line_width(4.0)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()
            label = '{:0.3f} mm'.format(dist)
            lx, ly = (x1 + x2)*0.5, (y1 + y2)*0.5
            xb, yb, w, h = cr.text_extents(label)[:4]
            cr.move_to(lx + h, ly + h)
            cr.show_text(label)
            cr.stroke()

    def clear_objects(self, *args, **kwargs):
        self.props.grid = None
        self.props.grid_xyz = None
        self.props.grid_scores = {}
        self.props.points = []
        self.props.polygon = []
        self.create_polygon = False
        self.widget.microscope_grid_btn.set_active(False)

    def make_grid(self, *args, **kwargs):
        if self.widget.microscope_grid_btn.get_active():
            self.create_polygon = True
            self.widget.microscope_bkg.get_window().set_cursor(Gdk.Cursor(Gdk.CursorType.CROSSHAIR))
            self.props.polygon = []
        else:
            self.create_polygon = False
            self.widget.microscope_bkg.get_window().set_cursor(None)

    def bbox_grid(self, bbox):
        step_size = 1e-3 * self.beamline.aperture.get() / self.video.mm_scale()
        grid_size = bbox[1] - bbox[0]

        nX, nY = grid_size / step_size
        nX = numpy.ceil(nX)
        nY = numpy.ceil(numpy.sqrt(2) * nY)

        xi = numpy.linspace(bbox[0][0], bbox[1][0], nX)
        yi = numpy.linspace(bbox[0][1], bbox[1][1], nY)
        x_ij, y_ij = numpy.meshgrid(xi, yi, sparse=False, indexing='ij')
        radius = step_size * 0.5
        return numpy.array([
            (x_ij[i, j] + (j % 2) * radius, y_ij[i, j], 0.0)
            for j in numpy.arange(nY).astype(int)
            for i in numpy.arange(nX).astype(int)
            if nX - i != j % 2
        ])

    def auto_grid(self, *args, **kwargs):
        img = self.camera.get_frame()
        bbox = self.video.scale * imgproc.get_sample_bbox2(img)
        self.props.grid = self.bbox_grid(bbox)
        self.props.grid_params = {
            'origin': self.beamline.sample_stage.get_xyz(),
            'angle': self.beamline.omega.get_position()
        }
        self.props.grid_state = self.GridState.PENDING
        self.props.grid_scores = {}

    def draw_grid(self, cr):
        if self.props.grid is not None:
            radius = 0.5e-3 * self.beamline.aperture.get() / self.video.mm_scale()

            cr.set_line_width(1.0)
            cr.set_font_size(8)
            for i, (x, y, z) in enumerate(self.props.grid):
                if i in self.props.grid_scores:
                    col = self.props.grid_cmap.rgba_values(self.props.grid_scores[i], alpha=0.5)
                    cr.set_source_rgba(*col)
                    cr.arc(x, y, radius, 0, 2.0 * 3.14)
                    cr.fill()
                cr.set_source_rgba(0.2, 1.0, 0.5, 0.5)
                cr.arc(x, y, radius, 0, 2.0 * 3.14)
                cr.stroke()
                name = '{}'.format(i)
                xb, yb, w, h = cr.text_extents(name)[:4]
                cr.move_to(x - w / 2. - xb, y - h / 2. - yb)
                cr.show_text(name)
                cr.stroke()

    def draw_polygon(self, cr):
        if self.props.polygon:
            cr.set_source_rgba(0.0, 1.0, 0.0, 0.5)
            cr.set_line_width(1.0)
            cr.move_to(*self.props.polygon[0])
            for x, y in self.props.polygon[1:]:
                cr.line_to(x, y)
            cr.stroke()
            cr.set_source_rgba(1.0, 0.0, 0.0, 0.5)
            first = True
            radius = 5
            for x, y in self.props.polygon:
                cr.arc(x, y, radius, 0, 2.0 * 3.14)
                if first:
                    cr.fill()
                    cr.set_source_rgba(1.0, 1.0, 0.0, 0.5)
                    radius = 2
                    first = False
                else:
                    cr.stroke()

    def draw_points(self, cr):
        if self.props.points:
            # convert coordinatets to current video pixel coordinates
            cr.save()
            mm_scale = self.video.mm_scale()
            radius = 0.5e-3*self.beamline.aperture.get()/(8*mm_scale)
            cur_point = numpy.array(self.beamline.sample_stage.get_xyz())
            center = numpy.array(self.video.get_size()) / 2
            points = numpy.array(self.props.points) - cur_point
            xyz = numpy.zeros_like(points)
            xyz[:,0], xyz[:,1], xyz[:,2] = self.beamline.sample_stage.xyz_to_screen(points[:, 0], points[:, 1], points[:, 2])
            xyz /= mm_scale
            radii = (4.0 - (xyz[:, 2] / (center[1]*0.25)))*radius
            xyz[:, :2] += center
            cr.set_source_rgba(1.0, 0.25, 0.75, 0.5)
            for i, (x, y, z) in enumerate(xyz):
                cr.arc(x, y, radii[i], 0, 2.0 * 3.14)
                cr.fill()
                cr.move_to(x + 6, y)
                cr.show_text('P{}'.format(i+1))
                cr.stroke()
            cr.restore()

    def add_point(self, *args, **kwargs):
        self.props.points = self.props.points + [self.beamline.sample_stage.get_xyz()]

    def add_polygon_point(self, x, y):
        radius = 0.5e-3*self.beamline.aperture.get() / self.video.mm_scale()
        if not len(self.props.polygon):
            self.props.polygon.append((x, y))
        else:
            d = numpy.sqrt((x - self.props.polygon[0][0]) ** 2 + (y - self.props.polygon[0][1]))
            if d > radius:
                self.props.polygon.append((x, y))
            else:
                self.props.polygon.append(self.props.polygon[0])
                self.make_polygon_grid()
                self.widget.microscope_grid_btn.set_active(False)

    def make_polygon_grid(self):
        step_size = 1e-3*self.beamline.aperture.get() / self.video.mm_scale()
        if len(self.props.polygon) == 3:
            points = numpy.array(self.props.polygon[:-1])
            grid_size = points[1] - points[0]
            shape = 1 + grid_size / step_size
            n = numpy.ceil(numpy.sqrt((shape ** 2).sum()))
            x = numpy.linspace(points[0][0], points[1][0], n)
            y = numpy.linspace(points[0][1], points[1][1], n)
            grid = numpy.dstack((x, y, numpy.zeros_like(y)))[0]

        else:
            points = numpy.array(self.props.polygon)
            bbox = numpy.array([points.min(axis=0), points.max(axis=0)])
            full_grid = self.bbox_grid(bbox)
            poly = Path(points)
            radius = orientation(poly) * step_size
            grid = full_grid[poly.contains_points(full_grid[:,:2], radius=radius)]

        xmm, ymm = self.video.screen_to_mm(grid[:, 0], grid[:, 1])[2:]
        ox, oy, oz =self.beamline.sample_stage.get_xyz()
        angle = self.beamline.omega.get_position()
        gx, gy, gz = self.beamline.sample_stage.xvw_to_xyz(-xmm, -ymm, numpy.radians(angle))
        grid_xyz = numpy.dstack([gx + ox, gy + oy, gz + oz])[0]

        self.props.grid_state = self.GridState.PENDING
        self.props.grid_xyz = grid_xyz
        self.props.grid_params = {
            'origin': (ox, oy, oz),
            'angle': angle
        }
        self.props.grid_scores = {}
        self.props.polygon = [] # delete polygon after making grid

    def add_grid_score(self, position, score):
        self.props.grid_scores[position] = score
        self.props.grid_cmap.autoscale(self.props.grid_scores.values())
        self.props.grid_state = self.GridState.COMPLETE

    def load_grid(self, grid_xyz, params, scores):
        self.props.grid_xyz = grid_xyz
        self.props.grid_scores = scores
        self.props.grid_params = params
        self.props.grid_state = self.GridState.COMPLETE
        self.props.grid_cmap.autoscale(self.props.grid_scores.values())

    def lock_grid(self):
        self.show_grid = True
        self.edit_grid = False

    @async_call
    def center_pixel(self, x, y):
        ix, iy, xmm, ymm = self.video.screen_to_mm(x, y)
        if not self.beamline.sample_stage.is_busy():
            self.beamline.sample_stage.move_screen_by(-xmm, -ymm, 0.0)

    def overlay_function(self, cr):
        # FIXME: For performance and efficiency, use overlay surface and only recreate it if objects have changed
        self.draw_beam(cr)
        self.draw_measurement(cr)
        self.draw_grid(cr)
        self.draw_polygon(cr)
        self.draw_points(cr)
        return True

    # callbacks

    def update_grid(self, *args, **kwargs):
        if self.props.grid_xyz is not None:
            center = numpy.array(self.video.get_size()) * 0.5
            points = self.grid_xyz - numpy.array(self.beamline.sample_stage.get_xyz())
            xyz = numpy.empty_like(points)
            xyz[:,0],  xyz[:,1], xyz[:,2] = self.beamline.sample_stage.xyz_to_screen(points[:, 0], points[:, 1], points[:, 2])
            xyz /= self.video.mm_scale()
            xyz[:, :2] += center
            self.props.grid = xyz
        else:
            self.props.grid = None


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

    def on_zoom(self, widget, position):
        self.camera.zoom(position)

    def on_rotate(self, widget, angle):
        cur_omega = int(self.beamline.omega.get_position())
        target = (cur_omega + angle)
        target = (target > 360) and (target % 360) or target
        self.beamline.omega.move_to(target)

    def on_mouse_motion(self, widget, event):
        if event.is_hint:
            _, x, y, state = event.window.get_pointer()
        else:
            x, y = event.x, event.y
        ix, iy, xmm, ymm = self.video.screen_to_mm(x, y)
        self.widget.microscope_pos_lbl.set_markup(
            "<small><tt>X:{:5.0f} {:6.3f} mm\nY:{:5.0f} {:6.3f} mm</tt></small>".format(ix, xmm, iy, ymm)
        )
        if 'GDK_BUTTON2_MASK' in event.get_state().value_names:
            self.measurement[1] = (x, y)
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
            self.measurement[0] = (event.x, event.y)
            self.measurement[1] = (event.x, event.y)
