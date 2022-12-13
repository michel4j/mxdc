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

    def __init__(self, widget):
        super().__init__()
        self.beamline = Registry.get_utility(IBeamline)
        self.image_viewer = Registry.get_utility(IImageViewer)

        self.widget = widget
        self.status = status.DataStatus()
        self.status_controller = common.DataStatusController(self.beamline, self.status)
        self.widget.auto_datasets_box.pack_end(self.status, False, True, 0)
        self.run_dialog = datawidget.DataDialog()

        self.widget.auto_edit_acq_btn.set_popover(self.run_dialog.popover)
        self.automation_queue = SampleQueue(self.widget.auto_queue)
        self.automator = Automator()

        self.config = RunItem()
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
            'diffraction': self.widget.center_diff_option,
            'screen': self.widget.analyse_screen_option,
            'process': self.widget.analyse_process_option,
            'anomalous': self.widget.analyse_anom_option,
            'powder': self.widget.analyse_powder_option,
            'analyse': self.widget.analyse_task_btn
        }
        self.setup()

    def setup(self):
        self.import_from_cache()
        self.widget.auto_edit_acq_btn.connect('clicked', self.on_edit_acquisition)
        self.run_dialog.data_save_btn.connect('clicked', self.on_save_acquisition)
        self.status.action_btn.set_sensitive(True)

        for btn in list(self.tasks.values()):
            btn.connect('toggled', self.on_save_acquisition)

        self.status.action_btn.connect('clicked', self.on_start_automation)
        self.status.stop_btn.connect('clicked', self.on_stop_automation)

        self.widget.auto_clean_btn.connect('clicked', self.on_clean_automation)
        self.widget.auto_groups_btn.set_popover(self.widget.auto_groups_pop)
        self.widget.center_task_btn.bind_property('active', self.widget.center_options_box, 'sensitive')
        self.widget.analyse_task_btn.bind_property('active', self.widget.analyse_options_box, 'sensitive')
        self.widget.acquire_task_btn.bind_property('active', self.widget.acquire_options_box, 'sensitive')

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
            for name in ['loop', 'crystal', 'diffraction', 'capillary']:
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
            self.status.action_icon.set_from_icon_name(
                "media-playback-pause-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.status.stop_btn.set_sensitive(True)
            self.status.action_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        elif self.props.state == self.StateType.PAUSED:
            self.status.progress_fbk.set_text("Automation paused!")
            self.status.action_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.status.stop_btn.set_sensitive(True)
            self.status.action_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        elif self.props.state == self.StateType.PENDING:
            self.status.action_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.widget.auto_sequence_box.set_sensitive(False)
            self.status.action_btn.set_sensitive(False)
            self.status.stop_btn.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        else:
            self.status.action_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.SMALL_TOOLBAR
            )
            self.status.stop_btn.set_sensitive(False)
            self.status.action_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(True)
            self.widget.auto_groups_btn.set_sensitive(True)

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
        remaining_time = 0 if not fraction else int((1 - fraction) * used_time / fraction)
        eta_time = timedelta(seconds=remaining_time)
        self.status.eta_fbk.set_markup(f'<small><tt>{eta_time}</tt></small>')
        self.status.progress_bar.set_fraction(fraction)
        self.status.progress_fbk.set_text(message)

    def on_sample_done(self, obj, uuid):
        self.automation_queue.mark_progress(uuid, SampleStore.Progress.DONE)

    def on_sample_started(self, obj, uuid):
        self.automation_queue.mark_progress(uuid, SampleStore.Progress.ACTIVE)

    def on_done(self, obj, data):
        self.props.state = self.StateType.STOPPED
        eta_time = timedelta(seconds=0)
        self.status.progress_fbk.set_text("Automation Completed.")
        self.status.eta_fbk.set_markup(f'<small><tt>{eta_time}</tt></small>')
        self.status.progress_bar.set_fraction(1.0)

    def on_stopped(self, obj, data):
        self.props.state = self.StateType.STOPPED
        self.status.progress_fbk.set_text("Automation Stopped.")

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
            self.status.progress_fbk.set_text("Pausing automation ...")
            self.automator.pause()
        elif self.props.state == self.StateType.PAUSED:
            self.status.progress_fbk.set_text("Resuming automation ...")
            self.automator.resume()
        elif self.props.state == self.StateType.STOPPED:
            tasks = self.get_task_list()
            samples = self.get_sample_list()
            if not samples:
                msg1 = 'Queue is empty!'
                msg2 = 'Please add samples and try again.'
                dialogs.warning(msg1, msg2)
            else:
                self.status.progress_fbk.set_text("Starting automation ...")
                self.props.state = self.StateType.PENDING
                self.automator.configure(samples, tasks)
                self.status.progress_bar.set_fraction(0)
                self.automator.start()
                self.image_viewer.set_collect_mode(True)


