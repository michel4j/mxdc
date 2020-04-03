import copy
import os
import time
import uuid
from datetime import datetime

from enum import Enum
from gi.repository import Gtk, GObject
from mxdc import Registry, IBeamline, Object

from mxdc.conf import load_cache, save_cache
from mxdc.engines.rastering import RasterCollector
from mxdc.utils import datatools, misc
from mxdc.utils.converter import resol_to_dist
from mxdc.utils.gui import TreeManager, ColumnType, ColumnSpec
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs
from mxdc.widgets.imageviewer import IImageViewer
from . import common
from .microscope import IMicroscope
from .samplestore import ISampleStore

RASTER_DELTA = 0.5

logger = get_module_logger(__name__)


class RasterResultsManager(TreeManager):
    class Data(Enum):
        NAME, ANGLE, X_POS, Y_POS, Z_POS, SCORE, CELL, COLOR, UUID, FILENAME = list(range(10))

    Types = [str, float, float, float, float, float, int, float, str, str]
    Columns = ColumnSpec(
        (Data.CELL, 'Label', ColumnType.TEXT, '{}', True),
        (Data.ANGLE, 'Angle', ColumnType.NUMBER, '{:0.1f}°', True),
        (Data.X_POS, 'X (mm)', ColumnType.NUMBER, '{:0.4f}', True),
        (Data.Y_POS, 'Y (mm)', ColumnType.NUMBER, '{:0.4f}', True),
        (Data.Z_POS, 'Z (mm)', ColumnType.NUMBER, '{:0.4f}', True),
        (Data.SCORE, 'Score', ColumnType.NUMBER, '{:0.1f}', True),
        (Data.COLOR, '', ColumnType.COLORSCALE, '{}', False),
    )
    parent = Data.NAME


