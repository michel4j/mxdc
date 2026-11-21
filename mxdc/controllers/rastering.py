
import os
import time
import uuid
from bisect import bisect_left
from datetime import datetime
from enum import IntEnum, Enum

from mxdc import Registry, IBeamline, Object, Property, Signal
from mxdc.engines.rastering import RasterCollector
from mxdc.utils import datatools, misc, decorators, grids
from mxdc.utils.converter import resol_to_dist
from mxdc.utils.grids import ScoringScheme
from mxdc.utils.gui import TreeManager, ColumnType, ColumnSpec, FormManager, FieldSpec, Validator
from mxdc.utils.log import get_module_logger
from mxdc.widgets import status, dialogs
from mxdc.widgets.imageviewer import IImageViewer
from mxdc.widgets.misc import ActiveMenu
from .microscope import IMicroscope
from .samplestore import ISampleStore


RASTER_DELTA = 0.1

logger = get_module_logger(__name__)



SCORING_LABELS = {
    ScoringScheme.SUMMARY: 'Summary',
    ScoringScheme.SCORE: 'Score',
    ScoringScheme.BRAGG: 'Bragg Spots',
    ScoringScheme.SPOTS: 'Total Spots',
    ScoringScheme.RESOLUTION: 'Resolution',
    ScoringScheme.SIGNAL: 'Signal/Noise',
    ScoringScheme.INTENSITY: 'Intensity',
    ScoringScheme.ICE: 'Ice Rings',
}


class RasterResultsManager(TreeManager):
    class Data(IntEnum):
        NAME, ANGLE, X_POS, Y_POS, Z_POS, SCORE, CELL, COLOR, UUID, FILENAME, INDEX = range(11)

    Types = [str, float, float, float, float, float, int, float, str, str, int]
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
    child = Data.INDEX
    default_sort = Data.SCORE
    default_sort_order = -1
    
    def set_colormap(self, cmap):
        self.colormap = cmap
        self.view.queue_draw()