class DatasetsController(Object):
    class Signals:
        changed = Signal('samples-changed', arg_types=(object,))
        active = Signal('active-sample', arg_types=(object,))
        selected = Signal('sample-selected', arg_types=(object,))

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

        self.status = status.DataStatus()
        self.status_controller = common.DataStatusController(self.beamline, self.status)
        self.widget.manual_datasets_box.pack_end(self.status, False, True, 0)

        self.run_editor = datawidget.RunEditor(points_model=self.microscope.points)
        self.editor_frame = arrowframe.ArrowFrame()
        self.editor_frame.add(self.run_editor.data_form)
        self.widget.datasets_overlay.add_overlay(self.editor_frame)
        self.run_store = Gio.ListStore(item_type=RunItem)
        self.run_sg = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        self.state_values =         {
            self.StateType.STARTING: (False, False),
            self.StateType.ACTIVE: (False, True),
            self.StateType.STOPPING: (False, False),
            self.StateType.STOPPED: (True, False)
        }
        self.setup()
        Registry.add_utility(IDatasets, self)

    def setup(self):
        #self.status.action_btn.set_sensitive(False)
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

        self.status.action_btn.connect('clicked', self.on_start)
        self.status.stop_btn.connect('clicked', self.on_stop)

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
            self.status.action_btn.set_sensitive(True)
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
            })
            self.add_new_run(config)
        else:
            self.run_editor.set_item(item)

    def on_runs_changed(self, model, position, removed, added):
        self.update_positions()
        if self.run_store.get_n_items() < 2:
            self.status.action_btn.set_sensitive(False)

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
        self.status.action_btn.set_sensitive(count > 0)

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
            new_item = RunItem({}, state=RunItem.StateType.DRAFT)
            new_item.props.info = info
            self.run_store.insert_sorted(new_item, RunItem.sorter)
        self.check_run_store()

    def on_state_changed(self, obj, param):
        action_state, stop_state = self.state_values.get(self.props.state, (False, False))
        self.status.stop_btn.set_sensitive(stop_state)
        self.status.action_btn.set_sensitive(action_state)
        if self.props.state == self.StateType.STOPPED:
            self.widget.datasets_clean_btn.set_sensitive(True)
            self.widget.datasets_overlay.set_sensitive(True)
        else:
            self.widget.datasets_clean_btn.set_sensitive(False)
            self.widget.datasets_overlay.set_sensitive(False)

        if self.props.state == self.StateType.STARTING:
            self.status.progress_fbk.set_text("Starting acquisition ...")
        elif self.props.state == self.StateType.STOPPING:
            self.status.progress_fbk.set_text("Stopping acquisition ...")

    def on_sample_updated(self, obj):
        sample = self.sample_store.get_current()
        sample_text = '{name}|{port}'.format(
            name=sample.get('name', '...'),
            port=sample.get('port', '...')
        ).replace('|...', '')
        self.status.sample_fbk.set_text(sample_text)
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
            info.update({
                'energy': energy,
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
        self.status.eta_fbk.set_markup(f'<small><tt>{eta_time}</tt></small>')
        self.status.progress_bar.set_fraction(fraction)

    def on_done(self, obj, completion):
        self.complete_run(completion)
        eta_time = timedelta(seconds=0)
        self.status.eta_fbk.set_markup(f'<small><tt>{eta_time}</tt></small>')
        self.status.progress_bar.set_fraction(1.0)
        self.status.progress_fbk.set_text('Acquisition complete!')

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
            self.status_controller.set_directory(wedge['directory'])

            progress_text = "Acquiring from {:g}-{:g}° for '{}' ...".format(
                wedge['start'], wedge['start'] + wedge['num_frames'] * wedge['delta'], wedge['name']
            )
            self.status.progress_fbk.set_text(progress_text)

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
            self.status.progress_bar.set_fraction(0)
            self.collector.configure(checked_runs, analysis='default')
            self.collector.start()
            self.image_viewer.set_collect_mode(True)
