
import time
import os
import uuid
from enum import Enum

from mxdc import Registry, IBeamline, Object, Property, Signal
from mxdc.engines.rastering import RasterCollector
from mxdc.utils import datatools, misc, decorators
from mxdc.utils.converter import resol_to_dist
from mxdc.utils.gui import TreeManager, ColumnType, ColumnSpec, FormManager, FieldSpec, Validator
from mxdc.utils.log import get_module_logger
from mxdc.widgets.imageviewer import IImageViewer
from mxdc.widgets.misc import ActiveMenu
from mxdc.widgets import status, dialogs
from .microscope import IMicroscope
from .samplestore import ISampleStore

RASTER_DELTA = .25

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
        (Data.SCORE, 'Score', ColumnType.NUMBER, '{:0.2f}', True),
        (Data.COLOR, '', ColumnType.COLORSCALE, '{}', False),
    )
    parent = Data.NAME


class RasterForm(FormManager):
    def __init__(self, *args, beamline=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.beamline = beamline

    def on_change(self, field, event, name):
        super().on_change(field, event, name)
        aperture = self.beamline.aperture.get_position()
        if name in ['aperture', 'width', 'height']:
            hsteps, vsteps = misc.calc_grid_shape(
                self.get_value('width'),
                self.get_value('height'),
                aperture,
            )
            self.set_values({'hsteps': hsteps, 'vsteps': vsteps, 'height': vsteps*aperture, 'width': hsteps*aperture})

        if name in ['aperture', 'exposure']:
            exposure = self.get_value('exposure')
            det_exp_limit = 1/self.beamline.config.raster.max_freq
            mtr_exp_limit = aperture*1e-3/self.beamline.config.raster.max_speed

            self.set_value('exposure', max(exposure, det_exp_limit, mtr_exp_limit))


class RasterController(Object):
    class StateType:
        READY, ACTIVE, WAITING = range(3)

    Fields = (
        FieldSpec('exposure', 'entry', '{:0.3g}', Validator.Float(0.001, 720, 0.005)),
        FieldSpec('resolution', 'entry', '{:0.2g}', Validator.Float(0.5, 50, 2.0)),
        FieldSpec('width', 'entry', '{:0.0f}', Validator.Float(5., 1000., 200.)),
        FieldSpec('height', 'entry', '{:0.0f}', Validator.Float(5., 1000., 200.)),
        FieldSpec('hsteps', 'entry', '{:d}', Validator.Int(1, 100, 10)),
        FieldSpec('vsteps', 'entry', '{:d}', Validator.Int(1, 100, 10)),
        FieldSpec('low_dose', 'check', '{}', Validator.Bool(True)),
    )

    state = Property(type=int, default=StateType.READY)

    class Signals:
        directory = Signal('directory', arg_types=(str,))

    def __init__(self, widget):
        super().__init__()
        self.view = widget.raster_list
        self.widget = widget

        self.beamline = Registry.get_utility(IBeamline)
        self.microscope = Registry.get_utility(IMicroscope)
        self.sample_store = Registry.get_utility(ISampleStore)
        self.collector = RasterCollector()
        self.manager = RasterResultsManager(self.view, colormap=self.microscope.props.grid_cmap)

        self.control = status.DataControl()
        self.widget.rastering_box.pack_end(self.control, False, True, 0)
        self.beam_size = ActiveMenu(self.beamline.aperture, 'Aperture', fmt="%0.0f")
        self.widget.raster_config_box.attach(self.beam_size, 4, 0, 1, 1)

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
        self.collector.connect('done', self.on_done)
        self.collector.connect('complete', self.on_complete)
        self.collector.connect('stopped', self.on_stopped)
        self.collector.connect('progress', self.on_progress)
        self.collector.connect('started', self.on_started)
        self.collector.connect('result', self.on_results)
        self.setup()

    def setup(self):
        self.view.props.activate_on_single_click = False
        self.control.action_btn.connect('clicked', self.on_start_raster)
        self.control.stop_btn.connect('clicked', self.on_stop_raster)
        self.view.connect('row-activated', self.on_result_activated)
        self.widget.raster_open_btn.connect('clicked', self.on_open)
        self.widget.raster_clean_btn.connect('clicked', self.on_clean)

    def on_open(self, btn):
        filters = [
            dialogs.SmartFilter(name='MxDC Grid-File', patterns=["*.grid"]),
        ]

        filename = dialogs.file_chooser.select_to_open('Select Grid File', filters=filters)
        if not filename:
            return
        else:
            params, grid_config = misc.load_pickle(filename)
            self.beamline.goniometer.omega.move_to(params['angle'], wait=False)
            self.microscope.load_grid(grid_config)
            template = params['template']
            self.results[params['uuid']] = grid_config

            for i, pos in enumerate(grid_config['grid_index']):
                pos = grid_config['grid_index'][i]
                score = grid_config['grid_scores'][pos]
                frame = grid_config['grid_frames'][i]
                filename = template.format(frame)
                x, y, z = self.microscope.props.grid_xyz[i]
                self.add_result_item(
                   params['name'], params['angle'], frame, x, y, z, score, filename, params['uuid'],
                )

    def on_clean(self, btn):
        self.manager.clear()
        self.widget.raster_clean_btn.set_sensitive(False)

    def on_start_raster(self, btn):
        params = {}
        params.update(self.microscope.grid_params)
        params.update(self.form.get_values())
        params.update({
            'distance': resol_to_dist(params['resolution'], self.beamline.detector.mm_size, self.beamline.energy.get_position()),
            'aperture': self.beamline.aperture.get_position(),
            'origin': self.beamline.goniometer.stage.get_xyz(),
            'uuid': str(uuid.uuid4()),
            'activity': 'raster',
            'energy': self.beamline.energy.get_position(),
            'angle': self.beamline.goniometer.omega.get_position(),
            'delta': RASTER_DELTA,
            'attenuation': self.beamline.attenuator.get_position(),
        })
        params = datatools.update_for_sample(
            params, sample=self.sample_store.get_current(), session=self.beamline.session_key
        )
        if not self.collector.is_busy():
            self.control.progress_fbk.set_text("Starting raster ...")
            self.collector.configure(params)
            self.collector.start()
        else:
            logger.warning('A raster scan is still active')

    def on_stop_raster(self, btn):
        self.control.progress_fbk.set_text("Stopping raster ...")
        self.collector.stop()

    def on_aperture(self, aperture, value):
        self.form.on_change(None, None, 'aperture')

    def on_state_changed(self, obj, param):
        if self.props.state == self.StateType.ACTIVE:
            self.control.action_btn.set_sensitive(False)
            self.control.stop_btn.set_sensitive(True)
            self.widget.raster_config_box.set_sensitive(False)
            self.view.set_sensitive(False)
        elif self.props.state == self.StateType.WAITING:
            self.control.progress_fbk.set_text("Waiting for results...")
            self.control.action_btn.set_sensitive(True)
            self.control.stop_btn.set_sensitive(False)
            self.widget.raster_config_box.set_sensitive(True)
            self.view.set_sensitive(True)
        else:
            self.widget.raster_config_box.set_sensitive(True)
            self.control.action_btn.set_sensitive(True)
            self.control.stop_btn.set_sensitive(False)
            self.view.set_sensitive(True)

    def on_started(self, collector, config):
        self.start_time = time.time()
        self.props.state = self.StateType.ACTIVE
        logger.info("Rastering Started.")
        grid_config = collector.get_grid()
        self.microscope.load_grid(grid_config)
        self.results[config['uuid']] = grid_config
        self.set_state(directory=config['directory'])

        # collapse existing data
        self.view.collapse_all()
        self.expanded = False

        image_viewer = Registry.get_utility(IImageViewer)
        image_viewer.set_collect_mode(True)

    def on_complete(self, collector, data):
        self.props.state = self.StateType.READY
        self.control.progress_fbk.set_text("Rastering analysis complete.")
        params = collector.get_parameters()
        logger.info('Saving overlay ...')
        self.microscope.save_image(os.path.join(params['directory'], '{}.png'.format(params['name'])))

    def on_done(self, collector, data):
        self.props.state = self.StateType.READY   # previously WAITING
        self.control.eta_fbk.set_text('--:--')
        self.control.progress_bar.set_fraction(1.0)

        image_viewer = Registry.get_utility(IImageViewer)
        image_viewer.set_collect_mode(False)

    def on_stopped(self, obj, data):
        self.props.state = self.StateType.READY
        self.control.progress_fbk.set_text("Rastering Stopped.")
        self.control.eta_fbk.set_text('--:--')

    def on_progress(self, obj, fraction, message):
        used_time = time.time() - self.start_time
        remaining_time = (1 - fraction) * used_time / fraction
        eta_time = remaining_time
        self.control.eta_fbk.set_text('{:0>2.0f}:{:0>2.0f} ETA'.format(*divmod(eta_time, 60)))
        self.control.progress_bar.set_fraction(fraction)
        self.control.progress_fbk.set_text(message)

    def on_results(self, collector, index, results):
        grid_config = collector.get_grid()
        params = collector.get_parameters()
        pos = grid_config['grid_index'][index]
        score = grid_config['grid_scores'][pos]
        frame = grid_config['grid_frames'][index]
        self.results[params['uuid']] = grid_config
        x, y, z = self.microscope.props.grid_xyz[index]
        self.add_result_item(
            params['name'], params['angle'], frame, x, y, z, score, results['filename'], params['uuid']
        )

        self.microscope.update_overlay_coords()

    @decorators.async_call
    def load_grid(self, angle, config):
        self.beamline.goniometer.omega.move_to(angle, wait=True)
        self.microscope.load_grid(config)

    def on_result_activated(self, view, path, column=None):
        itr = self.manager.model.get_iter(path)
        item = self.manager.get_item(itr)
        config = self.results[item['uuid']]

        if self.manager.model.iter_has_child(itr):
            self.load_grid(item['angle'], config)
        else:
            image_viewer = Registry.get_utility(IImageViewer)
            image_viewer.open_dataset(os.path.join(config['grid_params']['directory'], item['filename']))
            self.beamline.goniometer.stage.move_xyz(item['x_pos'], item['y_pos'], item['z_pos'], wait=False)


    def on_grid_changed(self, obj, param):
        params = self.microscope.grid_params
        if params is not None and 'width' in params and 'height' in params:
            self.form.set_values({'width': params['width'], 'height': params['height']}, propagate=True)

    def add_result_item(self, name, angle, cell, x, y, z, score, filename, id_key):
        parent, child = self.manager.add_item({
            'name': name,
            'angle': angle,
            'cell': cell,
            'x_pos': x,
            'y_pos': y,
            'z_pos': z,
            'score': score,
            'color': score,
            'filename': filename,
            'uuid': id_key,
        })
        self.widget.raster_clean_btn.set_sensitive(True)
        if parent and not self.expanded:
            self.view.expand_row(parent, False)
            self.expanded = True

