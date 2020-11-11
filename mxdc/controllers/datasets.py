import copy
import time
from datetime import datetime, timedelta, timezone

from gi.repository import Gio, Gtk
from zope.interface import Interface

from mxdc import Object, Signal, IBeamline, Property
from mxdc import Registry
from mxdc.conf import load_cache, save_cache
from mxdc.engines.automation import Automator
from mxdc.engines.diffraction import DataCollector
from mxdc.utils import converter, datatools, misc
from mxdc.utils.log import get_module_logger
from mxdc.widgets import datawidget, dialogs, arrowframe

from mxdc.widgets.imageviewer import ImageViewer, IImageViewer
from . import common
from .microscope import IMicroscope
from .samplestore import ISampleStore, SampleQueue, SampleStore

logger = get_module_logger(__name__)

(
    RESPONSE_REPLACE_ALL,
    RESPONSE_REPLACE_BAD,
    RESPONSE_SKIP,
    RESPONSE_CANCEL,
) = list(range(4))


class IDatasets(Interface):
    """Sample information database."""
    pass


class ConfigDisplay(object):
    Formats = {
        'resolution': '{:0.3g} Å',
        'delta': '{:0.3g}°',
        'range': '{:0.1f}°',
        'start': '{:0.1f}°',
        'wedge': '{:0.1f}°',
        'energy': '{:0.3f} keV',
        'distance': '{:0.1f} mm',
        'exposure': '{:0.3g} s',
        'attenuation': '{:0.1f} %',
        'strategy_desc': '{}',
        'first': '{}',
        'name': '{}',
        'strategy': '{}',
        'helical': '{}',
        'inverse': '{}',
    }

    def __init__(self, item, widget, label_prefix='run'):
        self.item = item
        self.widget = widget
        self.prefix = label_prefix
        self.item.connect('notify::info', self.on_item_changed)

    def on_item_changed(self, item, param):
        for name, format in list(self.Formats.items()):
            field_name = '{}_{}_lbl'.format(self.prefix, name)
            field = getattr(self.widget, field_name, None)
            if field and name in self.item.props.info:
                field.set_text(format.format(self.item.props.info[name]))


