import math
import os

import cairo
import numpy
from gi.repository import Gtk, Gdk
from zope.interface import Interface, Attribute, implementer

from mxdc import Registry, IBeamline, Object, Property
from mxdc.conf import save_cache, load_cache
from mxdc.devices.interfaces import ICenter
from mxdc.engines import centering
from mxdc.engines.scripting import get_scripts
from mxdc.utils import imgproc, colors, misc
from mxdc.utils.decorators import async_call
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs
from mxdc.widgets.video import VideoWidget
from . import common

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


@implementer(IMicroscope)
class Microscope(Object):
    class GridState:
        PENDING, COMPLETE = list(range(2))

    class ToolState(object):
        DEFAULT, CENTERING, GRID, MEASUREMENT = list(range(4))

    grid = Property(type=object)
    grid_xyz = Property(type=object)
    grid_state = Property(type=int, default=GridState.PENDING)
    grid_params = Property(type=object)
    grid_scores = Property(type=object)
    grid_cmap = Property(type=object)
    grid_bbox = Property(type=object)
    points = Property(type=object)

    tool = Property(type=int, default=ToolState.DEFAULT)
    mode = Property(type=object)

    def __init__(self, widget):
        super().__init__()
        self.timeout_id = None
        self.max_fps = 20
        self.fps_update = 0
        self.video_ready = False
        self.queue_overlay()
        self.overlay_surface = None
        self.overlay_ctx = None

        self.props.grid = None
        self.props.grid_xyz = None
        self.props.points = []
        self.props.grid_bbox = []
        self.props.grid_scores = {}
        self.props.grid_params = {}
        self.props.grid_state = self.GridState.PENDING
        self.props.grid_cmap = colors.ColorMapper(min_val=0, max_val=100)
        self.props.tool = self.ToolState.DEFAULT
        self.prev_tool = self.tool

        self.tool_cursors = {
            self.ToolState.DEFAULT: None,
            self.ToolState.CENTERING: Gdk.Cursor.new_from_name(Gdk.Display.get_default(), 'pointer'),
            self.ToolState.GRID: Gdk.Cursor.new_from_name(Gdk.Display.get_default(), 'cell'),
            self.ToolState.MEASUREMENT: Gdk.Cursor.new_from_name(Gdk.Display.get_default(), 'crosshair'),
        }

        self.ruler_box = numpy.array([[0, 0], [0, 0]])

        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.camera = self.beamline.sample_video
        self.centering = centering.Centering()
        self.setup()

        Registry.add_utility(IMicroscope, self)
        self.load_from_cache()

    def setup(self):

        # zoom
        low, med, high = self.beamline.config['zoom_levels']
        self.widget.microscope_zoomout_btn.connect('clicked', self.on_zoom, low)
        self.widget.microscope_zoom100_btn.connect('clicked', self.on_zoom, med)
        self.widget.microscope_zoomin_btn.connect('clicked', self.on_zoom, high)

        # rotate sample
        self.widget.microscope_ccw90_btn.connect('clicked', self.on_rotate, -90)
        self.widget.microscope_cw90_btn.connect('clicked', self.on_rotate, 90)
        self.widget.microscope_rot180_btn.connect('clicked', self.on_rotate, 180)

        # centering
        self.widget.microscope_loop_btn.connect('clicked', self.on_auto_center, 'loop')
        self.widget.microscope_capillary_btn.connect('clicked', self.on_auto_center, 'capillary')
        self.widget.microscope_diff_btn.connect('clicked', self.on_auto_center, 'diffraction')
        self.widget.microscope_ai_btn.connect('clicked', self.on_auto_center, 'external')

        self.beamline.manager.connect('mode', self.on_gonio_mode)
        self.beamline.goniometer.stage.connect('changed', self.update_grid)
        self.beamline.sample_zoom.connect('changed', self.update_grid)
        self.beamline.aperture.connect('changed', self.on_aperture)

        # Video Area
        self.video = VideoWidget(self.camera)
        self.beamline.camera_scale.connect('changed', self.on_camera_scale)
        self.widget.microscope_video_frame.add(self.video)

        # status, save, etc
        self.widget.microscope_save_btn.connect('clicked', self.on_save)
        self.widget.microscope_grid_btn.connect('toggled', self.toggle_grid_mode)
        self.widget.microscope_colorize_tbtn.connect('toggled', self.colorize)
        self.widget.microscope_point_btn.connect('clicked', self.on_save_point)
        self.widget.microscope_clear_btn.connect('clicked', self.clear_objects)

        # disable centering buttons on click
        self.centering.connect('started', self.on_scripts_started)
        self.centering.connect('done', self.on_scripts_done)

        aicenter = Registry.get_utility(ICenter)
        self.widget.microscope_ai_btn.set_sensitive(False)
        if aicenter:
            aicenter.connect('active', lambda obj, state: self.widget.microscope_ai_btn.set_sensitive(state))

        # lighting monitors
        self.monitors = []
        for key in ['backlight', 'frontlight', 'uvlight']:
            light = getattr(self.beamline, 'sample_{}'.format(key), None)
            scale = getattr(self.widget, 'microscope_{}_scale'.format(key), None)
            box = getattr(self.widget, '{}_box'.format(key), None)
            if all([light, scale, box]):
                scale.set_adjustment(Gtk.Adjustment(0, 0.0, 100.0, 1.0, 1.0, 10))
                self.monitors.append(
                    common.ScaleMonitor(scale, light),
                )
                box.set_sensitive(True)
            else:
                box.destroy()
            if key == 'uvlight':
                color = Gdk.RGBA()
                color.parse("#9B59B6")
                box.override_color(Gtk.StateFlags.NORMAL, color)

        self.video.connect('motion-notify-event', self.on_mouse_motion)
        self.video.connect('scroll-event', self.on_mouse_scroll)
        self.video.connect('button-press-event', self.on_mouse_press)
        self.video.connect('button-release-event', self.on_mouse_release)
        self.video.set_overlay_func(self.overlay_function)
        self.video.connect('configure-event', self.setup_grid)
        self.scripts = get_scripts()

        # Connect Grid signals
        self.connect('notify::grid-xyz', self.update_grid)
        self.connect('notify::tool', self.on_tool_changed)

    def change_tool(self, tool=None):
        if tool is None:
            self.props.tool, self.prev_tool = self.prev_tool, self.tool
        elif self.props.tool != tool:
            self.props.tool, self.prev_tool = tool, self.tool

    def setup_grid(self, *args, **kwargs):
        if not self.video_ready:
            self.video_ready = True
            for param in ['grid-xyz', 'points', 'grid-params']:
                self.connect('notify::{}'.format(param), self.save_to_cache)
        self.update_grid()

    def save_to_cache(self, *args, **kwargs):
        cache = {
            'points': self.props.points,
            'grid-xyz': None if self.props.grid_xyz is None else self.props.grid_xyz.tolist(),
            'grid-params': self.props.grid_params,
            'grid-scores': self.props.grid_scores,
            'grid-state': self.props.grid_state,
        }
        save_cache(cache, 'microscope')

    def load_from_cache(self):
        cache = load_cache('microscope')
        if cache and isinstance(cache, dict):
            for name, value in list(cache.items()):
                if name == 'grid-xyz':
                    value = None if not isinstance(value, list) else numpy.array(value)
                if name == 'points':
                    value = [tuple(point) for point in value]
                self.set_property(name, value)

    def save_image(self, filename):
        self.video.save_image(filename)

    def draw_beam(self, cr):
        radius = 0.5e-3 * self.beamline.aperture.get() / self.video.mm_scale()
        tick_in = radius * 0.8
        tick_out = radius * 1.2
        center = numpy.array(self.video.get_size()) / 2

        cr.set_source_rgba(1.0, 0.25, 0.0, 0.5)
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
        if self.tool == self.ToolState.MEASUREMENT:
            cr.set_font_size(10)
            (x1, y1), (x2, y2) = self.ruler_box
            dist = 1000 * self.video.mm_scale() * math.sqrt((x2 - x1) ** 2.0 + (y2 - y1) ** 2.0)
            cr.set_source_rgba(0.0, 0.5, 1.0, 1.0)
            cr.set_line_width(1.0)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()
            label = '{:0.0f} µm'.format(dist)
            xb, yb, w, h = cr.text_extents(label)[:4]
            cr.move_to(x1 - w*(int(x2>x1) + xb/w), y1 - h*(int(y2>y1) + yb/h))
            cr.show_text(label)

    def draw_bbox(self, cr):
        if self.tool == self.ToolState.GRID and len(self.props.grid_bbox):
            cr.set_font_size(10)
            cr.set_line_width(1.0)
            cr.set_source_rgba(0.0, 0.5, 1.0, 1.0)

            # rectangle
            (x1, y1), (x2, y2) = self.props.grid_bbox
            cr.rectangle(x1, y1, x2-x1, y2-y1)
            cr.stroke()

            # center
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2

            # width
            width = 1000 * self.video.mm_scale() * abs(x2 - x1)
            w_label = '{:0.0f} µm'.format(width)
            xb, yb, w, h = cr.text_extents(w_label)[:4]
            cr.move_to(cx - w/2, y1 - h/2)
            cr.show_text(w_label)

            # height
            height = 1000 * self.video.mm_scale() * abs(y2 - y1)
            h_label = '{:0.0f} µm'.format(height)
            cr.move_to(x2 + h/2, cy)
            cr.show_text(h_label)

    def draw_grid(self, cr):
        if self.props.grid is not None:
            radius = 0.5e-3 * self.beamline.aperture.get() / self.video.mm_scale()
            cr.set_line_width(1.0)
            cr.set_font_size(8)
            for i, (x, y, z) in enumerate(self.props.grid):
                if i+1 in self.props.grid_scores:
                    col = self.props.grid_cmap.rgba_values(self.props.grid_scores[i+1], alpha=0.5)
                    cr.set_source_rgba(*col)
                    cr.arc(x, y, radius, 0, 2.0 * 3.14)
                    cr.fill()
                cr.set_source_rgba(0.0, 0.5, 1.0, 1.0)
                cr.arc(x, y, radius, 0, 2.0 * 3.14)
                cr.stroke()
                name = '{}'.format(i+1)
                xb, yb, w, h = cr.text_extents(name)[:4]
                cr.move_to(x - w / 2. - xb, y - h / 2. - yb)
                cr.show_text(name)
                cr.stroke()

    def draw_points(self, cr):
        if self.props.points:
            cr.save()
            mm_scale = self.video.mm_scale()
            radius = 0.5e-3 * self.beamline.aperture.get() / (16 * mm_scale)
            cur_point = numpy.array(self.beamline.goniometer.stage.get_xyz())
            center = numpy.array(self.video.get_size()) / 2
            points = numpy.array(self.props.points) - cur_point
            xyz = numpy.zeros_like(points)
            xyz[:, 0], xyz[:, 1], xyz[:, 2] = self.beamline.goniometer.stage.xyz_to_screen(
                points[:, 0], points[:, 1], points[:, 2]
            )
            xyz /= mm_scale
            radii = (4.0 - (xyz[:, 2] / (center[1] * 0.25))) * radius
            xyz[:, :2] += center
            cr.set_source_rgba(1.0, 0.25, 0.75, 0.5)
            for i, (x, y, z) in enumerate(xyz):
                cr.arc(x, y, radii[i], 0, 2.0 * 3.14)
                cr.fill()
                cr.move_to(x + 6, y)
                cr.show_text('P{}'.format(i + 1))
                cr.stroke()
            cr.restore()

    def clear_objects(self, *args, **kwargs):
        self.props.grid = None
        self.props.grid_xyz = None
        self.props.grid_scores = {}
        self.props.points = []
        self.props.grid_bbox = []
        if self.tool == self.ToolState.GRID:
            self.change_tool(self.ToolState.CENTERING)
        self.widget.microscope_grid_btn.set_active(False)
        self.queue_overlay()

    def toggle_grid_mode(self, *args, **kwargs):
        if self.widget.microscope_grid_btn.get_active():
            self.change_tool(self.ToolState.GRID)
            self.props.grid_bbox = []
        else:
            self.widget.microscope_grid_btn.set_active(False)
            self.change_tool()
        self.queue_overlay()

    def auto_grid(self, *args, **kwargs):
        img = self.camera.get_frame()
        polygon = imgproc.find_profile(img, scale=0.25)
        points = numpy.array(polygon)
        self.props.grid_bbox = numpy.array([points.min(axis=0), points.max(axis=0)])

    def add_point(self, point):
        self.props.points = self.props.points + [point]
        self.queue_overlay()

    def make_grid(self, bbox=None, points=None, scaled=True, center=True):
        if points is not None:
            points = numpy.array(points)
            bbox = numpy.array([points.min(axis=0), points.max(axis=0)])
        elif bbox is None:
            bbox = self.props.grid_bbox

        if not isinstance(bbox, numpy.ndarray):
            bbox = numpy.array(bbox)

        factor = 1.0 if scaled else self.video.scale
        step_size = 1e-3 * self.beamline.aperture.get() / self.video.mm_scale()
        w, h = 1000*numpy.abs(numpy.diff(bbox, axis=0).ravel() * self.video.mm_scale()).round(4)

        # grid too small exit and clear
        if max(w, h) < 2 * step_size:
            self.props.grid_bbox = []
            self.queue_overlay()
            self.props.grid_params = {}
            return

        bounds = bbox * factor

        grid = misc.grid_from_bounds(bounds, step_size, tight=False)
        dx, dy = self.video.screen_to_mm(*bounds.mean(axis=0))[2:]

        angle = self.beamline.goniometer.omega.get_position()
        ox, oy, oz = self.beamline.goniometer.stage.get_xyz()
        xmm, ymm = self.video.screen_to_mm(grid[:, 0], grid[:, 1])[2:]
        gx, gy, gz = self.beamline.goniometer.stage.xvw_to_xyz(-xmm, -ymm, numpy.radians(angle))
        grid_xyz = numpy.dstack([gx + ox, gy + oy, gz + oz])[0]

        properties = {
            'grid_state': self.GridState.PENDING,
            'grid_xyz': grid_xyz.round(4),
            'grid_bbox': [],
            'grid_params': {
                'width': w,
                'height': h,
                'angle': angle,
            },
            'grid_scores': {}
        }

        for k, v in properties.items():
            self.set_property(k, v)
        if center:
            self.beamline.goniometer.stage.move_screen_by(-dx, -dy, 0.0)

    def add_grid_score(self, position, score):
        self.props.grid_scores[position] = score
        self.props.grid_cmap.autoscale(list(self.props.grid_scores.values()))
        self.props.grid_state = self.GridState.COMPLETE

    def load_grid(self, grid_xyz, params, scores):
        self.props.grid_xyz = grid_xyz
        self.props.grid_scores = scores
        self.props.grid_params = params
        self.props.grid_state = self.GridState.COMPLETE
        self.props.grid_cmap.autoscale(list(self.props.grid_scores.values()))

    @async_call
    def center_pixel(self, x, y, force=False):
        if self.tool == self.ToolState.CENTERING or force:
            ix, iy, xmm, ymm = self.video.screen_to_mm(x, y)
            if not self.beamline.goniometer.stage.is_busy():
                self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0)

    def create_overlay_surface(self):
        self.overlay_surface = cairo.ImageSurface(
            cairo.FORMAT_ARGB32, self.video.display_width, self.video.display_height
        )
        self.overlay_ctx = cairo.Context(self.overlay_surface)

    def overlay_function(self, cr):
        self.update_overlay()
        cr.set_source_surface(self.overlay_surface, 0, 0)
        cr.paint()

    def queue_overlay(self):
        self.overlay_dirty = True

    def update_overlay(self):
        if self.overlay_dirty or self.overlay_surface is None:
            self.create_overlay_surface()
            self.draw_beam(self.overlay_ctx)
            self.draw_grid(self.overlay_ctx)
            self.draw_bbox(self.overlay_ctx)
            self.draw_points(self.overlay_ctx)
            self.draw_measurement(self.overlay_ctx)
            self.overlay_dirty = False

    # callbacks
    def update_grid(self, *args, **kwargs):
        if self.props.grid_xyz is not None:
            center = numpy.array(self.video.get_size()) * 0.5
            points = self.grid_xyz - numpy.array(self.beamline.goniometer.stage.get_xyz())
            xyz = numpy.empty_like(points)
            xyz[:, 0], xyz[:, 1], xyz[:, 2] = self.beamline.goniometer.stage.xyz_to_screen(
                points[:, 0], points[:, 1],  points[:, 2]
            )
            xyz /= self.video.mm_scale()
            xyz[:, :2] += center
            self.props.grid = xyz
        else:
            self.props.grid = None
        self.queue_overlay()

    def colorize(self, button):
        self.video.set_colorize(state=button.get_active())

    def on_save_point(self, *args, **kwargs):
        self.add_point(self.beamline.goniometer.stage.get_xyz())
        self.save_to_cache()

    def on_tool_changed(self, *args, **kwargs):
        window = self.widget.microscope_bkg.get_window()
        if window:
            window.set_cursor(self.tool_cursors[self.props.tool])

    def on_camera_scale(self, obj, value):
        self.queue_overlay()
        self.video.set_pixel_size(value)

    def on_gonio_mode(self, obj, mode):
        self.props.mode = mode
        centering_tool = self.mode.name in ['CENTER', 'ALIGN']
        self.widget.microscope_centering_box.set_sensitive(centering_tool)
        self.widget.microscope_grid_box.set_sensitive(centering_tool)
        if centering_tool:
            self.change_tool(self.ToolState.CENTERING)
        else:
            self.change_tool(self.ToolState.DEFAULT)

        if self.mode.name == 'ALIGN':
            self.widget.microscope_colorize_tbtn.set_active(True)
        elif self.mode.name not in ['BUSY', 'UNKNOWN']:
            self.widget.microscope_colorize_tbtn.set_active(False)

    def on_scripts_started(self, obj, event=None):
        self.widget.microscope_toolbar.set_sensitive(False)

    def on_scripts_done(self, obj, event=None):
        self.widget.microscope_toolbar.set_sensitive(True)

    def on_save(self, obj=None, arg=None):
        img_filename, _ = dialogs.select_save_file(
            'Save Video Snapshot',
            formats=[('PNG Image', 'png'), ('JPEG Image', 'jpg')])
        if not img_filename:
            return
        if os.access(os.path.split(img_filename)[0], os.W_OK):
            self.save_image(img_filename)

    def on_auto_center(self, widget, method='loop'):
        self.centering.configure(method=method)
        self.centering.start()
        return True

    def on_zoom(self, widget, position):
        self.camera.zoom(position)

    def on_aperture(self, obj, value):
        if self.grid_xyz is not None:
            center = numpy.array(self.video.get_size()) * 0.5
            points = self.grid_xyz - numpy.array(self.beamline.goniometer.stage.get_xyz())
            xyz = numpy.empty_like(points)
            xyz[:, 0], xyz[:, 1], xyz[:, 2] = self.beamline.goniometer.stage.xyz_to_screen(
                points[:, 0], points[:, 1], points[:, 2]
            )
            xyz /= self.video.mm_scale()
            xyz[:, :2] += center
            self.make_grid(points=xyz[:, :2], center=False)
        else:
            self.queue_overlay()

    def on_rotate(self, widget, angle):
        cur_omega = int(self.beamline.goniometer.omega.get_position())
        target = (cur_omega + angle)
        target = (target > 360) and (target % 360) or target
        self.beamline.goniometer.omega.move_to(target)

    def on_mouse_scroll(self, widget, event):
        if 'GDK_CONTROL_MASK' in event.get_state().value_names and self.mode.name in ['CENTER', 'ALIGN']:
            if event.direction == Gdk.ScrollDirection.UP:
                self.on_rotate(widget, 45)
            elif event.direction == Gdk.ScrollDirection.DOWN:
                self.on_rotate(widget, -45)

    def on_mouse_motion(self, widget, event):
        if event.is_hint:
            _, x, y, state = event.window.get_pointer()
        else:
            x, y = event.x, event.y
        ix, iy, xmm, ymm = self.video.screen_to_mm(x, y)
        self.widget.microscope_pos_lbl.set_markup(
            f"<small><tt>X:{ix:5.0f} {xmm:6.3f} mm\nY:{iy:5.0f} {ymm:6.3f} mm</tt></small>"
        )

        if Gdk.ModifierType.BUTTON2_MASK & event.state:
            self.ruler_box[1] = (x, y)
            self.queue_overlay()
        elif Gdk.ModifierType.CONTROL_MASK & event.state and self.mode.name in ['COLLECT']:
            self.change_tool(tool=self.ToolState.CENTERING)
        elif self.tool == self.ToolState.GRID and len(self.props.grid_bbox):
            if Gdk.ModifierType.BUTTON1_MASK & event.state:
                self.props.grid_bbox[-1] = (x, y)
            self.queue_overlay()
        elif self.tool == self.ToolState.MEASUREMENT:
            self.change_tool()
            self.queue_overlay()
        elif self.tool == self.ToolState.CENTERING and self.mode.name in ['COLLECT']:
            self.change_tool()

    def on_mouse_press(self, widget, event):
        if event.button == 1:
            if self.tool == self.ToolState.GRID:
                self.props.grid_bbox = [(event.x, event.y), (event.x, event.y)]
                self.queue_overlay()
            else:
                self.center_pixel(event.x, event.y)
        elif event.button == 2:
            self.change_tool(self.ToolState.MEASUREMENT)
            self.ruler_box[0] = (event.x, event.y)
            self.ruler_box[1] = (event.x, event.y)
            self.queue_overlay()

    def on_mouse_release(self, widget, event):
        if event.button == 1:
            if self.tool == self.ToolState.GRID and self.grid_bbox:
                self.make_grid()
                self.widget.microscope_grid_btn.set_active(False)
