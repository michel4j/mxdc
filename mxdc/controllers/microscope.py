import os
import time
from pathlib import Path

import numpy
from gi.repository import Gtk, Gdk, Gio, GLib
from zope.interface import Interface, Attribute, implementer

from mxdc import Registry, IBeamline, Object, Property
from mxdc.conf import save_cache, load_cache
from mxdc.engines import centering
from mxdc.engines.scripting import get_scripts
from mxdc.utils import colors, misc, datatools
from mxdc.utils.decorators import async_call
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs
from mxdc.widgets.video import VideoWidget, VideoView
from . import common
from .samplestore import ISampleStore

logger = get_module_logger(__name__)

MIN_COORD_UPDATE_PERIOD = .1  # minimum time between grid recalculations


def orientation(p):
    verts = p.vertices
    orient = ((verts[1:, 0] - verts[:-1, 0]) * (verts[1:, 1] + verts[:-1, 1])).sum()
    return -numpy.sign(orient) or 1


class IMicroscope(Interface):
    """Sample information database."""
    grid = Attribute("A list of x, y points for the grid in screen coordinates")
    grid_xyz = Attribute("A list of x, y, z points for the grid in local coordinates")
    grid_params = Attribute("A dictionary of grid reference parameters")
    grid_scores = Attribute("A 2d MxN array representing the scores of the grid")
    grid_index = Attribute("A list of point indices for each cell in the grid by traversal order")
    grid_frames = Attribute("An integer arry of frame numbers for each cell")
    points = Attribute("A list of points")


POINTS_MENU_TMPL = """
<menu id='app-menu'>
  <section>
    <item>
      <attribute name='label' translatable='yes'>_Save Point</attribute>
      <attribute name='action'>microscope.save_point</attribute>
    </item>
  </section>
  <section>
    {points}
  </section>
</menu>
"""
POINT_ITEM_TMPL = """
    <item>
      <attribute name='label' translatable='yes'>Goto {name}</attribute>
      <attribute name='action'>microscope.center_point</attribute>
      <attribute name='target'>{name}</attribute>
    </item>
"""


