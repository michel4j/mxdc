import os
import time
import uuid
import copy
from collections import OrderedDict
from datetime import datetime
import numpy
from gi.repository import Gtk, GObject, Gdk
from twisted.python.components import globalRegistry

from microscope import IMicroscope
from mxdc.beamline.mx import IBeamline
from mxdc.engine.rastering import RasterCollector
from mxdc.utils import colors, runlists, config, misc
from mxdc.utils.converter import resol_to_dist
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs
from mxdc.widgets.imageviewer import IImageViewer
from samplestore import ISampleStore
import common

RASTER_DELTA = 0.5

logger = get_module_logger(__name__)


def frame_score(info):
    if info:
        bragg = info['bragg_spots']
        ice = 1 / (1.0 + info['ice_rings'])
        saturation = info['saturation'][1]
        sc_x = numpy.array([bragg, saturation, ice])
        sc_w = numpy.array([5, 10, 0.2])
        score = numpy.exp((sc_w * numpy.log(sc_x)).sum() / sc_w.sum())
    else:
        score = 0.0
    return score


class RasterStore(Gtk.TreeStore):
    class Data(object):
        NAME, ANGLE, X_POS, Y_POS, Z_POS, SCORE, CELL, STATE, UUID = range(9)

    class State(object):
        PARENT, PENDING, ACTIVE, COMPLETE = range(4)

    def __init__(self):
        super(RasterStore, self).__init__(str, float, float, float, float, float, int, int, str)

    def find_parent(self, name):
        parent = self.get_iter_first()
        while parent:
            if self[parent][self.Data.NAME] == name:
                break
            parent = self.iter_next(parent)
        return parent

    def add_item(self, item, parent=None):
        """Add one item to the tree store. Items with the same name will be grouped with same parent"""
        if not parent:
            parent = self.find_parent(item['name'])

        # No parent exists, create one
        if not parent:
            parent = self.append(
                None,
                row=[item['name'], item['angle'], 0.0, 0.0, 0.0, 0.0, 0, self.State.PARENT, item['uuid']]
            )
        child = self.append(
            parent,
            row=[
                'cell-{}'.format(item['cell']), item['angle'], item['xyz'][0], item['xyz'][1],item['xyz'][2],
                item.get('score', 0.0), item['cell'], item.get('state', self.State.PENDING), item['uuid']
            ]
        )
        return self.get_path(parent), self.get_path(child)

    def add_items(self, items):
        """Add a list of items to the tree store with the same parent. The tree will be cleared first"""
        self.clear()
        for item in items:
            self.add_item(item)

    def update_item(self, name, cell, info):
        """Given the name and the cell number update the row with the specified info dictionary
        The dictionary should be keyed using the data constants
        """
        itr = self.get_iter_first()
        while itr:
            if self[itr][self.Data.NAME] == name:
                if self.has_children(itr):
                    child_itr = self.iter_children(itr)
                    while child_itr:
                        if self[child_itr][self.Data.CELL] == cell:
                            for column, value in info.items():
                                self[child_itr][column] = value
                            break
                        child_itr = self.iter_next(child_itr)
                    break
            itr = self.iter_next(itr)