class RasterController(Object):
    class StateType:
        READY, ACTIVE, PAUSED = list(range(3))

    ConfigSpec = {
        'exposure': ['entry', '{:0.3g}', float, 1.0],
        'resolution': ['entry', '{:0.3g}', float, 50.0],
    }

    state = GObject.Property(type=int, default=StateType.READY)
    config = GObject.Property(type=object)

    def __init__(self, view, widget):
        super().__init__()
        self.view = view
        self.widget = widget

        # housekeeping
        self.start_time = 0
        self.pause_dialog = None
        self.results = {}

        self.beamline = Registry.get_utility(IBeamline)
        self.microscope = Registry.get_utility(IMicroscope)
        self.sample_store = Registry.get_utility(ISampleStore)
        self.collector = RasterCollector()

        self.manager = RasterResultsManager(self.view, colormap=self.microscope.props.grid_cmap)

        # signals
        self.microscope.connect('notify::grid-xyz', self.on_grid_changed)
        self.connect('notify::state', self.on_state_changed)
        self.collector.connect('done', self.on_done)
        self.collector.connect('new-image', self.on_new_image)
        self.collector.connect('paused', self.on_pause)
        self.collector.connect('stopped', self.on_stopped)
        self.collector.connect('progress', self.on_progress)
        self.collector.connect('started', self.on_started)
        self.collector.connect('result', self.on_results)

        self.sample_store.connect('updated', self.on_sample_updated)
        self.setup()

    def setup(self):
        self.view.props.activate_on_single_click = False
        self.widget.raster_start_btn.connect('clicked', self.start_raster)
        self.widget.raster_stop_btn.connect('clicked', self.stop_raster)
        self.widget.raster_dir_btn.connect('clicked', self.open_terminal)
        self.view.connect('row-activated', self.on_result_activated)

        labels = {
            'energy': (self.beamline.energy, self.widget.raster_energy_fbk, {'format': '{:0.3f} keV'}),
            'attenuation': (self.beamline.attenuator, self.widget.raster_attenuation_fbk, {'format': '{:0.0f} %'}),
            'aperture': (self.beamline.aperture, self.widget.raster_aperture_fbk, {'format': '{:0.0f} \xc2\xb5m'}),
            'omega': (self.beamline.omega, self.widget.raster_angle_fbk, {'format': '{:0.2f}°'}),
            'maxres': (self.beamline.maxres, self.widget.raster_maxres_fbk, {'format': '{:0.2f} \xc3\x85'}),
        }
        self.monitors = {
            name: common.DeviceMonitor(dev, lbl, **kw)
            for name, (dev, lbl, kw) in list(labels.items())
        }
        self.load_from_cache()

    def load_from_cache(self):
        cache = load_cache('raster')
        if cache and isinstance(cache, dict):
            self.configure(cache)

    def get_parameters(self):
        info = {}
        for name, details in list(self.ConfigSpec.items()):
            field_type, fmt, conv, default = details
            field_name = 'raster_{}_{}'.format(name, field_type)
            field = getattr(self.widget, field_name)
            raw_value = default
            if field_type == 'entry':
                raw_value = field.get_text()
            elif field_type == 'switch':
                raw_value = field.get_active()
            elif field_type == 'cbox':
                raw_value = field.get_active_id()
            try:
                value = conv(raw_value)
            except (TypeError, ValueError):
                value = default
            info[name] = value
        return info

    def configure(self, info):
        if not self.ConfigSpec: return
        for name, details in list(self.ConfigSpec.items()):
            field_type, fmt, conv, default = details
            field_name = 'raster_{}_{}'.format(name, field_type)
            value = info.get(name, default)
            field = getattr(self.widget, field_name, None)
            if not field: continue
            if field_type == 'entry':
                field.set_text(fmt.format(value))
            elif field_type == 'check':
                field.set_active(value)
            elif field_type == 'spin':
                field.set_value(value)
            elif field_type == 'cbox':
                field.set_active_id(str(value))
            try:
                conv(value)
                field.get_style_context().remove_class('error')
            except (TypeError, ValueError):
                field.get_style_context().add_class('error')

    def start_raster(self, *args, **kwargs):
        if self.props.state == self.StateType.ACTIVE:
            self.widget.raster_progress_lbl.set_text("Pausing raster ...")
            self.collector.pause()
        elif self.props.state == self.StateType.PAUSED:
            self.widget.raster_progress_lbl.set_text("Resuming raster ...")
            self.collector.resume()
        elif self.props.state == self.StateType.READY:
            self.widget.raster_progress_lbl.set_text("Starting raster ...")
            grid = self.microscope.grid_xyz
            params = self.get_parameters()

            save_cache(params, 'raster')

            params['angle'] = self.microscope.grid_params['angle']
            params['origin'] = self.microscope.grid_params['origin']
            params['scale'] = self.microscope.grid_params['scale']
            params['energy'] = self.beamline.energy.get_position()
            params['distance'] = resol_to_dist(params['resolution'], self.beamline.detector.mm_size, params['energy'])
            params['attenuation'] = self.beamline.attenuator.get()
            params['delta'] = RASTER_DELTA
            params['uuid'] = str(uuid.uuid4())
            params['name'] = datetime.now().strftime('%y%m%d-%H%M')
            params['activity'] = 'raster'
            params = datatools.update_for_sample(params, self.sample_store.get_current())

            self.props.config = params
            self.collector.configure(grid, self.props.config)
            self.collector.start()

    def stop_raster(self, *args, **kwargs):
        self.widget.raster_progress_lbl.set_text("Stopping raster ...")
        self.collector.stop()

    def open_terminal(self, button):
        directory = self.widget.raster_dir_fbk.get_text()
        misc.open_terminal(directory)

    def on_sample_updated(self, obj):
        sample = self.sample_store.get_current()
        sample_text = '{name}|{port}'.format(
            name=sample.get('name', '...'),
            port=sample.get('port', '...')
        ).replace('|...', '')
        self.widget.raster_sample_fbk.set_text(sample_text)

    def on_state_changed(self, obj, param):
        if self.props.state == self.StateType.ACTIVE:
            self.widget.raster_start_icon.set_from_icon_name(
                "media-playback-pause-symbolic", Gtk.IconSize.LARGE_TOOLBAR
            )
            self.widget.raster_stop_btn.set_sensitive(True)
            self.widget.raster_start_btn.set_sensitive(True)
            self.widget.raster_config_box.set_sensitive(False)
            self.view.set_sensitive(False)
        elif self.props.state == self.StateType.PAUSED:
            self.widget.raster_progress_lbl.set_text("Rastering paused!")
            self.widget.raster_start_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR
            )
            self.widget.raster_stop_btn.set_sensitive(True)
            self.widget.raster_start_btn.set_sensitive(True)
            self.widget.raster_config_box.set_sensitive(False)
            self.view.set_sensitive(True)
        else:
            self.widget.raster_start_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR
            )
            self.widget.raster_config_box.set_sensitive(True)
            self.widget.raster_start_btn.set_sensitive(True)
            self.widget.raster_stop_btn.set_sensitive(False)
            self.view.set_sensitive(True)

    def on_started(self, collector, data):
        self.start_time = time.time()
        self.props.state = self.StateType.ACTIVE
        logger.info("Rastering Started.")
        config = collector.config['params']
        self.results[config['uuid']] = {
            'config': copy.deepcopy(config),
            'grid': self.microscope.grid_xyz,
            'scores': {}
        }

        directory = config['directory']
        home_dir = misc.get_project_home()
        current_dir = directory.replace(home_dir, '~')
        self.widget.raster_dir_fbk.set_text(current_dir)

    def on_done(self, obj, data):
        self.props.state = self.StateType.READY
        self.widget.raster_progress_lbl.set_text("Rastering Completed.")
        self.widget.raster_eta.set_text('--:--')
        self.widget.raster_pbar.set_fraction(1.0)

    def on_pause(self, obj, paused, reason):
        if paused:
            self.props.state = self.StateType.PAUSED
            if reason:
                # Build the dialog message
                self.pause_dialog = dialogs.make_dialog(
                    Gtk.MessageType.WARNING, 'Rastering Paused', reason,
                    buttons=(('OK', Gtk.ResponseType.OK),)
                )
                self.pause_dialog.run()
                self.pause_dialog.destroy()
                self.pause_dialog = None
        else:
            self.props.state = self.StateType.ACTIVE
            if self.pause_dialog:
                self.pause_dialog.destroy()
                self.pause_dialog = None

    def on_error(self, obj, reason):
        error_dialog = dialogs.make_dialog(
            Gtk.MessageType.WARNING, 'Rastering Error!', reason,
            buttons=(('OK', Gtk.ResponseType.OK),)
        )
        error_dialog.run()
        error_dialog.destroy()

    def on_stopped(self, obj, data):
        self.props.state = self.StateType.READY
        self.widget.raster_progress_lbl.set_text("Rastering Stopped.")
        self.widget.raster_eta.set_text('--:--')

    def on_progress(self, obj, fraction, message):
        used_time = time.time() - self.start_time
        remaining_time = (1 - fraction) * used_time / fraction
        eta_time = remaining_time
        self.widget.raster_eta.set_text('{:0>2.0f}:{:0>2.0f} ETA'.format(*divmod(eta_time, 60)))
        self.widget.raster_pbar.set_fraction(fraction)
        self.widget.raster_progress_lbl.set_text(message)

    def on_new_image(self, obj, file_path):
        image_viewer = Registry.get_utility(IImageViewer)
        frame = os.path.splitext(os.path.basename(file_path))[0]
        image_viewer.open_frame(file_path)
        logger.info('Frame acquired: {}'.format(frame))

    def on_results(self, collector, cell, results):
        config = collector.config['params']
        score = misc.frame_score(results)
        self.microscope.add_grid_score(cell, score)
        x, y, z = self.microscope.props.grid_xyz[cell]
        parent, child = self.manager.add_item({
            'name': config['name'],
            'angle': config['angle'],
            'cell': cell,
            'x_pos': x,
            'y_pos': y,
            'z_pos': z,
            'score': score,
            'color': score,
            'filename': results['filename'],
            'uuid': config['uuid'],
        })
        self.results[config['uuid']]['scores'][cell] = score
        if parent:
            self.view.expand_row(parent, False)
        self.view.scroll_to_cell(child, None, True, 0.5, 0.5)

    def on_result_activated(self, view, path, column=None):
        itr = self.manager.model.get_iter(path)
        item = self.manager.get_item(itr)

        if self.manager.model.iter_has_child(itr):
            self.beamline.omega.move_to(item['angle'], wait=True)
            grid = self.results[item['uuid']]
            self.microscope.load_grid(
                grid['grid'],
                {'origin': grid['config']['origin'], 'angle': grid['config']['angle']},
                grid['scores']
            )
            self.widget.raster_dir_fbk.set_text(grid['config']['directory'])
        else:
            image_viewer = Registry.get_utility(IImageViewer)
            self.beamline.sample_stage.move_xyz(item['x_pos'], item['y_pos'], item['z_pos'])
            image_viewer.open_image(item['filename'])

    def on_grid_changed(self, obj, param):
        grid = self.microscope.props.grid_xyz
        state = self.microscope.props.grid_state
        raster_page = self.widget.samples_stack.get_child_by_name('rastering')
        if grid is not None and state == self.microscope.GridState.PENDING:
            self.widget.raster_grid_info.set_text('Defined grid has {} points'.format(len(grid)))
            self.widget.raster_command_box.set_sensitive(True)
            self.widget.samples_stack.set_visible_child_name('rastering')
            # self.widget.samples_stack.child_set(raster_page, needs_attention=True)
        else:
            msg = 'Please define a new grid using the sample viewer!'
            self.widget.raster_grid_info.set_text(msg)
            self.widget.raster_command_box.set_sensitive(False)
            self.widget.samples_stack.child_set(raster_page, needs_attention=False)