@implementer(IMicroscope)
class Microscope(Object):
    class ToolState(object):
        DEFAULT, CENTERING, GRID, MEASUREMENT = list(range(4))

    grid = Property(type=object)
    grid_xyz = Property(type=object)
    grid_params = Property(type=object)
    grid_scores = Property(type=object)
    grid_index = Property(type=object)
    grid_frames = Property(type=object)
    grid_cmap = Property(type=object)
    grid_bbox = Property(type=object)

    tool = Property(type=int, default=ToolState.DEFAULT)
    mode = Property(type=object)

    def __init__(self, widget):
        super().__init__()
        self.timeout_id = None
        self.max_fps = 20
        self.fps_update = 0
        self.video_ready = False
        self.show_annotations = False
        self.viewer = None
        self.last_coord_update = time.time()
        self.actions = Gio.SimpleActionGroup()

        self.points = Gtk.ListStore(str, object)
        self.points_menu = Gio.Menu()
        self.points_menu_points = Gio.Menu()
        self.props.grid = None
        self.props.grid_xyz = None
        self.props.grid_index = None
        self.props.grid_frames = None
        self.props.grid_bbox = []
        self.props.grid_scores = None
        self.props.grid_params = {}
        self.props.grid_cmap = colors.ColorMapper(vmin=0, vmax=100)
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
        # create actions and points menu
        actions = {
            'save_point': (self.on_save_point, None),
            'center_point': (self.on_center_point, GLib.VariantType("s")),
        }

        # menu = Gtk.Builder.new_from_string('/org/gtk/mxdc/data/menus.ui')
        # self.builder.app_menu_btn.set_menu_model(menu.get_object('app-menu'))

        for name, info in actions.items():
            action = Gio.SimpleAction.new(name, info[1])
            action.connect("activate", info[0])
            action.set_enabled(True)
            self.actions.add_action(action)

        self.widget.microscope_box.insert_action_group('microscope', self.actions)

        self.points_menu.append_item(Gio.MenuItem.new('Save Point', 'microscope.save_point'))
        self.points_menu.append_section(None, self.points_menu_points)

        # zoom
        low, med, high = self.beamline.config.zoom.levels
        self.widget.microscope_zoomout_btn.connect('clicked', self.on_zoom, -1)
        self.widget.microscope_zoom100_btn.connect('clicked', self.on_reset_zoom, med)
        self.widget.microscope_zoomin_btn.connect('clicked', self.on_zoom, 1)

        # rotate sample
        self.widget.microscope_ccw90_btn.connect('clicked', self.on_rotate, -90)
        self.widget.microscope_cw90_btn.connect('clicked', self.on_rotate, 90)
        self.widget.microscope_rot180_btn.connect('clicked', self.on_rotate, 180)

        # centering
        self.widget.microscope_loop_btn.connect('clicked', self.on_auto_center, 'loop')
        self.widget.microscope_capillary_btn.connect('clicked', self.on_auto_center, 'capillary')
        self.widget.microscope_diff_btn.connect('clicked', self.on_auto_center, 'diffraction')
        self.widget.microscope_external_btn.connect('clicked', self.on_auto_center, 'external')

        self.beamline.manager.connect('mode', self.on_gonio_mode)
        self.beamline.goniometer.stage.connect('changed', self.update_overlay_coords)
        self.beamline.sample_zoom.connect('changed', self.update_overlay_coords)
        self.beamline.aperture.connect('changed', self.on_aperture)

        # Video Area
        self.video = VideoWidget(self.camera)
        self.beamline.camera_scale.connect('changed', self.on_camera_scale)
        self.widget.microscope_video_frame.add(self.video)
        self.widget.microscope_duplicate_btn.connect('clicked', self.on_duplicate)

        # status, save, etc
        self.widget.microscope_save_btn.connect('clicked', self.on_save)
        self.widget.microscope_grid_btn.connect('toggled', self.toggle_grid_mode)
        self.widget.microscope_colorize_tbtn.connect('toggled', self.colorize)
        self.widget.microscope_clear_btn.connect('clicked', self.on_clear_objects)
        self.widget.microscope_points_mnu.set_menu_model(self.points_menu)

        # disable centering buttons on click
        self.centering.connect('started', self.on_scripts_started)
        self.centering.connect('done', self.on_centering_done)
        if self.beamline.config.centering.show_bbox:
            self.beamline.sample_xcenter.connect('loop', self.on_centering_object)
            self.beamline.sample_xcenter.connect('crystal', self.on_centering_object)
            self.beamline.sample_xcenter.connect('pin', self.on_centering_object)

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
        self.video.connect('configure-event', self.setup_grid)
        self.scripts = get_scripts()

        # Connect Grid signals
        self.connect('notify::grid-xyz', self.update_overlay_coords)
        self.connect('notify::tool', self.on_tool_changed)

        # Connect Point Signals
        for signal in ('row-inserted', 'row-deleted', 'row-changed'):
            self.points.connect(signal, self.save_to_cache)
            self.points.connect(signal, self.update_points_menu)

    def change_tool(self, tool=None):
        if tool is None:
            self.props.tool, self.prev_tool = self.prev_tool, self.tool
        elif self.props.tool != tool:
            self.props.tool, self.prev_tool = tool, self.tool

    def setup_grid(self, *args, **kwargs):
        if not self.video_ready:
            self.video_ready = True
            for param in ['grid-xyz', 'grid-params']:
                self.connect('notify::{}'.format(param), self.save_to_cache)
        self.update_overlay_coords()

    def save_to_cache(self, *args, **kwargs):
        # config = {k: v for k, v in self.grid_params.items() if k != 'grid'}
        cache = {
            'points': [row[1] for row in self.points],
        }
        save_cache(cache, 'microscope')

    def load_from_cache(self):
        cache = load_cache('microscope')
        if cache and isinstance(cache, dict):
            for name, value in cache.items():
                if name.startswith('grid'):
                    continue
                if name == 'points':
                    for i, point in enumerate(value):
                        self.points.append([f'P{i + 1}', tuple(point)])
                else:
                    self.set_property(name, value)

    def update_points_menu(self, *args, **kwargs):
        self.points_menu_points.remove_all()
        for row in self.points:
            item = Gio.MenuItem.new(f"Go to {row[0]}")
            item.set_action_and_target_value("microscope.center_point", GLib.Variant.new_string(row[0]))
            self.points_menu_points.append_item(item)

    def save_image(self, filename):
        self.video.save_image(filename)

    def remove_objects(self):
        self.points.clear()
        self.props.grid = None
        self.props.grid_xyz = None
        self.props.grid_scores = None
        self.props.grid_index = None
        self.props.grid_frames = None

        self.props.grid_bbox = []
        if self.tool == self.ToolState.GRID:
            self.change_tool(self.ToolState.CENTERING)
        self.widget.microscope_grid_btn.set_active(False)

        self.video.clear_overlays()
        self.video.set_overlay_beam(self.beamline.aperture.get_position() * 1e-3)

    def toggle_grid_mode(self, *args, **kwargs):
        if self.widget.microscope_grid_btn.get_active():
            self.change_tool(self.ToolState.GRID)
            self.props.grid_bbox = []
        else:
            self.widget.microscope_grid_btn.set_active(False)
            self.change_tool()
            self.video.set_overlay_box()

    def add_point(self, point):
        self.points.append([f'P{len(self.points) + 1}', point])
        self.update_points()

    @async_call
    def update_points(self):
        if len(self.points):
            point_list = [row[1] for row in self.points]
            cur_point = numpy.array(self.beamline.goniometer.stage.get_xyz())
            points = numpy.array(point_list) - cur_point
            xyz = numpy.zeros_like(points)
            xyz[:, 0], xyz[:, 1], xyz[:, 2] = self.beamline.goniometer.stage.xyz_to_screen(
                points[:, 0], points[:, 1], points[:, 2]
            )
            GLib.idle_add(self.video.set_overlay_points, xyz)
        else:
            GLib.idle_add(self.video.set_overlay_points)

    def make_grid(self, bbox=None, points=None, scaled=True, center=True):
        if points is not None:
            points = numpy.array(points)
            bbox = numpy.array([points.min(axis=0), points.max(axis=0)])
        elif bbox is None:
            bbox = self.props.grid_bbox

        if not isinstance(bbox, numpy.ndarray):
            bbox = numpy.array(bbox)

        factor = 1.0 if scaled else self.video.scale
        step_size = 1e-3 * self.beamline.aperture.get() / self.video.get_mm_scale()

        bounds = bbox * factor
        shape = misc.calc_grid_size(bounds, step_size)
        w, h = 1000 * shape * self.video.get_mm_scale() * step_size
        if min(w, h) == 0.0:
            self.props.grid_bbox = []
            self.props.grid_params = {}
            self.video.set_overlay_grid()
            return

        grid, index, frames = misc.grid_from_bounds(bounds, step_size, **self.beamline.goniometer.grid_settings())
        dx, dy = self.video.pix_to_mm(*bounds.mean(axis=0))

        angle = self.beamline.goniometer.omega.get_position()
        ox, oy, oz = self.beamline.goniometer.stage.get_xyz()
        xmm, ymm = self.video.pix_to_mm(grid[:, 0], grid[:, 1])
        gx, gy, gz = self.beamline.goniometer.stage.xvw_to_xyz(-xmm, -ymm, numpy.radians(angle))
        grid_xyz = numpy.dstack([gx + ox, gy + oy, gz + oz])[0]

        if center:
            self.beamline.goniometer.stage.move_screen_by(-dx, -dy, 0.0)

        properties = {
            'grid_xyz': grid_xyz.round(4),
            'grid_bbox': [],
            'grid_index': index,
            'grid_frames': frames,
            'grid_scores': -numpy.ones(shape[::-1]),
            'grid_params': {
                'origin': (ox, oy, oz),
                'width': w,
                'height': h,
                'angle': angle,
                'shape': tuple(shape),
            },
        }
        self.load_grid(properties)

    def load_grid(self, properties):
        # Set properties
        for k, v in properties.items():
            self.set_property(k, v)

    @async_call
    def center_pixel(self, x, y, force=False):
        if self.tool == self.ToolState.CENTERING or force:
            xmm, ymm = self.video.pix_to_mm(x, y)
            if not self.beamline.goniometer.stage.is_busy():
                self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0)

    def recalculate_grid(self):
        center = numpy.array(self.video.get_size()) * 0.5
        points = self.grid_xyz - numpy.array(self.beamline.goniometer.stage.get_xyz())
        xyz = numpy.empty_like(points)
        xyz[:, 0], xyz[:, 1], xyz[:, 2] = self.beamline.goniometer.stage.xyz_to_screen(
            points[:, 0], points[:, 1], points[:, 2]
        )
        xyz /= self.video.get_mm_scale()
        xyz[:, :2] += center
        return xyz

    # callbacks
    def update_overlay_coords(self, *args, **kwargs):
        if time.time() - self.last_coord_update > MIN_COORD_UPDATE_PERIOD:
            self.last_coord_update = time.time()
            # Update grid
            if self.props.grid_xyz is not None:
                self.props.grid = self.recalculate_grid()
                self.video.set_overlay_grid(
                    {
                        'coords': self.props.grid,
                        'indices': self.props.grid_index,
                        'frames': self.props.grid_frames,
                        'scores': self.props.grid_scores
                    }
                )
            else:
                self.props.grid = None
                self.video.set_overlay_grid()
        self.update_points()

    def colorize(self, button):
        self.video.set_colorize(state=button.get_active())

    def on_clear_objects(self, *args, **kwargs):
        response = dialogs.warning(
            "Clear Grid & Points?",
            "All saved points and defined grids will be cleared.\nThis operation cannot be undone!",
            buttons=(('Cancel', Gtk.ButtonsType.CANCEL), ('Proceed', Gtk.ButtonsType.OK))
        )
        if response == Gtk.ButtonsType.OK:
            self.remove_objects()

    def on_centering_object(self, dev, obj):
        objects = dev.get_objects()
        annotations = {}
        for key, obj in objects.items():
            if obj and obj.time > time.time() - 2.0:
                hw = obj.w / 2.0
                hh = obj.h / 2.0
                if 'loop' in obj.label:
                    annotations[f'{obj.label} | {obj.score:0.0%}'] = {
                        'coords': numpy.array([[obj.x - hw, obj.y - hh], [obj.x + hw, obj.y + hh]]) * self.video.scale,
                        'expire': obj.time + 2.0
                    }
                else:
                    annotations[f'{obj.label} | {obj.score:0.0%}'] = {
                        'coords': numpy.array([[obj.x, obj.y], [obj.x, obj.y]]) * self.video.scale,
                        'expire': obj.time + 2.0
                    }
        self.video.set_annotations(annotations)

    def on_save_point(self, *args, **kwargs):
        self.add_point(self.beamline.goniometer.stage.get_xyz())
        self.save_to_cache()

    def on_duplicate(self, *args, **kwargs):
        if self.viewer is None:
            self.viewer = VideoView(self.beamline, title="MxDC Sample Viewer")
            self.viewer.connect('destroy', self.on_viewer_destroyed)
        self.viewer.present()

    def on_viewer_destroyed(self, widget):
        if self.viewer is not None and self.viewer == widget:
            self.viewer = None

    def on_center_point(self, action, param):
        name = param.get_string()
        for row in self.points:
            if row[0] == name:
                point = row[1]
                self.beamline.goniometer.stage.move_xyz(*point, wait=False)
                break

    def on_tool_changed(self, *args, **kwargs):
        window = self.widget.microscope_video_frame.get_window()
        if window:
            window.set_cursor(self.tool_cursors[self.props.tool])

    def on_camera_scale(self, obj, value):
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

    def on_centering_done(self, obj, event=None):
        self.widget.microscope_toolbar.set_sensitive(True)
        self.show_annotations = False
        self.video.set_annotations(None)

    def on_save(self, obj=None, arg=None):
        filters = {
            'png': dialogs.SmartFilter(name='PNG Image', extension='png'),
            'jpg': dialogs.SmartFilter(name='JPEG Image', extension='jpg')
        }
        img_filename, file_format = dialogs.file_chooser.select_to_save(
            title='Save Video Snapshot', filters=list(filters.values())
        )
        if not img_filename:
            return
        if os.access(Path(img_filename).parent, os.W_OK):
            self.save_image(img_filename)

    def on_auto_center(self, widget, method='loop'):
        if method == 'external':
            self.show_annotations = True
        samples = Registry.get_utility(ISampleStore)
        sample = samples.get_current()
        directory = datatools.get_activity_folder(
            sample, activity='centering', session=self.beamline.session_key
        )
        self.centering.configure(method=method, directory=directory, name=sample.get('name', 'unknown'))
        self.centering.start()
        return True

    def on_reset_zoom(self, widget, position):
        self.camera.zoom(position)

    def on_zoom(self, widget, change):
        low, med, high = self.beamline.config.zoom.levels
        position = min(max(low, self.beamline.sample_zoom.get_position() + change), high)
        self.camera.zoom(position)

    def on_aperture(self, obj, value):
        aperture = value * 1e-3  # convert to mm
        self.video.set_overlay_beam(aperture)

        if self.grid_xyz is not None:
            xyz = self.recalculate_grid()
            self.make_grid(points=xyz[:, :2], center=False)

    def on_rotate(self, widget, angle):
        cur_omega = round(self.beamline.goniometer.omega.get_position())
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

        xmm, ymm = self.video.pix_to_mm(x, y)
        ix, iy = self.video.pix_to_image(x, y)

        self.widget.microscope_pos_lbl.set_markup(
            f"<small><tt>X:{ix:5.0f} {xmm:6.3f} mm\nY:{iy:5.0f} {ymm:6.3f} mm</tt></small>"
        )

        if Gdk.ModifierType.BUTTON2_MASK & event.state:
            self.ruler_box[-1] = (x, y)
            self.video.set_overlay_ruler(self.ruler_box)
        elif Gdk.ModifierType.CONTROL_MASK & event.state and self.mode.name in ['COLLECT']:
            self.change_tool(tool=self.ToolState.CENTERING)
        elif self.tool == self.ToolState.GRID and len(self.props.grid_bbox):
            if Gdk.ModifierType.BUTTON1_MASK & event.state:
                self.props.grid_bbox[-1] = (x, y)
            self.video.set_overlay_box(self.grid_bbox)
        elif self.tool == self.ToolState.MEASUREMENT:
            self.change_tool()
        elif self.tool == self.ToolState.CENTERING and self.mode.name in ['COLLECT']:
            self.change_tool()

    def on_mouse_press(self, widget, event):
        if event.button == 1:
            if self.tool == self.ToolState.GRID:
                self.props.grid_bbox = [(event.x, event.y), (event.x, event.y)]
                self.video.set_overlay_box(self.grid_bbox)
            else:
                self.center_pixel(event.x, event.y)
        elif event.button == 2:
            self.change_tool(self.ToolState.MEASUREMENT)
            self.ruler_box[0] = (event.x, event.y)
            self.ruler_box[1] = (event.x, event.y)
            self.video.set_overlay_ruler(self.ruler_box)

    def on_mouse_release(self, widget, event):
        if event.button == 1:
            if self.tool == self.ToolState.GRID and self.grid_bbox:
                self.make_grid()
                self.widget.microscope_grid_btn.set_active(False)
        elif event.button == 2:
            self.video.set_overlay_ruler()