class AutomationController(Object):
    class StateType:
        STOPPED, PAUSED, ACTIVE, PENDING = list(range(4))

    state = Property(type=int, default=0)

    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.image_viewer = Registry.get_utility(IImageViewer)
        self.run_dialog = datawidget.DataDialog()
        self.widget.auto_edit_acq_btn.set_popover(self.run_dialog.popover)
        self.automation_queue = SampleQueue(self.widget.auto_queue)
        self.automator = Automator()

        self.config = datawidget.RunItem()
        self.config_display = ConfigDisplay(self.config, self.widget, 'auto')

        self.start_time = 0
        self.pause_info = None
        self.automator.connect('done', self.on_done)
        self.automator.connect('paused', self.on_pause)
        self.automator.connect('stopped', self.on_stopped)
        self.automator.connect('progress', self.on_progress)
        self.automator.connect('sample-done', self.on_sample_done)
        self.automator.connect('sample-started', self.on_sample_started)
        self.automator.connect('started', self.on_started)
        self.automator.connect('error', self.on_error)

        self.connect('notify::state', self.on_state_changed)

        # default
        params = self.run_dialog.get_default(strategy_type=datawidget.StrategyType.SINGLE)
        params.update({
            'resolution': converter.dist_to_resol(
                250, self.beamline.detector.mm_size, self.beamline.energy.get_position()
            ),
            'energy': self.beamline.energy.get_position(),
        })
        self.run_dialog.configure(params)
        self.config.props.info = self.run_dialog.get_parameters()

        # btn, type, options method
        self.tasks = {
            'mount': self.widget.mount_task_btn,
            'center': self.widget.center_task_btn,
            'pause1': self.widget.pause1_task_btn,
            'acquire': self.widget.acquire_task_btn,
            'analyse': self.widget.analyse_task_btn,
            'pause2': self.widget.pause2_task_btn,
        }
        self.task_templates = [
            (self.widget.mount_task_btn, Automator.Task.MOUNT),
            (self.widget.center_task_btn, Automator.Task.CENTER),
            (self.widget.pause1_task_btn, Automator.Task.PAUSE),
            (self.widget.acquire_task_btn, Automator.Task.ACQUIRE),
            (self.widget.analyse_task_btn, Automator.Task.ANALYSE),
            (self.widget.pause2_task_btn, Automator.Task.PAUSE)
        ]
        self.options = {
            'capillary': self.widget.center_cap_option,
            'loop': self.widget.center_loop_option,
            'screen': self.widget.analyse_screen_option,
            'process': self.widget.analyse_process_option,
            'anomalous': self.widget.analyse_anom_option,
            'powder': self.widget.analyse_powder_option,
            'analyse': self.widget.analyse_task_btn
        }
        self.setup()

    def import_from_cache(self):
        config = load_cache('auto')
        if config:
            self.config.info = config['info']
            for name, btn in list(self.tasks.items()):
                if name in config:
                    btn.set_active(config[name])
            for name, option in list(self.options.items()):
                if name in config:
                    option.set_active(config[name])

    def get_options(self, task_type):
        if task_type == Automator.Task.CENTER:
            for name in ['loop', 'crystal', 'raster', 'capillary']:
                if name in self.options and self.options[name].get_active():
                    return {'method': name}
        elif task_type == Automator.Task.ACQUIRE:
            options = {}
            if self.options['analyse'].get_active():
                for name in ['screen', 'process', 'powder']:
                    if self.options[name].get_active():
                        options = {'analysis': name, 'anomalous': self.options['anomalous'].get_active()}
                        break
            options.update(self.config.props.info)
            options['energy'] = self.beamline.energy.get_position()  # use current beamline energy
            return options
        return {}

    def get_task_list(self):
        return [
            {'type': kind, 'options': self.get_options(kind)}
            for btn, kind in self.task_templates if btn.get_active()
        ]

    def get_sample_list(self):
        return self.automation_queue.get_samples()

    def on_state_changed(self, obj, param):
        if self.props.state == self.StateType.ACTIVE:
            self.widget.auto_collect_icon.set_from_icon_name(
                "media-playback-pause-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.widget.auto_stop_btn.set_sensitive(True)
            self.widget.auto_collect_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        elif self.props.state == self.StateType.PAUSED:
            self.widget.auto_progress_lbl.set_text("Automation paused!")
            self.widget.auto_collect_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.widget.auto_stop_btn.set_sensitive(True)
            self.widget.auto_collect_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        elif self.props.state == self.StateType.PENDING:
            self.widget.auto_collect_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.widget.auto_sequence_box.set_sensitive(False)
            self.widget.auto_collect_btn.set_sensitive(False)
            self.widget.auto_stop_btn.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        else:
            self.widget.auto_collect_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.widget.auto_stop_btn.set_sensitive(False)
            self.widget.auto_collect_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(True)
            self.widget.auto_groups_btn.set_sensitive(True)

    def setup(self):
        self.import_from_cache()
        self.widget.auto_edit_acq_btn.connect('clicked', self.on_edit_acquisition)
        self.run_dialog.data_save_btn.connect('clicked', self.on_save_acquisition)

        for btn in list(self.tasks.values()):
            btn.connect('toggled', self.on_save_acquisition)

        self.widget.auto_collect_btn.connect('clicked', self.on_start_automation)
        self.widget.auto_stop_btn.connect('clicked', self.on_stop_automation)
        self.widget.auto_clean_btn.connect('clicked', self.on_clean_automation)
        self.widget.auto_groups_btn.set_popover(self.widget.auto_groups_pop)
        self.widget.center_task_btn.bind_property('active', self.widget.center_options_box, 'sensitive')
        self.widget.analyse_task_btn.bind_property('active', self.widget.analyse_options_box, 'sensitive')
        self.widget.acquire_task_btn.bind_property('active', self.widget.acquire_options_box, 'sensitive')

    def on_edit_acquisition(self, obj):
        info = self.config.info
        info['energy'] = self.beamline.energy.get_position()
        self.run_dialog.configure(info)

    def on_save_acquisition(self, obj):
        self.config.props.info = self.run_dialog.get_parameters()
        cache = {
            'info': self.config.info,
        }
        for name, btn in list(self.tasks.items()):
            cache[name] = btn.get_active()
        for name, option in list(self.options.items()):
            cache[name] = option.get_active()
        save_cache(cache, 'auto')

    def on_progress(self, obj, fraction, message):
        used_time = time.time() - self.start_time
        remaining_time = 0 if not fraction else (1 - fraction) * used_time / fraction
        eta_time = remaining_time
        self.widget.auto_eta.set_text('{:0>2.0f}:{:0>2.0f} ETA'.format(*divmod(eta_time, 60)))
        self.widget.auto_pbar.set_fraction(fraction)
        self.widget.auto_progress_lbl.set_text(message)

    def on_sample_done(self, obj, uuid):
        self.automation_queue.mark_progress(uuid, SampleStore.Progress.DONE)

    def on_sample_started(self, obj, uuid):
        self.automation_queue.mark_progress(uuid, SampleStore.Progress.ACTIVE)

    def on_done(self, obj, data):
        self.props.state = self.StateType.STOPPED
        self.widget.auto_progress_lbl.set_text("Automation Completed.")
        self.widget.auto_eta.set_text('--:--')
        self.widget.auto_pbar.set_fraction(1.0)

    def on_stopped(self, obj, data):
        self.props.state = self.StateType.STOPPED
        self.widget.auto_progress_lbl.set_text("Automation Stopped.")
        self.widget.auto_eta.set_text('--:--')

    def on_pause(self, obj, paused, reason):
        if paused:
            self.props.state = self.StateType.PAUSED
            if reason:
                # Build the dialog message
                self.pause_info = dialogs.make_dialog(
                    Gtk.MessageType.WARNING, 'Automation Paused', reason,
                    buttons=(('OK', Gtk.ResponseType.OK),)
                )
                self.pause_info.run()
                if self.pause_info:
                    self.pause_info.destroy()
                    self.pause_info = None
        else:
            self.props.state = self.StateType.ACTIVE
            if self.pause_info:
                self.pause_info.destroy()
                self.pause_info = None

    def on_error(self, obj, reason):
        # Build the dialog message
        error_dialog = dialogs.make_dialog(
            Gtk.MessageType.WARNING, 'Automation Error!', reason,
            buttons=(('OK', Gtk.ResponseType.OK),)
        )
        error_dialog.run()
        error_dialog.destroy()

    def on_started(self, obj, data):
        self.start_time = time.time()
        self.props.state = self.StateType.ACTIVE
        logger.info("Automation Started.")

    def on_stop_automation(self, obj):
        self.automator.stop()

    def on_clean_automation(self, obj):
        self.automation_queue.clean()

    def on_start_automation(self, obj):
        if self.props.state == self.StateType.ACTIVE:
            self.widget.auto_progress_lbl.set_text("Pausing automation ...")
            self.automator.pause()
        elif self.props.state == self.StateType.PAUSED:
            self.widget.auto_progress_lbl.set_text("Resuming automation ...")
            self.automator.resume()
        elif self.props.state == self.StateType.STOPPED:
            tasks = self.get_task_list()
            samples = self.get_sample_list()
            if not samples:
                msg1 = 'Queue is empty!'
                msg2 = 'Please add samples and try again.'
                dialogs.warning(msg1, msg2)
            else:
                self.widget.auto_progress_lbl.set_text("Starting automation ...")
                self.props.state = self.StateType.PENDING
                self.automator.configure(samples, tasks)
                self.widget.auto_pbar.set_fraction(0)
                self.automator.start()
                self.image_viewer.set_collect_mode(True)


class DatasetsController(Object):

    class Signals:
        changed = Signal('samples-changed', arg_types=(object,))
        active = Signal('active-sample', arg_types=(object,))
        selected = Signal('sample-selected', arg_types=(object,))

    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.collector = DataCollector()
        self.collecting = False
        self.stopping = False
        self.pause_info = False
        self.start_time = 0
        self.frame_monitor = None
        self.first_frame = True
        self.monitors = {}
        self.image_viewer = ImageViewer()
        self.microscope = Registry.get_utility(IMicroscope)
        self.run_editor = datawidget.RunEditor()
        self.editor_frame = arrowframe.ArrowFrame()
        self.editor_frame.add(self.run_editor.data_form)
        self.widget.datasets_overlay.add_overlay(self.editor_frame)
        self.run_store = Gio.ListStore(item_type=datawidget.RunItem)
        self.run_store.connect('items-changed', self.on_runs_changed)

        self.collector.connect('done', self.on_done)
        self.collector.connect('paused', self.on_pause)
        self.collector.connect('stopped', self.on_stopped)
        self.collector.connect('progress', self.on_progress)
        self.collector.connect('started', self.on_started)
        Registry.add_utility(IDatasets, self)
        self.setup()

    def import_from_cache(self):
        runs = load_cache('runs')
        if runs:
            self.run_editor.set_points(self.microscope.props.points)
            for run in runs:
                new_item = datawidget.RunItem(
                    run['info'], state=run['state'], created=run['created'], uid=run['uuid']
                )
                self.run_store.insert_sorted(new_item, datawidget.RunItem.sorter)
            self.widget.datasets_collect_btn.set_sensitive(True)

    def update_positions(self):
        pos = 0
        item = self.run_store.get_item(pos)
        while item:
            item.props.position = pos
            pos += 1
            item = self.run_store.get_item(pos)

    def setup(self):
        self.widget.datasets_list.bind_model(self.run_store, self.create_run_config)
        self.widget.datasets_viewer_box.add(self.image_viewer)
        self.widget.datasets_clean_btn.connect('clicked', self.on_clean_runs)
        self.widget.datasets_list.connect('row-activated', self.on_row_activated)
        self.widget.dsets_dir_btn.connect('clicked', self.open_terminal)

        self.run_editor.data_delete_btn.connect('clicked', self.on_delete_run)
        self.run_editor.data_copy_btn.connect('clicked', self.on_copy_run)
        self.run_editor.data_save_btn.connect('clicked', self.on_save_run)
        self.sample_store = Registry.get_utility(ISampleStore)
        self.sample_store.connect('updated', self.on_sample_updated)

        self.import_from_cache()

        new_item = datawidget.RunItem(state=datawidget.RunItem.StateType.ADD)
        pos = self.run_store.insert_sorted(new_item, datawidget.RunItem.sorter)
        self.run_editor.set_item(new_item)
        first_row = self.widget.datasets_list.get_row_at_index(pos)
        self.editor_frame.set_row(first_row)

        labels = {
            'omega': (self.beamline.goniometer.omega, self.widget.dsets_omega_fbk, '{:0.1f}°'),
            'energy': (self.beamline.energy, self.widget.dsets_energy_fbk, '{:0.3f} keV'),
            'attenuation': (self.beamline.attenuator, self.widget.dsets_attenuation_fbk, '{:0.0f} %'),
            'maxres': (self.beamline.maxres, self.widget.dsets_maxres_fbk, '{:0.2f} Å'),
            'aperture': (self.beamline.aperture, self.widget.dsets_aperture_fbk, '{:0.0f} µm'),
            'two_theta': (self.beamline.two_theta, self.widget.dsets_2theta_fbk, '{:0.0f}°'),
        }
        self.group_selectors = []
        self.monitors = {
            name: common.DeviceMonitor(dev, lbl, fmt)
            for name, (dev, lbl, fmt) in list(labels.items())
        }
        self.widget.datasets_collect_btn.connect('clicked', self.on_collect_btn)
        self.microscope.connect('notify::points', self.on_points)
        self.frame_monitor = self.beamline.detector.connect('new-image', self.on_new_image)

    def create_run_config(self, item):
        config = datawidget.RunConfig()
        config.set_item(item)
        return config.get_widget()

    def auto_save_run(self):
        item = self.run_editor.item
        # auto save current parameters
        if item and item.props.state not in [datawidget.RunItem.StateType.ADD, datawidget.RunItem.StateType.COMPLETE]:
            info = self.run_editor.get_parameters()
            item.props.info = info
            item.props.state = datawidget.RunItem.StateType.DRAFT
            self.check_run_store()

    def on_row_activated(self, list, row):
        self.auto_save_run()
        self.editor_frame.set_row(row)
        position = row.get_index()
        item = self.run_store.get_item(position)
        num_items = self.run_store.get_n_items()

        # add a new run
        if item.state == item.StateType.ADD and num_items < 8:
            if position > 0:
                prev = self.run_store.get_item(position - 1)
                config = prev.info.copy()
            else:
                config = self.run_editor.get_default()
                energy = self.beamline.bragg_energy.get_position()
                distance = self.beamline.distance.get_position()
                resolution = converter.dist_to_resol(
                    distance, self.beamline.detector.mm_size, energy
                )
                config.update({
                    'resolution': round(resolution, 4),
                    'strategy': datawidget.StrategyType.SINGLE,
                    'energy': energy,
                    'distance': distance,
                })
            sample = self.sample_store.get_current()
            config['name'] = sample.get('name', 'test')
            item.props.info = config
            item.props.state = datawidget.RunItem.StateType.DRAFT
            new_item = datawidget.RunItem({}, state=datawidget.RunItem.StateType.ADD)
            self.run_store.insert_sorted(new_item, datawidget.RunItem.sorter)
            self.check_run_store()

        # switch focus
        self.run_editor.set_item(item)

    def on_runs_changed(self, model, position, removed, added):
        self.update_positions()
        if self.run_store.get_n_items() < 2:
            self.widget.datasets_collect_btn.set_sensitive(False)

    def on_points(self, *args, **kwargs):
        self.run_editor.set_points(self.microscope.props.points)

    def generate_run_list(self):
        runs = []

        pos = 0
        item = self.run_store.get_item(pos)
        sample = self.sample_store.get_current()
        while item:
            if item.state in [item.StateType.DRAFT, item.StateType.ACTIVE]:
                run = {'uuid': item.uuid}
                run.update(item.info)

                # convert points to coordinates and then
                # make sure point is not empty if end_point is set
                for name in ['p0', 'p1']:
                    if run.get(name) not in [-1, 0, None]:
                        run[name] = self.run_editor.get_point(run[name])
                    elif name in run:
                        del run[name]
                if 'p1' in run and 'p0' not in run:
                    run['p0'] = run.pop('p1')

                run = datatools.update_for_sample(run, sample)
                runs.append(run)
            pos += 1
            item = self.run_store.get_item(pos)
        return runs

    def check_runlist(self, runs):
        existing = {
            run['name']: self.beamline.detector.check(run['directory'], run['name'], first=run['first'])
            for run in runs
        }

        config_data = copy.deepcopy(runs)
        success = True
        collected = 0

        # check for existing files
        if any(pair[0] for pair in existing.values()):
            details = '\n'.join([
                '{}: {}'.format(k, datatools.summarize_list(v[0]))
                for k, v in existing.items()
                if v[0]

            ])
            header = 'Frames from this sequence already exist!\n'
            sub_header = details + (
                '\n\n<b>What would you like to? </b>\n'
                'NOTE: Starting over will delete existing data!\n'
            )
            buttons = (
                ('Cancel', RESPONSE_CANCEL),
                ('Start Over', RESPONSE_REPLACE_ALL),
            )
            # Add resume option if resumable
            if all(pair[1] for pair in existing.values()):
                buttons += (('Resume', RESPONSE_SKIP),)

            response = dialogs.warning(header, sub_header, buttons=buttons)
            if response == RESPONSE_SKIP:
                success = True
                collected = 0
                for run in config_data:
                    run['existing'] = datatools.summarize_list(existing.get(run['name'], ([], False))[0])
                    collected += len(datatools.frameset_to_list(run['existing']))
            elif response == RESPONSE_REPLACE_ALL:
                success = True
            else:
                success = False
        return success, config_data, collected

    def check_run_store(self):
        count = 0
        item = self.run_store.get_item(count)
        sample = self.sample_store.get_current()
        fix_names = datatools.NameManager(sample.get('name', ''))
        while item:
            if item.props.state in [item.StateType.DRAFT, item.StateType.ACTIVE]:
                info = item.info.copy()
                new_name = fix_names(info['name'])
                info['name'] = new_name
                item.props.info = info
                item.props.position = count

            count += 1
            item = self.run_store.get_item(count)
        self.widget.datasets_collect_btn.set_sensitive(count > 1)
        self.update_cache()

    def update_cache(self):
        count = 0
        item = self.run_store.get_item(count)
        cache = []
        while item:
            if item.props.state in [item.StateType.DRAFT, item.StateType.ACTIVE]:
                item.props.info = item.info
                item.props.position = count
                cache.append({
                    'state': item.state,
                    'created': item.created,
                    'position': item.position,
                    'uuid': item.uuid,
                    'info': item.info
                })
            count += 1
            item = self.run_store.get_item(count)
        save_cache(cache, 'runs')

    def add_runs(self, runs):
        num_items = self.run_store.get_n_items()
        if num_items > 7:
            return

        default = self.run_editor.get_default(strategy_type=datawidget.StrategyType.FULL)
        dist = self.beamline.distance.get_position()
        for run in runs:
            energy = run.get('energy', self.beamline.energy.get_position())
            res = converter.dist_to_resol(
                dist, self.beamline.detector.mm_size, energy
            )
            resolution = run.get('resolution', res)
            info = copy.copy(default)
            info.update({
                'resolution': round(resolution, 4),
                'strategy': datawidget.StrategyType.FULL,
                'energy': energy,
                'name': run['name'],
            })
            new_item = datawidget.RunItem({}, state=datawidget.RunItem.StateType.DRAFT)
            new_item.props.info = info
            self.run_store.insert_sorted(new_item, datawidget.RunItem.sorter)
        self.check_run_store()

    def open_terminal(self, button):
        directory = self.widget.dsets_dir_fbk.get_text()
        misc.open_terminal(directory)

    def on_sample_updated(self, obj):
        sample = self.sample_store.get_current()
        sample_text = '{name}|{port}'.format(
            name=sample.get('name', '...'),
            port=sample.get('port', '...')
        ).replace('|...', '')
        self.widget.dsets_sample_fbk.set_text(sample_text)

    def on_save_run(self, obj):
        item = self.run_editor.item
        if not item: return
        if item.props.state == datawidget.RunItem.StateType.ADD:
            new_item = datawidget.RunItem({}, state=datawidget.RunItem.StateType.ADD)
            self.run_store.insert_sorted(new_item, datawidget.RunItem.sorter)
        info = self.run_editor.get_parameters()
        item.props.info = info
        item.props.state = datawidget.RunItem.StateType.DRAFT
        self.check_run_store()

    def on_delete_run(self, obj):
        item = self.run_editor.item
        if item.state != datawidget.RunItem.StateType.ADD:
            pos = item.position
            self.run_store.remove(item.position)
            item = self.run_store.get_item(pos)
            next_row = self.widget.datasets_list.get_row_at_index(pos)
            self.run_editor.set_item(item)
            self.editor_frame.set_row(next_row)
        self.check_run_store()

    def on_clean_runs(self, obj):
        count = 0
        item = self.run_store.get_item(count)
        while item.state in [item.StateType.COMPLETE, item.StateType.ERROR]:
            count += 1
            item = self.run_store.get_item(count)
        if count > 0:
            self.run_store.splice(0, count, [])
            self.check_run_store()

    def on_copy_run(self, obj):
        num_items = self.run_store.get_n_items()
        if num_items > 7:
            return
        new_item = datawidget.RunItem({}, state=datawidget.RunItem.StateType.DRAFT)
        new_item.props.info = self.run_editor.get_parameters()
        pos = self.run_store.insert_sorted(new_item, datawidget.RunItem.sorter)
        self.check_run_store()
        next_row = self.widget.datasets_list.get_row_at_index(pos)
        self.run_editor.set_item(new_item)
        self.editor_frame.set_row(next_row)

    def on_progress(self, obj, fraction, message):
        used_time = time.time() - self.start_time
        if fraction > 0:
            remaining_time = (1 - fraction) * used_time / fraction
            eta_time = remaining_time
            eta = '{:0>2.0f}:{:0>2.0f} ETA'.format(*divmod(eta_time, 60))
        else:
            eta = '--:--'
        self.widget.collect_eta.set_text(eta)
        self.widget.collect_pbar.set_fraction(fraction)

    def on_done(self, obj, completion):
        self.complete_run(completion)
        self.widget.collect_eta.set_text('--:--')
        self.widget.collect_pbar.set_fraction(1.0)
        self.widget.collect_progress_lbl.set_text('Acquisition complete!')

    def on_stopped(self, obj, completion):
        self.widget.collect_eta.set_text('--:--')
        self.complete_run(completion)

    def on_pause(self, obj, paused, message):
        if paused:
            self.widget.notifier.notify(message, important=True)
            self.pause_info = True
        elif message:
            self.widget.notifier.notify(message, duration=30, show_timer=True)
            self.pause_info = False

    def complete_run(self, completion):
        self.widget.datasets_collect_btn.set_sensitive(True)
        self.widget.collect_btn_icon.set_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        self.widget.datasets_clean_btn.set_sensitive(True)
        self.widget.datasets_overlay.set_sensitive(True)
        self.collecting = False
        self.stopping = False
        if self.pause_info:
            self.widget.notifier.close()

        # mark runs as complete
        completion = {} if not completion else completion
        count = 0
        item = self.run_store.get_item(count)
        changed = False
        while item:
            changed = item.set_progress(completion.get(item.uuid, 1.0))
            count += 1
            item = self.run_store.get_item(count)
        if changed:
            self.update_cache()

    def on_started(self, obj, wedge):
        if wedge is None:  # Overall start for all wedges
            self.start_time = time.time()
            self.widget.datasets_collect_btn.set_sensitive(True)
            self.widget.datasets_clean_btn.set_sensitive(False)
            self.widget.datasets_overlay.set_sensitive(False)
            logger.info("Acquisition started ...")
        else:
            logger.info("Starting wedge {} ...".format(wedge['name']))
            self.widget.dsets_dir_fbk.set_text(wedge['directory'])
            progress_text = "Acquiring frames {}-{} of '{}' ...".format(
                wedge['first'], wedge['first'] + wedge['num_frames'] - 1, wedge['name']
            )
            self.widget.collect_progress_lbl.set_text(progress_text)

            # mark progress
            count = 0
            item = self.run_store.get_item(count)
            while item:
                if item.uuid == wedge['uuid']:
                    item.props.state = item.StateType.ACTIVE
                elif item.state not in [item.StateType.COMPLETE, item.StateType.ADD]:
                    item.props.state = item.StateType.PAUSED
                count += 1
                item = self.run_store.get_item(count)

    def on_new_image(self, obj, frame):
        # ignore first frame which is the PV value when MxDC starts up, frame may belong to a different user
        if not self.first_frame:
            self.image_viewer.show_frame(frame)
        self.first_frame = False

    def on_collect_btn(self, obj):
        self.auto_save_run()
        self.widget.datasets_collect_btn.set_sensitive(False)
        if self.collecting:
            self.stopping = True
            self.widget.collect_progress_lbl.set_text("Stopping acquisition ...")
            self.collector.stop()
        else:
            runs = self.generate_run_list()
            if not runs:
                msg1 = 'Run list is empty!'
                msg2 = 'Please define and save a run before collecting.'
                dialogs.warning(msg1, msg2)
                return
            success, checked_runs, existing = self.check_runlist(runs)

            if success:
                self.collecting = True
                self.widget.collect_btn_icon.set_from_icon_name(
                    "media-playback-stop-symbolic", Gtk.IconSize.SMALL_TOOLBAR
                )
                self.widget.collect_progress_lbl.set_text("Starting acquisition ...")
                self.widget.collect_pbar.set_fraction(0)
                self.collector.configure(checked_runs, analysis='default')
                self.collector.start()
                self.image_viewer.set_collect_mode(True)