class RasterForm(FormManager):
    def __init__(self, *args, beamline=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.beamline = beamline
        aperture_field = self.get_field('aperture')
        for i, value in enumerate(self.beamline.aperture.get_choices()):
            aperture_field.append(str(value), f"{value}")
        self.set_value('aperture', self.beamline.config.centering.aperture)

        scoring_field = self.get_field('scoring')
        for i, value in SCORING_LABELS.items():
            scoring_field.append(str(i), value)
        self.set_value('scoring', ScoringScheme.SUMMARY)

    def on_change(self, field, event, name):
        super().on_change(field, event, name)
        aperture = int(self.get_value('aperture'))

        if name in ['aperture', 'width', 'height']:
            hsteps, vsteps = grids.calc_grid_shape(
                self.get_value('width'),
                self.get_value('height'),
                aperture,
            )
            self.set_values({'hsteps': hsteps, 'vsteps': vsteps, 'height': vsteps*aperture, 'width': hsteps*aperture})

        if name in ['aperture', 'exposure']:
            exposure = self.get_value('exposure')
            
            exposure_limit = 1/self.beamline.config.raster.max_freq
            min_exposure = misc.nearest(aperture / self.beamline.config.raster.max_speed, 0.025)
            self.set_value('exposure', max(exposure, exposure_limit, min_exposure))


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
        FieldSpec('aperture', 'cbox', '{}', Validator.Int(None, None, 0)),
        FieldSpec('scoring', 'cbox', '{}', Validator.Int(None, None, ScoringScheme.SCORE)),
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
            grid_config['grid_params']['aperture'] = params['aperture']
            grid_config = grids.fix_grid(params, grid_config, max_delay=0.5)
            self.microscope.load_grid(grid_config)

            result_items = self.get_grid_scores(params, grid_config)
            self.manager.add_items(result_items)
            self.results[params['uuid']] = grid_config
            self.widget.raster_clean_btn.set_sensitive(True)
            self.expanded = True
            self.beamline.goniometer.omega.move_to(params['angle'], wait=False)

    def on_clean(self, btn):
        self.manager.clear()
        self.widget.raster_clean_btn.set_sensitive(False)

    def on_start_raster(self, btn):
        params = {}
        params.update(self.microscope.grid_params)
        params.update(self.form.get_values())

        sample = self.sample_store.get_current()
        prefix = 'test' if not sample else sample.get('name', 'test')
        suffix = datetime.now().strftime('%m%d-%H%M%S')

        params.update({
            'name': f'{prefix}-{suffix}',
            'distance': resol_to_dist(params['resolution'], self.beamline.detector.mm_size, self.beamline.energy.get_position()),
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

    def on_started(self, collector, params):
        self.start_time = time.time()
        self.props.state = self.StateType.ACTIVE
        logger.info("Rastering Started.")
        grid_config = collector.get_grid()
        self.microscope.load_grid(grid_config)
        self.results[params['uuid']] = grid_config
        self.set_state(directory=params['directory'])

        # collapse existing data
        self.view.collapse_all()
        self.expanded = False

        image_viewer = Registry.get_utility(IImageViewer)
        image_viewer.set_collect_mode(True)

    def on_complete(self, collector, data):
        params, grid_config = data
        grid_config = grids.fix_grid(params, grid_config, max_delay=0.5)
        self.update_scores(params, grid_config)
        self.props.state = self.StateType.READY
        self.control.progress_fbk.set_text("Rastering analysis complete.")
        logger.info('Saving overlay ...')
        self.microscope.save_image(os.path.join(params['directory'], f'{params["name"]}.png'))

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
        config = collector.get_grid()
        params = collector.get_parameters()
        cell_item = self.get_cell_score(index, params, config, filename=results.get('filename', ""))
        self.add_result_item(cell_item)

        self.microscope.update_overlay_coords()

    @staticmethod
    def get_cell_score(index, params, config, filename="") -> dict:
        """
        Fetch grid results for the given index, parameters and config
        :param index: 0-based sequential position in the grid
        :param params: raster collection parameters
        :param config: detailed grid configuration and scores
        :return: dict
        """
        pos = config['grid_index'][index]
        score = config['grid_scores'][pos]
        frame = config['grid_frames'][index]
        x, y, z = config['grid_xyz'][index]
        
        if not filename and 'template' in params:
            filename = params['template'].format(frame)        

        return {
            'index': index,
            'name': params['name'],
            'angle': params['angle'],
            'cell': frame,
            'x_pos': x,
            'y_pos': y,
            'z_pos': z,
            'score': score,
            'color': score,
            'filename': filename,
            'uuid': params['uuid'],
        }
        
    def get_grid_scores(self, params, config):
        items = []
        for i, score in enumerate(config['grid_scores'].flat):
            pos = config['grid_index'][i]
            frame = config['grid_frames'][i]
            if pos[1] < 0 or frame < 1:
                continue
            items.append(self.get_cell_score(i, params, config))

        return items

    def update_scores(self, params, grid_config):
        self.microscope.load_grid(grid_config)
        self.results[params['uuid']] = grid_config
        items = self.get_grid_scores(params, grid_config)
        self.manager.update_items(items, delete_missing=True)

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
            file_name = os.path.join(config['grid_params']['directory'], item['filename'])
            image_viewer.open_dataset(file_name)
            self.beamline.goniometer.stage.move_xyz(item['x_pos'], item['y_pos'], item['z_pos'], wait=False)

    def on_grid_changed(self, obj, param):
        params = self.microscope.grid_params
        if not params:
            return
            
        if 'width' in params and 'height' in params:
            self.form.set_values({
                'width': params['width'],
                'height': params['height'],
            }, propagate=True)
            
        if 'exposure' in params:
            self.form.set_value('exposure', params['exposure'], propagate=True)
            
        if 'aperture' in params:
            self.form.set_value('aperture', params['aperture'], propagate=True)

    def add_result_item(self, item: dict):
        parent, child = self.manager.add_item(item)
        self.widget.raster_clean_btn.set_sensitive(True)
        if parent and not self.expanded:
            self.view.expand_row(parent, False)
            self.expanded = True