class RasterController(GObject.GObject):
    Column = OrderedDict([
        (RasterStore.Data.NAME, 'Name'),
        (RasterStore.Data.ANGLE, 'Angle'),
        (RasterStore.Data.X_POS, 'X (mm)'),
        (RasterStore.Data.Y_POS, 'Y (mm)'),
        (RasterStore.Data.Z_POS, 'Z (mm)'),
        (RasterStore.Data.SCORE, 'Score (%)'),
        (RasterStore.Data.STATE, ''),
    ])
    Format = {
        RasterStore.Data.NAME: '{}',
        RasterStore.Data.ANGLE: '{:0.1f}\xc2\xb0',
        RasterStore.Data.X_POS: '{:0.4f}',
        RasterStore.Data.Y_POS: '{:0.4f}',
        RasterStore.Data.Z_POS: '{:0.4f}',
        RasterStore.Data.SCORE: '{:0.2f}',
    }
    Specs = {
        # field: ['field_type', format, type, default]
        'resolution': ['entry', '{:0.3g}', float, 2.0],
        'exposure': ['entry', '{:0.3g}', float, 1.0],
    }

    class StateType:
        READY, ACTIVE, PAUSED = range(3)

    state = GObject.Property(type=int, default=StateType.READY)
    config = GObject.Property(type=object)

    def __init__(self, view, widget):
        super(RasterController, self).__init__()
        self.model = RasterStore()
        self.view = view
        self.widget = widget

        # housekeeping
        self.start_time = 0
        self.pause_dialog = None
        self.results = {}

        self.view.set_model(self.model)
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.microscope = globalRegistry.lookup([], IMicroscope)
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        self.collector = RasterCollector()

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
        # Selected Column
        for data, title in self.Column.items():
            if data == RasterStore.Data.STATE:
                renderer = Gtk.CellRendererText(text=u"\u25a0")
                column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_fixed_width(40)
                column.set_cell_data_func(renderer, self.format_state, data)
            else:
                renderer = Gtk.CellRendererText()
                column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_expand(True)
                column.set_sort_column_id(data)
                column.set_cell_data_func(renderer, self.format_cell, data)
                if data == RasterStore.Data.NAME:
                    column.set_resizable(True)
                else:
                    renderer.set_alignment(1.0, 0.5)
                    renderer.props.family = 'Monospace'
            column.set_clickable(True)
            column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
            self.view.append_column(column)

        self.view.props.activate_on_single_click = False
        self.widget.raster_start_btn.connect('clicked', self.start_raster)
        self.widget.raster_stop_btn.connect('clicked', self.stop_raster)
        self.view.connect('row-activated', self.on_result_activated)

        labels = {
            'energy': (self.beamline.energy, self.widget.raster_energy_fbk, {'format': '{:0.3f} keV'}),
            'attenuation': (self.beamline.attenuator, self.widget.raster_attenuation_fbk, {'format': '{:0.0f} %'}),
            'aperture': (self.beamline.aperture, self.widget.raster_aperture_fbk, {'format': '{:0.0f} \xc2\xb5m'}),
            'omega': (self.beamline.omega, self.widget.raster_angle_fbk, {'format': '{:0.2f} deg'}),
            'maxres': (self.beamline.maxres, self.widget.raster_maxres_fbk, {'format': '{:0.2f} A'}),
        }
        self.monitors = {
            name: common.DeviceMonitor(dev, lbl, **kw)
            for name, (dev, lbl, kw) in labels.items()
        }

    def format_cell(self, column, renderer, model, itr, data):
        if model[itr][RasterStore.Data.STATE] == RasterStore.State.PARENT and not data in [RasterStore.Data.NAME,
                                                                                           RasterStore.Data.ANGLE]:
            renderer.set_property('text', '')
        else:
            value = model[itr][data]
            renderer.set_property('text', self.Format[data].format(value))

    def format_state(self, column, renderer, model, itr, data):
        value = model[itr][data]
        if value == RasterStore.State.PARENT:
            col = Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=0.0)
            renderer.set_property("foreground-rgba", col)
            renderer.set_property("text", "")
        else:
            score = model[itr][RasterStore.Data.SCORE]
            col = Gdk.RGBA(**self.microscope.grid_cmap.rgba(score))
            renderer.set_property("foreground-rgba", col)
            renderer.set_property("text", u"\u25a0")

    def get_parameters(self):
        info = {}
        for name, details in self.Specs.items():
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
            params['angle'] = self.microscope.grid_params['angle']
            params['origin'] = self.microscope.grid_params['origin']
            params['energy'] = self.beamline.energy.get_position()
            params['distance'] = resol_to_dist(params['resolution'], self.beamline.detector.mm_size, params['energy'])
            params['attenuation'] = self.beamline.attenuator.get()
            params['delta'] = RASTER_DELTA
            params['uuid'] = str(uuid.uuid4())
            params['name'] = datetime.now().strftime('%Y%m%d-%H%M')
            params['activity'] = 'raster'
            params = runlists.update_for_sample(params, self.sample_store.get_current())

            self.props.config = params
            self.collector.configure(grid, self.props.config)
            self.collector.start()

    def stop_raster(self, *args, **kwargs):
        self.widget.raster_progress_lbl.set_text("Stopping raster ...")
        self.collector.stop()

    def on_sample_updated(self, obj):
        sample = self.sample_store.get_current()
        sample_text = '{name}|{group}|{container}|{port}'.format(
            name=sample.get('name', '...'), group=sample.get('group', '...'), container=sample.get('container', '...'),
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

    def on_started(self, obj):
        self.start_time = time.time()
        self.props.state = self.StateType.ACTIVE
        logger.info("Rastering Started.")

        self.results[self.props.config['uuid']] = {
            'config': copy.deepcopy(self.props.config),
            'grid': self.microscope.grid_xyz,
            'scores': {}
        }

        directory = self.props.config['directory']
        home_dir = misc.get_project_home()
        current_dir = directory.replace(home_dir, '~')
        self.widget.raster_dir_fbk.set_text(current_dir)

        #self.widget.raster_points_fbk.set_text('{}'.format(len(self.microscope.grid_xyz)))

    def on_done(self, obj=None):
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

    def on_stopped(self, obj=None):
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

    def on_new_image(self, widget, file_path):
        image_viewer = globalRegistry.lookup([], IImageViewer)
        frame = os.path.splitext(os.path.basename(file_path))[0]
        image_viewer.queue_frame(file_path)
        logger.info('Frame acquired: {}'.format(frame))

    def on_results(self, obj, cell, results):
        score = frame_score(results)
        self.microscope.add_grid_score(cell, score)
        parent, child = self.model.add_item({
            'name': self.props.config['name'],
            'angle': self.props.config['angle'],
            'origin': self.props.config['origin'],
            'cell': cell,
            'xyz': self.microscope.props.grid_xyz[cell],
            'score': score,
            'state': RasterStore.State.ACTIVE,
            'uuid': self.props.config['uuid'],
        })
        self.results[self.props.config['uuid']]['scores'][cell] = score
        self.view.expand_row(parent, False)
        self.view.scroll_to_cell(child, None, True, 0.5, 0.5)

    def on_result_activated(self, view, path, column=None):
        itr = self.model.get_iter(path)
        uid, angle, x, y, z, state = self.model.get(
            itr,
            RasterStore.Data.UUID, RasterStore.Data.ANGLE, RasterStore.Data.X_POS,
            RasterStore.Data.Y_POS, RasterStore.Data.Z_POS, RasterStore.Data.STATE
        )
        if state == RasterStore.State.PARENT:
            self.beamline.omega.move_to(angle, wait=True)
            grid = self.results[uid]
            self.microscope.load_grid(
                grid['grid'],
                {'origin': grid['config']['origin'], 'angle': grid['config']['angle']},
                grid['scores']
            )
            self.beamline.sample_stage.move_xyz(*grid['config']['origin'])
            self.widget.raster_directory_fbk.set_text(grid['config']['directory'])
        else:
            self.beamline.sample_stage.move_xyz(x, y, z)

    def on_grid_changed(self, obj, param):
        grid = self.microscope.props.grid_xyz
        state = self.microscope.props.grid_state
        raster_page = self.widget.samples_stack.get_child_by_name('rastering')
        if grid is not None and state == self.microscope.GridState.PENDING:
            self.widget.raster_grid_info.set_text('Defined grid has {} points'.format(len(grid)))
            self.widget.raster_command_box.set_sensitive(True)
            #self.widget.samples_stack.set_visible_child_name('rastering')
            self.widget.samples_stack.child_set(raster_page, needs_attention=True)
        else:
            msg = 'Please define a new grid using the sample viewer!'
            self.widget.raster_grid_info.set_text(msg)
            self.widget.raster_command_box.set_sensitive(False)
            self.widget.samples_stack.child_set(raster_page, needs_attention = False)

