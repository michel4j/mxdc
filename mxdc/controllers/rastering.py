
import time
import os
import uuid
from enum import Enum

from gi.repository import Gtk

from mxdc import Registry, IBeamline, Object, Property
from mxdc.engines.rastering import RasterCollector
from mxdc.utils import datatools, misc
from mxdc.utils.converter import resol_to_dist
from mxdc.utils.gui import TreeManager, ColumnType, ColumnSpec, FormManager, FieldSpec, Validator
from mxdc.utils.log import get_module_logger
from mxdc.widgets.imageviewer import IImageViewer
from .microscope import IMicroscope
from .samplestore import ISampleStore

RASTER_DELTA = .1

logger = get_module_logger(__name__)


class RasterResultsManager(TreeManager):
    class Data(Enum):
        NAME, ANGLE, X_POS, Y_POS, Z_POS, SCORE, CELL, COLOR, UUID, FILENAME = range(10)

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
    def __init__(self, *args, beamline=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.beamline = beamline

    def on_change(self, field, event, name):
        super().on_change(field, event, name)

        if name in ['aperture', 'width', 'height']:
            aperture = self.get_value('aperture')
            hsteps, vsteps = misc.calc_grid_shape(
                self.get_value('width'),
                self.get_value('height'),
                aperture,
            )
            self.set_values({'hsteps': hsteps, 'vsteps': vsteps, 'height': vsteps*aperture, 'width': hsteps*aperture})

        if name in ['aperture', 'exposure']:
            exposure = self.get_value('exposure')
            det_exp_limit = 1/self.beamline.config.get('max_raster_freq', 100)
            mtr_exp_limit = self.get_value('aperture')*1e-3/self.beamline.config.get('max_raster_speed', 0.5)

            self.set_value('exposure', max(exposure, det_exp_limit, mtr_exp_limit))


class RasterController(Object):
    class StateType:
        READY, ACTIVE, WAITING = range(3)

    Fields = (
        FieldSpec('exposure', 'entry', '{:0.3g}', Validator.Float(0.001, 720, 0.25)),
        FieldSpec('resolution', 'entry', '{:0.2g}', Validator.Float(0.5, 50, 2.0)),
        FieldSpec('width', 'entry', '{:0.0f}', Validator.Float(5., 1000., 200.)),
        FieldSpec('height', 'entry', '{:0.0f}', Validator.Float(5., 1000., 200.)),
        FieldSpec('hsteps', 'entry', '{:d}', Validator.Int(1, 100, 10)),
        FieldSpec('vsteps', 'entry', '{:d}', Validator.Int(1, 100, 10)),
        FieldSpec('angle', 'entry', '{:0.3g}', Validator.Float(-1e6, 1e6, 0.0)),
        FieldSpec('aperture', 'entry', '{:0.0f}', Validator.Float(-1e6, 1e6, 50.)),
    )

    state = Property(type=int, default=StateType.READY)

    def __init__(self, view, widget):
        super().__init__()
        self.view = view
        self.widget = widget

        self.beamline = Registry.get_utility(IBeamline)
        self.microscope = Registry.get_utility(IMicroscope)
        self.sample_store = Registry.get_utility(ISampleStore)
        self.collector = RasterCollector()
        self.manager = RasterResultsManager(self.view, colormap=self.microscope.props.grid_cmap)

        # housekeeping
        self.start_time = 0
        self.pause_dialog = None
        self.expanded = False
        self.results = {}
        self.form = RasterForm(
            widget, beamline=self.beamline,
            fields=self.Fields, prefix='raster', persist=True, disabled=('hsteps', 'vsteps')
        )

        # signals
        self.microscope.connect('notify::grid-params', self.on_grid_changed)
        self.connect('notify::state', self.on_state_changed)
        self.beamline.aperture.connect('changed', self.on_aperture)
        self.beamline.goniometer.omega.connect('changed', self.on_angle)
        self.collector.connect('done', self.on_done)
        self.collector.connect('complete', self.on_complete)
        self.collector.connect('stopped', self.on_stopped)
        self.collector.connect('progress', self.on_progress)
        self.collector.connect('started', self.on_started)
        self.collector.connect('result', self.on_results)
        self.setup()

    def setup(self):
        self.view.props.activate_on_single_click = False
        self.widget.raster_start_btn.connect('clicked', self.start_raster)
        self.view.connect('row-activated', self.on_result_activated)

    def start_raster(self, *args, **kwargs):
        if self.props.state == self.StateType.ACTIVE:
            self.widget.raster_progress_lbl.set_text("Stopping raster ...")
            self.collector.stop()
        elif self.props.state == self.StateType.READY:
            params = {}
            params.update(self.microscope.grid_params)
            params.update(self.form.get_values())
            params.update({
                'distance': resol_to_dist(params['resolution'], self.beamline.detector.mm_size, self.beamline.energy.get_position()),
                'origin': self.beamline.goniometer.stage.get_xyz(),
                'uuid': str(uuid.uuid4()),
                'activity': 'raster',
                'energy': self.beamline.energy.get_position(),
                'delta': RASTER_DELTA,
                'attenuation': self.beamline.attenuator.get_position(),
            })
            params = datatools.update_for_sample(params, self.sample_store.get_current())
            if not self.collector.is_busy():
                self.widget.raster_progress_lbl.set_text("Starting raster ...")
                self.collector.configure(params)
                self.collector.start()
            else:
                logger.warning('A raster scan is still active')

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
                "media-playback-stop-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.widget.raster_start_btn.set_sensitive(True)
            self.widget.raster_config_box.set_sensitive(False)
            self.view.set_sensitive(False)
        elif self.props.state == self.StateType.WAITING:
            self.widget.raster_progress_lbl.set_text("Waiting for results...")
            self.widget.raster_start_icon.set_from_icon_name(
                "appointment-soon-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.widget.raster_start_btn.set_sensitive(True)
            self.widget.raster_config_box.set_sensitive(True)
            self.view.set_sensitive(True)
        else:
            self.widget.raster_start_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.widget.raster_config_box.set_sensitive(True)
            self.widget.raster_start_btn.set_sensitive(True)
            self.view.set_sensitive(True)

    def on_started(self, collector, config):
        self.start_time = time.time()
        self.props.state = self.StateType.ACTIVE
        logger.info("Rastering Started.")
        grid_config = collector.get_grid()
        self.microscope.load_grid(grid_config)
        self.results[config['uuid']] = grid_config
        directory = config['directory']
        home_dir = misc.get_project_home()
        current_dir = directory.replace(home_dir, '~')
        self.widget.dsets_dir_fbk.set_text(current_dir)

        # collapse existing data
        self.view.collapse_all()
        self.expanded = False

    def on_complete(self, collector, data):
        self.props.state = self.StateType.READY
        self.widget.raster_progress_lbl.set_text("Rastering analysis complete.")
        params = collector.get_parameters()
        logger.info('Saving overlay ...')
        self.microscope.save_image(os.path.join(params['directory'], '{}.png'.format(params['name'])))

    def on_done(self, collector, data):
        self.props.state = self.StateType.READY   # previously WAITING
        self.widget.raster_eta.set_text('--:--')
        self.widget.raster_pbar.set_fraction(1.0)

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

    def on_results(self, collector, index, results):
        grid_config = collector.get_grid()
        params = collector.get_parameters()
        pos = grid_config['grid_index'][index]
        score = grid_config['grid_scores'][pos]
        frame = grid_config['grid_frames'][index]

        x, y, z = self.microscope.props.grid_xyz[index]
        parent, child = self.manager.add_item({
            'name': params['name'],
            'angle': params['angle'],
            'cell': frame,
            'x_pos': x,
            'y_pos': y,
            'z_pos': z,
            'score': score,
            'color': score,
            'filename': results['filename'],
            'info':  None if index > 0 else grid_config,
            'uuid': params['uuid'],
        })

        if parent and not self.expanded:
            self.view.expand_row(parent, False)
            self.expanded = True

        self.microscope.update_overlay_coords()

    def on_result_activated(self, view, path, column=None):
        itr = self.manager.model.get_iter(path)
        item = self.manager.get_item(itr)

        if self.manager.model.iter_has_child(itr):
            self.beamline.goniometer.omega.move_to(item['angle'], wait=True)
            config = self.results[item['uuid']]
            self.microscope.load_grid(config)
            self.widget.dsets_dir_fbk.set_text(config['info']['directory'])
        else:
            image_viewer = Registry.get_utility(IImageViewer)
            self.beamline.goniometer.stage.move_xyz(item['x_pos'], item['y_pos'], item['z_pos'])
            image_viewer.open_frame(item['filename'])

    def on_grid_changed(self, obj, param):
        params = self.microscope.grid_params
        if params is not None and 'width' in params and 'height' in params:
            self.form.set_values({'width': params['width'], 'height': params['height']}, propagate=True)
