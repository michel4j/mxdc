import copy
import time
import os
from datetime import timedelta
from enum import Enum
from gi.repository import Gio, Gtk
from zope.interface import Interface

from mxdc import Object, Signal, IBeamline, Property
from mxdc import Registry
from mxdc.conf import load_cache, save_cache
from mxdc.engines.automation import Automator
from mxdc.engines.diffraction import DataCollector
from mxdc.utils import converter, datatools, misc
from mxdc.utils.log import get_module_logger
from mxdc.widgets import datawidget, dialogs, arrowframe, status
from mxdc.widgets.datawidget import RunItem

from mxdc.widgets.imageviewer import ImageViewer, IImageViewer
from .microscope import IMicroscope
from .samplestore import ISampleStore, SampleQueue, SampleStore
from ..utils.datatools import StrategyType, Strategy, AnalysisType, calculate_skip
from ..widgets.tasks import TaskItem, TaskRow, ANALYSIS_DESCRIPTIONS

logger = get_module_logger(__name__)

(
    RESPONSE_REPLACE_ALL,
    RESPONSE_REPLACE_BAD,
    RESPONSE_SKIP,
    RESPONSE_CANCEL,
) = list(range(4))

MAX_RUNS = 10


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

    class Signals:
        directory = Signal('directory', arg_types=(str,))

    def __init__(self, widget):
        super().__init__()
        self.beamline = Registry.get_utility(IBeamline)
        self.image_viewer = Registry.get_utility(IImageViewer)

        self.widget = widget
        self.control = status.DataControl()
        self.widget.auto_datasets_box.pack_end(self.control, False, True, 0)
        self.list_box = widget.unattended_box
        self.task_list = Gio.ListStore(item_type=TaskItem)
        self.list_box.bind_model(self.task_list, TaskRow)
        self.automation_queue = SampleQueue(self.widget.auto_queue)
        self.automator = Automator()

        self.start_time = 0
        self.pause_info = None
        self.automator.connect('done', self.on_done)
        self.automator.connect('paused', self.on_pause)
        self.automator.connect('stopped', self.on_stopped)
        self.automator.connect('message', self.on_message)
        self.automator.connect('task-progress', self.on_task_progress)
        self.automator.connect('started', self.on_started)
        self.automator.connect('error', self.on_error)

        self.connect('notify::state', self.on_state_changed)
        self.setup()

    def data_defaults(self, strategy_type=StrategyType.SINGLE, **kwargs):
        info = Strategy[strategy_type]
        delta, exposure = self.beamline.config.dataset.delta, self.beamline.config.dataset.exposure
        default = {
            'delta': delta, 'exposure': exposure, 'attenuation': 0.0, 'resolution': 2.0,
            'start': 0.0, 'first': 1,
            **kwargs
        }
        rate = delta / float(exposure)
        info['delta'] = delta if 'delta' not in info else info['delta']
        info['exposure'] = info['delta'] / rate if exposure not in info else info['exposure']
        default.update(info)
        return default

    def setup_tasks(self):
        tasks = [
            TaskItem(
                name='Mount', type=TaskItem.Type.MOUNT,
                active=True, options={'skip_on_failure': True, 'pause': False, 'use_prefetch': True}
            ),
            TaskItem(
                name='Center', type=TaskItem.Type.CENTER,
                active=True, options={
                    'method': 'loop',
                    'skip_on_failure': True,
                    'pause': False,
                    'thaw_delay': 0.0,
                    'min_score': 25.0,
                }
            ),
            TaskItem(
                name='Screen', type=TaskItem.Type.SCREEN, active=True,
                options=self.data_defaults(strategy_type=StrategyType.SCREEN_3, skip_on_failure=True, pause=False)
            ),
            TaskItem(
                name='Strategy', type=TaskItem.Type.ANALYSE,
                active=True, options={
                    'method': 'strategy', 'skip_on_failure': False, 'pause': False, 'min_score': 0.4,
                    'desc': ANALYSIS_DESCRIPTIONS['strategy']
                }
            ),
            TaskItem(
                name='Acquire', type=TaskItem.Type.ACQUIRE, active=True,
                options=self.data_defaults(
                    strategy_type=StrategyType.FULL, skip_on_failure=True, pause=False, use_strategy=True,
                )
            ),
            TaskItem(
                name='Process', type=TaskItem.Type.ANALYSE,
                active=True, options={
                    'method': 'process', 'skip_on_failure': True, 'pause': False, 'min_score': 0.5,
                    'desc': ANALYSIS_DESCRIPTIONS['process']
                }
            ),
        ]
        for i, task in enumerate(tasks):
            task.props.index = i + 1
            self.task_list.append(task)
            task.connect('notify::active', self.save_to_cache)

    def setup(self):
        self.setup_tasks()
        self.load_from_cache()
        self.control.action_btn.set_sensitive(True)
        self.control.action_btn.connect('clicked', self.on_start_automation)
        self.control.stop_btn.connect('clicked', self.on_stop_automation)
        self.widget.auto_clean_btn.connect('clicked', self.on_clean_automation)
        self.widget.auto_groups_btn.set_popover(self.widget.auto_groups_pop)

    def load_from_cache(self):
        config = load_cache('automation')
        if not config:
            return

        for i, task in enumerate(self.task_list):
            if task.name not in config:
                continue
            task.set_active(config[task.name])

    def save_to_cache(self, *args, **kwargs):
        config = {task.name: task.is_active() for task in self.task_list}
        save_cache(config, 'automation')

    def get_task_options(self, task) -> dict:
        params = task.get_parameters()
        options = {**params['options']}
        if task.type in [TaskItem.Type.SCREEN, TaskItem.Type.ACQUIRE]:
            # Validate data collection parameters
            options['energy'] = self.beamline.bragg_energy.get_position()
            options['exposure'] = max(self.beamline.config.minimum_exposure, options.get('exposure', 0))
            options['distance'] = converter.resol_to_dist(
                options.get('resolution', 2), self.beamline.detector.mm_size, options['energy']
            )

            options['skip'] = datatools.calculate_skip(
                options['strategy'], options['range'], options['delta'], options.get('first', 1)
            )
            options['frames'] = datatools.calc_num_frames(
                options['strategy'], options['delta'], options['range'], skip=options['skip']
            )
            options['strategy_desc'] = options.pop('desc', '')
            params['options'] = options
        return params

    def get_task_list(self):
        return [
            self.get_task_options(task) for task in self.task_list if task.active
        ]

    def get_sample_list(self):
        return self.automation_queue.get_samples()

    def on_state_changed(self, obj, param):
        if self.props.state == self.StateType.ACTIVE:
            self.control.action_icon.set_from_icon_name(
                "media-playback-pause-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.control.stop_btn.set_sensitive(True)
            self.control.action_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        elif self.props.state == self.StateType.PAUSED:
            self.control.progress_fbk.set_text("Automation paused!")
            self.control.action_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.control.stop_btn.set_sensitive(True)
            self.control.action_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        elif self.props.state == self.StateType.PENDING:
            self.control.action_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.widget.auto_sequence_box.set_sensitive(False)
            self.control.action_btn.set_sensitive(False)
            self.control.stop_btn.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        else:
            self.control.action_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.control.stop_btn.set_sensitive(False)
            self.control.action_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(True)
            self.widget.auto_groups_btn.set_sensitive(True)

    def on_message(self, obj,message):
        self.control.progress_fbk.set_text(message)

    def on_task_progress(self, obj, fraction, uuid, code):
        self.automation_queue.set_progress(uuid, code)
        used_time = time.time() - self.start_time
        remaining_time = 0 if not fraction else int((1 - fraction) * used_time / fraction)
        eta_time = timedelta(seconds=remaining_time)
        self.control.eta_fbk.set_markup(f'<small><tt>{eta_time}</tt></small>')
        self.control.progress_bar.set_fraction(fraction)

    def on_done(self, obj, data):
        self.props.state = self.StateType.STOPPED
        eta_time = timedelta(seconds=0)
        self.control.progress_fbk.set_text("Automation Completed.")
        self.control.eta_fbk.set_markup(f'<small><tt>{eta_time}</tt></small>')
        self.control.progress_bar.set_fraction(1.0)

    def on_stopped(self, obj, data):
        self.props.state = self.StateType.STOPPED
        self.control.progress_fbk.set_text("Automation Stopped.")

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
        logger.warning("Automation Started.")

    def on_stop_automation(self, obj):
        self.automator.stop()

    def on_clean_automation(self, obj):
        self.automation_queue.clean()

    def on_start_automation(self, obj):
        if self.props.state == self.StateType.ACTIVE:
            self.control.progress_fbk.set_text("Pausing automation ...")
            self.automator.pause()
        elif self.props.state == self.StateType.PAUSED:
            self.control.progress_fbk.set_text("Resuming automation ...")
            self.automator.resume()
        elif self.props.state == self.StateType.STOPPED:
            tasks = self.get_task_list()
            samples = self.get_sample_list()
            if not samples:
                msg1 = 'Queue is empty!'
                msg2 = 'Please add samples and try again.'
                dialogs.warning(msg1, msg2)
            else:
                self.control.progress_fbk.set_text("Starting automation ...")
                self.props.state = self.StateType.PENDING
                self.automator.configure(samples, tasks)
                self.control.progress_bar.set_fraction(0)
                self.automator.start()
                self.image_viewer.set_collect_mode(True)


class DatasetsController(Object):
    class Signals:
        changed = Signal('samples-changed', arg_types=(object,))
        active = Signal('active-sample', arg_types=(object,))
        selected = Signal('sample-selected', arg_types=(object,))
        directory = Signal('directory', arg_types=(str,))

    class StateType(Enum):
        STARTING, ACTIVE, STOPPING, STOPPED = range(4)

    state = Property(type=object)

    def __init__(self, widget):
        super().__init__()
        self.pause_info = False
        self.start_time = 0
        self.frame_monitor = None
        self.starting = True
        self.widget = widget

        self.beamline = Registry.get_utility(IBeamline)
        self.collector = DataCollector()
        self.names = datatools.NameManager()
        self.image_viewer = ImageViewer()
        self.microscope = Registry.get_utility(IMicroscope)
        self.sample_store = Registry.get_utility(ISampleStore)

        self.control = status.DataControl()
        self.widget.manual_datasets_box.pack_end(self.control, False, True, 0)

        self.run_editor = datawidget.RunEditor(points_model=self.microscope.points)
        self.editor_frame = arrowframe.ArrowFrame()
        self.editor_frame.add(self.run_editor.data_form)
        self.widget.datasets_overlay.add_overlay(self.editor_frame)
        self.run_store = Gio.ListStore(item_type=RunItem)
        self.run_sg = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        self.state_values = {
            self.StateType.STARTING: (False, False),
            self.StateType.ACTIVE: (False, True),
            self.StateType.STOPPING: (False, False),
            self.StateType.STOPPED: (True, False)
        }
        self.setup()
        Registry.add_utility(IDatasets, self)

    def setup(self):
        self.run_store.connect('items-changed', self.on_runs_changed)
        self.collector.connect('done', self.on_done)
        self.collector.connect('paused', self.on_pause)
        self.collector.connect('stopped', self.on_stopped)
        self.collector.connect('progress', self.on_progress)
        self.collector.connect('started', self.on_started)
        self.connect('notify::state', self.on_state_changed)

        self.widget.datasets_list.bind_model(self.run_store, self.create_run_config)
        self.widget.datasets_viewer_box.add(self.image_viewer)
        self.widget.datasets_clean_btn.connect('clicked', self.on_clean_runs)
        self.widget.datasets_list.connect('row-activated', self.on_row_activated)

        self.run_editor.data_delete_btn.connect('clicked', self.on_delete_run)
        self.run_editor.data_copy_btn.connect('clicked', self.on_copy_run)
        self.run_editor.data_recycle_btn.connect('clicked', self.on_recycle_run)
        self.run_editor.data_save_btn.connect('clicked', self.on_save_run)
        self.sample_store.connect('updated', self.on_sample_updated)

        self.import_from_cache()

        new_item = RunItem(state=RunItem.StateType.ADD)
        pos = self.run_store.insert_sorted(new_item, RunItem.sorter)
        self.run_editor.set_item(new_item)
        first_row = self.widget.datasets_list.get_row_at_index(pos)
        self.editor_frame.set_row(first_row)

        self.control.action_btn.connect('clicked', self.on_start)
        self.control.stop_btn.connect('clicked', self.on_stop)

        self.frame_monitor = self.beamline.detector.connect('new-image', self.on_new_image)
        self.props.state = self.StateType.STOPPED

    def import_from_cache(self):
        runs = load_cache('runs')
        names = load_cache('names')
        names = {} if not names else names
        if runs:
            for run in runs:
                new_item = RunItem(
                    run['info'], state=run['state'], created=run['created'], uid=run['uuid']
                )
                self.run_store.insert_sorted(new_item, RunItem.sorter)
            self.control.action_btn.set_sensitive(True)
        self.names.set_database(names)

    def update_positions(self):
        pos = 0
        item = self.run_store.get_item(pos)
        while item:
            item.props.position = pos
            pos += 1
            item = self.run_store.get_item(pos)

    def create_run_config(self, item):
        config = datawidget.RunConfig()
        self.run_sg.add_widget(config.data_title_box)
        config.set_item(item)
        return config.get_widget()

    def auto_save_run(self):
        item = self.run_editor.item
        # auto save current parameters
        if item and item.props.state not in [RunItem.StateType.ADD, RunItem.StateType.COMPLETE]:
            info = self.run_editor.get_parameters()
            item.props.info = info
            item.props.state = RunItem.StateType.DRAFT
            self.check_run_store()

    def add_new_run(self, config):
        sample = self.sample_store.get_current()
        name = sample.get('name', 'test')
        config['name'] = self.names.get(name)

        item = RunItem({}, state=RunItem.StateType.DRAFT)
        item.props.info = config
        self.run_store.insert_sorted(item, RunItem.sorter)
        self.check_run_store()

        next_row = self.widget.datasets_list.get_row_at_index(item.position)
        self.editor_frame.set_row(next_row)
        self.run_editor.set_item(item)

    def on_row_activated(self, list, row):
        self.auto_save_run()
        self.editor_frame.set_row(row)
        position = row.get_index()
        item = self.run_store.get_item(position)

        num_items = self.run_store.get_n_items()
        if item.state == item.StateType.ADD and num_items < MAX_RUNS:
            energy = self.beamline.bragg_energy.get_position()
            distance = self.beamline.distance.get_position()
            start_angle = self.beamline.goniometer.omega.get_position()
            resolution = converter.dist_to_resol(
                distance, self.beamline.detector.mm_size, energy
            )
            attenuation = self.beamline.attenuator.get_position()

            if num_items >= 2:
                prev = self.run_store.get_item(num_items - 2)
                config = prev.info.copy()
            else:
                config = self.run_editor.get_default(datawidget.StrategyType.FULL)
                config.update({
                    'resolution': round(resolution, 4),
                    'strategy': datawidget.StrategyType.FULL,
                    'energy': energy,
                    'attenuation': attenuation,
                    'distance': distance,
                })
            config.update({
                'energy': energy,
                'attenuation': attenuation,
                'start': start_angle,
            })
            self.add_new_run(config)
        else:
            self.run_editor.set_item(item)

    def on_runs_changed(self, model, position, removed, added):
        self.update_positions()
        if self.run_store.get_n_items() < 2:
            self.control.action_btn.set_sensitive(False)

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
                    if run.get(name):
                        run[name] = self.run_editor.get_point(run[name])
                    elif name in run:
                        del run[name]
                if 'p1' in run and 'p0' not in run:
                    run['p0'] = run.pop('p1')

                run = datatools.update_for_sample(run, sample=sample, session=self.beamline.session_key)
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
        editable_states = (RunItem.StateType.DRAFT, RunItem.StateType.ACTIVE)
        draft_names = [item.info['name'] for item in self.run_store if item.state in editable_states]
        root = self.sample_store.get_current().get('name', 'test')
        new_names = self.names.fix(root, *draft_names)
        count = 0
        for i, item in enumerate(self.run_store):
            if item.props.state in editable_states:
                count += 1
                info = item.info.copy()
                info['name'] = new_names.pop(0)
                item.props.info = info
                item.props.position = i

        self.update_cache()
        self.control.action_btn.set_sensitive(count > 0)

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
        save_cache(self.names.get_database(), 'names')

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
            if 'exposure' in run and 'delta' in run:
                info.update(exposure=run['exposure'], delta=run['delta'])
            new_item = RunItem({}, state=RunItem.StateType.DRAFT)
            new_item.props.info = info
            self.run_store.insert_sorted(new_item, RunItem.sorter)
        self.check_run_store()

    def on_state_changed(self, obj, param):
        action_state, stop_state = self.state_values.get(self.props.state, (False, False))
        self.control.stop_btn.set_sensitive(stop_state)
        self.control.action_btn.set_sensitive(action_state)
        if self.props.state == self.StateType.STOPPED:
            self.widget.datasets_clean_btn.set_sensitive(True)
            self.widget.datasets_overlay.set_sensitive(True)
        else:
            self.widget.datasets_clean_btn.set_sensitive(False)
            self.widget.datasets_overlay.set_sensitive(False)

        if self.props.state == self.StateType.STARTING:
            self.control.progress_fbk.set_text("Starting acquisition ...")
        elif self.props.state == self.StateType.STOPPING:
            self.control.progress_fbk.set_text("Stopping acquisition ...")

    def on_sample_updated(self, obj):
        sample = self.sample_store.get_current()
        self.remove_runs()

        config = self.run_editor.get_default(datawidget.StrategyType.SCREEN_2)
        energy = self.beamline.bragg_energy.get_position()
        distance = self.beamline.distance.get_position()
        resolution = converter.dist_to_resol(
            distance, self.beamline.detector.mm_size, energy
        )
        attenuation = self.beamline.attenuator.get_position()
        config.update({
            'resolution': round(resolution, 4),
            'strategy': datawidget.StrategyType.SCREEN_2,
            'energy': energy,
            'attenuation': attenuation,
            'distance': distance,
        })
        self.add_new_run(config)

    def on_save_run(self, obj):
        item = self.run_editor.item
        if not item: return
        if item.props.state == RunItem.StateType.ADD:
            new_item = RunItem({}, state=RunItem.StateType.ADD)
            self.run_store.insert_sorted(new_item, RunItem.sorter)
        info = self.run_editor.get_parameters()
        item.props.info = info
        item.props.state = RunItem.StateType.DRAFT
        self.check_run_store()

    def on_delete_run(self, obj):
        item = self.run_editor.item
        if item.state != RunItem.StateType.ADD:
            pos = item.position
            self.run_store.remove(item.position)
            item = self.run_store.get_item(pos)
            if item.state == RunItem.StateType.ADD and pos > 0:
                pos -= 1
                item = self.run_store.get_item(pos)
            next_row = self.widget.datasets_list.get_row_at_index(pos)
            self.run_editor.set_item(item)
            self.editor_frame.set_row(next_row)
        self.check_run_store()

    def on_clean_runs(self, obj):
        self.remove_runs(RunItem.StateType.COMPLETE, RunItem.StateType.ERROR)
        self.check_run_store()

    def remove_runs(self, *states, keep=(), force=False):
        all_states = (
            RunItem.StateType.DRAFT,
            RunItem.StateType.ACTIVE,
            RunItem.StateType.PAUSED,
            RunItem.StateType.ERROR,
            RunItem.StateType.COMPLETE
        )
        states = states if states else all_states

        i = 0
        item = self.run_store[i]
        while item.state != RunItem.StateType.ADD:
            if item.state in states and not (item.state in keep or item.pinned):
                self.run_store.remove(i)
                item = self.run_store[i]
            else:
                i += 1
                if i == self.run_store.get_n_items():
                    break
                else:
                    item = self.run_store[i]
        self.check_run_store()

    def on_copy_run(self, obj):
        num_items = self.run_store.get_n_items()
        if num_items > 7:
            return
        new_item = RunItem({}, state=RunItem.StateType.DRAFT)
        new_item.props.info = self.run_editor.get_parameters()
        pos = self.run_store.insert_sorted(new_item, RunItem.sorter)
        self.check_run_store()
        next_row = self.widget.datasets_list.get_row_at_index(pos)
        self.run_editor.set_item(new_item)
        self.editor_frame.set_row(next_row)

    def on_recycle_run(self, obj):
        item = self.run_editor.item
        if item.state != RunItem.StateType.ADD:
            info = item.info.copy()

            sample = self.sample_store.get_current()
            root = sample.get('name', 'test')

            energy = self.beamline.energy.get_position()
            start_angle = self.beamline.goniometer.omega.get_position()
            info.update({
                'energy': energy,
                'start': start_angle,
                'name': self.names.get(root),
                'notes': ''
            })
            item.state = RunItem.StateType.DRAFT
            item.props.info = info
        self.auto_save_run()
        self.check_run_store()

    def on_progress(self, obj, fraction, message):
        used_time = time.time() - self.start_time
        if fraction > 0:
            remaining_time = int((1 - fraction) * used_time / fraction)
            eta_time = timedelta(seconds=remaining_time)
        else:
            eta_time = timedelta(seconds=0)
        self.control.eta_fbk.set_markup(f'<small><tt>{eta_time}</tt></small>')
        self.control.progress_bar.set_fraction(fraction)

    def on_done(self, obj, completion):
        self.complete_run(completion)
        eta_time = timedelta(seconds=0)
        self.control.eta_fbk.set_markup(f'<small><tt>{eta_time}</tt></small>')
        self.control.progress_bar.set_fraction(1.0)
        self.control.progress_fbk.set_text('Acquisition complete!')

    def on_stopped(self, obj, completion):
        self.complete_run(completion)

    def on_pause(self, obj, paused, message):
        if paused:
            self.widget.notifier.notify(message, important=True)
            self.pause_info = True
        elif message:
            self.widget.notifier.notify(message, duration=30, show_timer=True)
            self.pause_info = False

    def complete_run(self, completion=None):
        self.image_viewer.set_collect_mode(False)
        self.props.state = self.StateType.STOPPED
        if self.pause_info:
            self.widget.notifier.close()

        # mark runs as complete
        completion = {} if not completion else completion
        sample = self.sample_store.get_current()
        root = sample.get('name', 'test')

        for item in self.run_store:
            if item.state != RunItem.StateType.ADD:
                item.set_progress(completion.get(item.uuid, 1.0))
                if completion.get(item.uuid, 1.0) > 0.0:
                    self.names.update(root, item.info['name'])
        self.update_cache()

    def on_started(self, obj, wedge):
        if wedge is None:  # Overall start for all wedges
            self.start_time = time.time()
            self.props.state = self.StateType.ACTIVE
            logger.info("Acquisition started ...")
        else:
            logger.info("Starting wedge {} ...".format(wedge['name']))
            self.set_state(directory=wedge['directory'])

            progress_text = "Acquiring from {:g}-{:g}° for '{}' ...".format(
                wedge['start'], wedge['start'] + wedge['num_frames'] * wedge['delta'], wedge['name']
            )
            self.control.progress_fbk.set_text(progress_text)

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
        if not self.starting:
            self.image_viewer.show_frame(frame)
        self.starting = False

    def on_stop(self, btn):
        if self.props.state not in [self.StateType.STOPPING, self.StateType.STOPPED]:
            self.props.state = self.StateType.STOPPING
            self.collector.stop()

    def on_start(self, obj):
        self.auto_save_run()
        runs = self.generate_run_list()
        if not runs:
            msg1 = 'Run list is empty!'
            msg2 = 'Please define and save a run before collecting.'
            dialogs.warning(msg1, msg2)
            return
        success, checked_runs, existing = self.check_runlist(runs)

        if success and self.props.state != self.StateType.STARTING:
            self.props.state = self.StateType.STARTING
            self.control.progress_bar.set_fraction(0)
            self.collector.configure(checked_runs, analysis='default')
            self.collector.start()
            self.image_viewer.set_collect_mode(True)


