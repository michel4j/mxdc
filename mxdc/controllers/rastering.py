import copy
import time
import uuid
from datetime import datetime
from enum import Enum

from gi.repository import Gtk

from mxdc import Registry, IBeamline, Object, Property
from mxdc.engines.rastering import RasterCollector
from mxdc.utils import datatools, misc
from mxdc.utils.converter import resol_to_dist
from mxdc.utils.gui import TreeManager, ColumnType, ColumnSpec, FormManager, FieldSpec, Validator
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs
from mxdc.widgets.imageviewer import IImageViewer
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


class RasterForm(FormManager):
    def on_change(self, field, event, name):
        super().on_change(field, event, name)

        if name in ['aperture', 'width', 'height']:
            frames, lines = misc.calc_grid_size(
                self.get_value('width'),
                self.get_value('height'),
                self.get_value('aperture'),
                tight=False
            )
            self.set_values({'lines': lines, 'frames':frames})


class RasterController(Object):
    class StateType:
        READY, ACTIVE, PAUSED = list(range(3))

    Fields = (
        FieldSpec('exposure', 'entry', '{:0.3g}', Validator.Float(0.001, 720, 0.5)),
        FieldSpec('resolution', 'entry','{:0.2g}', Validator.Float(0.5, 50, 2.0)),
        FieldSpec('width', 'entry', '{:0.0f}', Validator.Float(5., 500., 200.)),
        FieldSpec('height', 'entry', '{:0.0f}', Validator.Float(5., 500., 200.)),
        FieldSpec('frames', 'entry', '{:d}', Validator.Int(1, 100, 10)),
        FieldSpec('lines', 'entry', '{:d}', Validator.Int(1, 100, 10)),
        FieldSpec('angle', 'entry', '{:0.3g}', Validator.Float(-1e6, 1e6, 0.0)),
        FieldSpec('aperture', 'entry', '{:0.0f}', Validator.Float(-1e6, 1e6, 50.)),
    )

    state = Property(type=int, default=StateType.READY)

    def __init__(self, view, widget):
        super().__init__()
        self.view = view
        self.widget = widget

        # housekeeping
        self.start_time = 0
        self.pause_dialog = None
        self.results = {}

        self.form = RasterForm(
            widget, fields=self.Fields, prefix='raster', persist=True, disabled=('lines', 'frames')
        )

        self.beamline = Registry.get_utility(IBeamline)
        self.microscope = Registry.get_utility(IMicroscope)
        self.sample_store = Registry.get_utility(ISampleStore)
        self.collector = RasterCollector()
        self.manager = RasterResultsManager(self.view, colormap=self.microscope.props.grid_cmap)

        # signals
        self.microscope.connect('notify::grid-params', self.on_grid_changed)
        self.connect('notify::state', self.on_state_changed)
        self.beamline.aperture.connect('changed', self.on_aperture)
        self.beamline.goniometer.omega.connect('changed', self.on_angle)
        self.collector.connect('done', self.on_done)
        self.collector.connect('paused', self.on_pause)
        self.collector.connect('stopped', self.on_stopped)
        self.collector.connect('progress', self.on_progress)
        self.collector.connect('started', self.on_started)
        self.collector.connect('result', self.on_results)
        self.setup()

    def setup(self):
        self.view.props.activate_on_single_click = False
        self.widget.raster_start_btn.connect('clicked', self.start_raster)
        self.widget.raster_stop_btn.connect('clicked', self.stop_raster)
        self.view.connect('row-activated', self.on_result_activated)

    def start_raster(self, *args, **kwargs):
        if self.props.state == self.StateType.ACTIVE:
            self.widget.raster_progress_lbl.set_text("Pausing raster ...")
            self.collector.pause()
        elif self.props.state == self.StateType.PAUSED:
            self.widget.raster_progress_lbl.set_text("Resuming raster ...")
            self.collector.resume()
        elif self.props.state == self.StateType.READY:
            self.widget.raster_progress_lbl.set_text("Starting raster ...")
            params = {
                'name': datetime.now().strftime('%y%m%d-%H%M'),
                'uuid': str(uuid.uuid4()),
                'activity': 'raster',
                'energy': self.beamline.energy.get_position(),
                'delta': RASTER_DELTA,
                'attenuation': self.beamline.attenuator.get(),
            }
            params.update(self.microscope.grid_params)
            params.update(self.form.get_values())
            params.update({
                'distance': resol_to_dist(params['resolution'], self.beamline.detector.mm_size, params['energy']),
                'origin': self.beamline.goniometer.stage.get_xyz(),
            })

            params = datatools.update_for_sample(params, self.sample_store.get_current())
            self.collector.configure(params)
            self.collector.start()

    def stop_raster(self, *args, **kwargs):
        self.widget.raster_progress_lbl.set_text("Stopping raster ...")
        self.collector.stop()

    def on_aperture(self, aperture, value):
        self.form.set_value('aperture', value, propagate=True)

    def on_angle(self, omega, value):
        self.form.set_value('angle', value)

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

    def on_started(self, collector, config):
        self.start_time = time.time()
        self.props.state = self.StateType.ACTIVE
        logger.info("Rastering Started.")

        self.microscope.props.grid_xyz = config['grid']
        self.results[config['uuid']] = {
            'config': copy.deepcopy(config),
            'scores': {}
        }

        directory = config['directory']
        home_dir = misc.get_project_home()
        current_dir = directory.replace(home_dir, '~')
        self.widget.dsets_dir_fbk.set_text(current_dir)

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

    def on_results(self, collector, frame, results):
        index = frame - 1   # frames are 1-based counting
        config = collector.config['params']
        try:
            score = misc.frame_score(results)
        except (KeyError, ValueError, AttributeError):
            score = 0.0
        self.microscope.add_grid_score(frame, score)
        x, y, z = self.microscope.props.grid_xyz[index]  # frames
        parent, child = self.manager.add_item({
            'name': config['name'],
            'angle': config['angle'],
            'cell': frame,
            'x_pos': x,
            'y_pos': y,
            'z_pos': z,
            'score': score,
            'color': score,
            'filename': results['filename'],
            'uuid': config['uuid'],
        })
        self.results[config['uuid']]['scores'][frame] = score
        if parent:
            self.view.expand_row(parent, False)
        self.view.scroll_to_cell(child, None, True, 0.5, 0.5)
        self.microscope.update_grid()

    def on_result_activated(self, view, path, column=None):
        itr = self.manager.model.get_iter(path)
        item = self.manager.get_item(itr)

        if self.manager.model.iter_has_child(itr):
            self.beamline.goniometer.omega.move_to(item['angle'], wait=True)
            grid = self.results[item['uuid']]
            self.microscope.load_grid(
                grid['grid'],
                {'origin': grid['config']['origin'], 'angle': grid['config']['angle']},
                grid['scores']
            )
            self.widget.dsets_dir_fbk.set_text(grid['config']['directory'])
        else:
            image_viewer = Registry.get_utility(IImageViewer)
            self.beamline.goniometer.stage.move_xyz(item['x_pos'], item['y_pos'], item['z_pos'])
            image_viewer.open_frame(item['filename'])

    def on_grid_changed(self, obj, param):
        params = self.microscope.grid_params
        if params is not None and 'width' in params and 'height' in params:
            self.form.set_values({'width': params['width'], 'height': params['height']}, propagate=True)




