import copy
import os
import time

import common
from gi.repository import GObject, Gio, Gtk
from mxdc.beamline.mx import IBeamline
from mxdc.engines.diffraction import DataCollector
from mxdc.engines.automation import Automator
from mxdc.utils import converter, datatools, misc
from mxdc.utils.log import get_module_logger
from mxdc.widgets import datawidget, dialogs, arrowframe
from mxdc.widgets.imageviewer import ImageViewer, IImageViewer
from samplestore import ISampleStore, SampleQueue, SampleStore
from microscope import IMicroscope
from zope.interface import Interface, implements
from twisted.python.components import globalRegistry

logger = get_module_logger(__name__)

(
    RESPONSE_REPLACE_ALL,
    RESPONSE_REPLACE_BAD,
    RESPONSE_SKIP,
    RESPONSE_CANCEL,
) = range(4)



class IDatasets(Interface):
    """Sample information database."""
    pass


class ConfigDisplay(object):
    Formats = {
        'resolution': '{:0.2f}',
        'delta': '{:0.2f} deg',
        'range': '{:0.1f} deg',
        'start': '{:0.1f} deg',
        'wedge': '{:0.1f} deg',
        'energy': '{:0.3f} keV',
        'distance': '{:0.1f} mm',
        'exposure': '{:0.3f} s',
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
        item.connect('notify::info', self.on_item_changed)

    def on_item_changed(self, item, param):
        for name, format in self.Formats.items():
            field_name = '{}_{}_lbl'.format(self.prefix, name, name)
            field = getattr(self.widget, field_name, None)
            if field and name in self.item.props.info:
                field.set_text(format.format(self.item.props.info[name]))


class AutomationController(GObject.GObject):
    class StateType:
        STOPPED, PAUSED, ACTIVE, PENDING = range(4)

    state = GObject.Property(type=int, default=0)

    def __init__(self, widget):
        super(AutomationController, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.image_viewer = globalRegistry.lookup([], IImageViewer)
        self.run_dialog = datawidget.DataDialog()
        self.run_dialog.window.set_transient_for(dialogs.MAIN_WINDOW)
        self.automation_queue = SampleQueue(self.widget.auto_queue)
        self.automator = Automator()
        self.config = datawidget.RunItem()
        self.config_display = ConfigDisplay(self.config, self.widget, 'auto')

        self.start_time = 0
        self.pause_dialog = None
        self.automator.connect('done', self.on_done)
        self.automator.connect('paused', self.on_pause)
        self.automator.connect('analysis-request', self.on_analysis)
        self.automator.connect('stopped', self.on_stopped)
        self.automator.connect('progress', self.on_progress)
        self.automator.connect('sample-done', self.on_sample_done)
        self.automator.connect('sample-started', self.on_sample_started)
        self.automator.connect('started', self.on_started)
        self.automator.connect('error', self.on_error)

        self.connect('notify::state', self.on_state_changed)

        # default
        params = datawidget.DataDialog.get_default(
            strategy_type=datawidget.StrategyType.SINGLE, delta=self.beamline.config['default_delta']
        )
        params.update({
            'resolution': converter.dist_to_resol(
                250, self.beamline.detector.mm_size, self.beamline.energy.get_position()
            ),
            'exposure': self.beamline.config['default_exposure'],
        })
        self.run_dialog.configure(params)
        self.config.props.info = self.run_dialog.get_parameters()

        # btn, type, options method
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
            'crystal': self.widget.center_xtal_option,
            'screen': self.widget.analyse_screen_option,
            'native': self.widget.analyse_native_option,
            'anomalous': self.widget.analyse_anom_option,
            'powder': self.widget.analyse_powder_option,
            'analyse': self.widget.analyse_task_btn
        }
        self.setup()

    def get_options(self, task_type):
        if task_type == Automator.Task.CENTER:
            for name in ['loop', 'crystal', 'raster', 'capillary']:
                if self.options[name].get_active():
                    return {'method': name}
        elif task_type == Automator.Task.ACQUIRE:
            options = {}
            if self.options['analyse'].get_active():
                for name in ['screen', 'native', 'anomalous', 'powder']:
                    if self.options[name].get_active():
                        options = {'analysis': name}
                        break
            options.update(self.config.props.info)
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
                "media-playback-pause-symbolic", Gtk.IconSize.LARGE_TOOLBAR
            )
            self.widget.auto_stop_btn.set_sensitive(True)
            self.widget.auto_collect_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        elif self.props.state == self.StateType.PAUSED:
            self.widget.auto_progress_lbl.set_text("Automation paused!")
            self.widget.auto_collect_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR
            )
            self.widget.auto_stop_btn.set_sensitive(True)
            self.widget.auto_collect_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        elif self.props.state == self.StateType.PENDING:
            self.widget.auto_collect_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR
            )
            self.widget.auto_sequence_box.set_sensitive(False)
            self.widget.auto_collect_btn.set_sensitive(False)
            self.widget.auto_stop_btn.set_sensitive(False)
            self.widget.auto_groups_btn.set_sensitive(False)
        else:
            self.widget.auto_collect_icon.set_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR
            )
            self.widget.auto_stop_btn.set_sensitive(False)
            self.widget.auto_collect_btn.set_sensitive(True)
            self.widget.auto_sequence_box.set_sensitive(True)
            self.widget.auto_groups_btn.set_sensitive(True)

    def setup(self):
        self.widget.auto_edit_acq_btn.connect('clicked', self.on_edit_acquisition)
        self.run_dialog.data_cancel_btn.connect('clicked', lambda x: self.run_dialog.window.hide())
        self.run_dialog.data_save_btn.connect('clicked', self.on_save_acquisition)
        self.widget.auto_collect_btn.connect('clicked', self.on_start_automation)
        self.widget.auto_stop_btn.connect('clicked', self.on_stop_automation)
        self.widget.auto_clean_btn.connect('clicked', self.on_clean_automation)
        self.widget.auto_groups_btn.set_popover(self.widget.auto_groups_pop)

    def on_edit_acquisition(self, obj):
        self.run_dialog.configure(self.config.info)
        self.run_dialog.window.show_all()

    def on_save_acquisition(self, obj):
        self.config.props.info = self.run_dialog.get_parameters()
        self.run_dialog.window.hide()

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

    def on_done(self, obj=None):
        self.props.state = self.StateType.STOPPED
        self.widget.auto_progress_lbl.set_text("Automation Completed.")
        self.widget.auto_eta.set_text('--:--')
        self.widget.auto_pbar.set_fraction(1.0)

    def on_stopped(self, obj=None):
        self.props.state = self.StateType.STOPPED
        self.widget.auto_progress_lbl.set_text("Automation Stopped.")
        self.widget.auto_eta.set_text('--:--')

    def on_pause(self, obj, paused, reason):
        if paused:
            self.props.state = self.StateType.PAUSED
            if reason:
                # Build the dialog message
                self.pause_dialog = dialogs.make_dialog(
                    Gtk.MessageType.WARNING, 'Automation Paused', reason,
                    buttons=(('OK', Gtk.ResponseType.OK),)
                )
                response = self.pause_dialog.run()
                self.pause_dialog.destroy()
                self.pause_dialog = None
        else:
            self.props.state = self.StateType.ACTIVE
            if self.pause_dialog:
                self.pause_dialog.destroy()
                self.pause_dialog = None

    def on_error(self, obj, reason):
        # Build the dialog message
        error_dialog = dialogs.make_dialog(
            Gtk.MessageType.WARNING, 'Automation Error!', reason,
            buttons=(('OK', Gtk.ResponseType.OK),)
        )
        error_dialog.run()
        error_dialog.destroy()

    def on_analysis(self, obj, params):
        pass

    def on_started(self, obj):
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
                msg2 = 'Please select samples on the Samples page.'
                dialogs.warning(msg1, msg2)
            else:
                self.widget.auto_progress_lbl.set_text("Starting automation ...")
                self.props.state = self.StateType.PENDING
                self.automator.configure(samples, tasks)
                self.widget.auto_pbar.set_fraction(0)
                self.automator.start()
                self.image_viewer.set_collect_mode(True)


class DatasetsController(GObject.GObject):
    __gsignals__ = {
        'samples-changed': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'active-sample': (GObject.SignalFlags.RUN_LAST, None, [object, ]),
        'sample-selected': (GObject.SignalFlags.RUN_LAST, None, [object, ]),
    }

    def __init__(self, widget):
        super(DatasetsController, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.collector = DataCollector()
        self.collecting = False
        self.stopping = False
        self.monitors = {}
        self.frame_manager = {}
        self.image_viewer = ImageViewer()
        self.microscope = globalRegistry.lookup([], IMicroscope)
        self.run_editor = datawidget.RunEditor()
        self.editor_frame = arrowframe.ArrowFrame()
        self.editor_frame.add(self.run_editor.data_form)
        self.editor_frame.set_size_request(300, -1)
        self.widget.datasets_overlay.add_overlay(self.editor_frame)
        self.run_store = Gio.ListStore(item_type=datawidget.RunItem)
        self.run_store.connect('items-changed', self.on_runs_changed)

        self.collector.connect('done', self.on_done)
        self.collector.connect('paused', self.on_pause)
        self.collector.connect('new-image', self.on_new_image)
        self.collector.connect('stopped', self.on_stopped)
        self.collector.connect('progress', self.on_progress)
        self.collector.connect('started', self.on_started)
        self.microscope.connect('notify::points', self.on_points)
        globalRegistry.register([], IDatasets, '', self)
        self.setup()

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
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        self.sample_store.connect('updated', self.on_sample_updated)

        new_item = datawidget.RunItem(state=datawidget.RunItem.StateType.ADD)
        pos = self.run_store.insert_sorted(new_item, datawidget.RunItem.sorter)
        self.run_editor.set_item(new_item)
        first_row = self.widget.datasets_list.get_row_at_index(pos)
        self.editor_frame.set_row(first_row)

        labels = {
            'omega': (self.beamline.omega, self.widget.dsets_omega_fbk, '{:0.1f} deg'),
            'energy': (self.beamline.energy, self.widget.dsets_energy_fbk, '{:0.3f} keV'),
            'attenuation': (self.beamline.attenuator, self.widget.dsets_attenuation_fbk, '{:0.0f} %'),
            'maxres': (self.beamline.maxres, self.widget.dsets_maxres_fbk, '{:0.2f} A'),
            'aperture': (self.beamline.aperture, self.widget.dsets_aperture_fbk, '{:0.0f} \xc2\xb5m'),
            'two_theta': (self.beamline.two_theta, self.widget.dsets_2theta_fbk, '{:0.0f} deg'),
        }
        self.group_selectors = []
        self.monitors = {
            name: common.DeviceMonitor(dev, lbl, fmt)
            for name, (dev, lbl, fmt) in labels.items()
        }
        self.widget.datasets_collect_btn.connect('clicked', self.on_collect_btn)

    def create_run_config(self, item):
        config = datawidget.RunConfig()
        config.set_item(item)
        return config.get_widget()

    def on_row_activated(self, list, row):
        position = row.get_index()
        item = self.run_store.get_item(position)
        if position > 8:
            return
        self.editor_frame.set_row(row)
        if item.state == item.StateType.ADD:
            sample = self.sample_store.get_current()
            energy = self.beamline.bragg_energy.get_position()
            distance = self.beamline.distance.get_position()
            resolution = converter.dist_to_resol(
                distance, self.beamline.detector.mm_size, energy
            )
            config = datawidget.DataDialog.get_default()
            config.update({
                'resolution': round(resolution,1),
                'strategy': datawidget.StrategyType.SINGLE,
                'energy': energy,
                'distance': round(distance,1),
                'exposure': self.beamline.config['default_exposure'],
                'name': sample.get('name', 'test'),
            })
            item.props.info = config
            item.props.position = position  # make sure position is up to date for removal
            item.props.state = datawidget.RunItem.StateType.DRAFT
            new_item = datawidget.RunItem({}, state=datawidget.RunItem.StateType.ADD)
            self.run_store.insert_sorted(new_item, datawidget.RunItem.sorter)
        self.run_editor.set_item(item)
        self.check_run_store()

    def on_runs_changed(self, model, position, removed, added):
        self.update_positions()
        if self.run_store.get_n_items() < 2:
            self.widget.datasets_collect_btn.set_sensitive(False)

    def on_points(self, *args, **kwargs):
        if self.microscope.props.points:
            self.run_editor.add_point(
                'P{}'.format(len(self.microscope.props.points)), self.microscope.props.points[-1]
            )
        else:
            self.run_editor.clear_points()

    def generate_run_list(self):
        runs = []
        self.frame_manager = {}  # initialize frame manager
        pos = 0
        item = self.run_store.get_item(pos)
        sample = self.sample_store.get_current()
        while item:
            if item.state in [item.StateType.DRAFT, item.StateType.ACTIVE]:
                run = {'uuid': item.uuid}
                run.update(item.info)
                run = datatools.update_for_sample(run, sample)
                runs.append(run)
                self.frame_manager.update({
                    frame: item for frame in item.frames
                })
                # strip labels from prepare points to have just coordinates
                for key in ['point', 'end_point']:
                    point_info = run.pop(key, None)
                    if point_info:
                        run[key] = point_info[1]
                item.collected = set()
            pos += 1
            item = self.run_store.get_item(pos)
        return runs

    def check_runlist(self, runs):
        frame_list = datatools.generate_run_list(runs)
        existing, bad = datatools.check_frame_list(
            frame_list, self.beamline.detector.file_extension, detect_bad=False
        )
        config_data = copy.deepcopy(runs)
        success = True
        if any(existing.values()):
            details = '\n'.join(['{}: {}'.format(k, v) for k, v in existing.items()])
            header = 'Frames from this sequence already exist!\n'
            sub_header = details + (
                '\n\n<b>What would you like to do with them? </b>\n'
                'NOTE: Starting over will delete existing frames!\n'
            )
            buttons = (
                ('Cancel', RESPONSE_CANCEL),
                ('Start Over', RESPONSE_REPLACE_ALL),
                ('Resume', RESPONSE_SKIP)
            )

            response = dialogs.warning(header, sub_header, buttons=buttons)
            if response == RESPONSE_SKIP:
                success = True
                for run in config_data:
                    run['skip'] = ','.join([existing.get(run['name'], ''), run.get('skip', '')])
            elif response == RESPONSE_REPLACE_ALL:
                success = True
            else:
                success = False
        return success, config_data

    def check_run_store(self):
        count = 0
        item = self.run_store.get_item(count)
        names = set()
        while item:
            if item.props.state in [item.StateType.DRAFT, item.StateType.ACTIVE]:
                item.info['name'] = datatools.fix_name(item.info['name'], names)
                item.props.info = item.info
                names.add(item.info['name'])
            count += 1
            item = self.run_store.get_item(count)
        self.widget.datasets_collect_btn.set_sensitive(count > 1)

    def add_runs(self, runs):
        num_items = self.run_store.get_n_items()
        if num_items > 7:
            return

        default = datawidget.DataDialog.get_default(strategy_type=datawidget.StrategyType.FULL)
        distance = self.beamline.distance.get_position()
        for run in runs:
            energy = run['energy']
            resolution = converter.dist_to_resol(
                distance, self.beamline.detector.mm_size, energy
            )
            info = copy.copy(default)
            info.update({
                'resolution': round(resolution, 1),
                'strategy': datawidget.StrategyType.FULL,
                'energy': energy,
                'distance': round(distance, 1),
                'exposure': self.beamline.config['default_exposure'],
                'name': run['name'],
            })
            new_item = datawidget.RunItem({}, state=datawidget.RunItem.StateType.DRAFT)
            new_item.props.info = info
            pos = self.run_store.insert_sorted(new_item, datawidget.RunItem.sorter)
            self.check_run_store()
            new_item.props.position = pos

    def open_terminal(self, button):
        directory = self.widget.dsets_dir_fbk.get_text()
        misc.open_terminal(directory)

    def on_sample_updated(self, obj):
        sample = self.sample_store.get_current()
        sample_text = '{name}|{group}|{container}|{port}'.format(
            name=sample.get('name', '...'), group=sample.get('group', '...'), container=sample.get('container', '...'),
            port=sample.get('port', '...')
        ).replace('|...', '')
        self.widget.dsets_sample_fbk.set_text(sample_text)

    def on_save_run(self, obj):
        item = self.run_editor.item
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
        done = 0
        count = 0
        item = self.run_store.get_item(count)
        while item:
            if item.state in [item.StateType.COMPLETE, item.StateType.ERROR]:
                done += 1
            count += 1
            item = self.run_store.get_item(count)
        if done > 0:
            self.run_store.splice(count - done, done, [])

    def on_copy_run(self, obj):
        num_items = self.run_store.get_n_items()
        if num_items > 7:
            return
        new_item = datawidget.RunItem({}, state=datawidget.RunItem.StateType.DRAFT)
        new_item.props.info = self.run_editor.get_parameters()
        pos = self.run_store.insert_sorted(new_item, datawidget.RunItem.sorter)
        self.check_run_store()
        new_item.props.position = pos
        next_row = self.widget.datasets_list.get_row_at_index(pos)
        self.run_editor.set_item(new_item)
        self.editor_frame.set_row(next_row)

    def on_progress(self, obj, fraction):
        used_time = time.time() - self.start_time
        remaining_time = (1 - fraction) * used_time / fraction
        eta_time = remaining_time
        self.widget.collect_eta.set_text('{:0>2.0f}:{:0>2.0f} ETA'.format(*divmod(eta_time, 60)))
        self.widget.collect_pbar.set_fraction(fraction)

    def on_done(self, obj=None):
        self.on_complete(obj)
        self.widget.collect_eta.set_text('--:--')
        self.widget.collect_pbar.set_fraction(1.0)
        self.widget.collect_progress_lbl.set_text('Data acquisition completed.')

    def on_stopped(self, obj=None):
        self.widget.collect_eta.set_text('--:--')
        self.on_complete(obj)

    def on_pause(self, obj, paused, info):
        if paused:
            # Build the dialog message
            title = info.get('reason', '')
            msg = info.get('details', '')
            self.pause_dialog = dialogs.make_dialog(
                Gtk.MessageType.WARNING, title, msg,
                buttons=(('Stop', Gtk.ResponseType.CANCEL), ('OK', Gtk.ResponseType.OK))
            )
            response = self.pause_dialog.run()
            if response == Gtk.ResponseType.CANCEL:
                self.collector.stop()
                self.pause_dialog = None
        else:
            if self.pause_dialog:
                self.pause_dialog.destroy()
                self.pause_dialog = None

    def on_complete(self, obj=None):
        self.widget.datasets_collect_btn.set_sensitive(True)
        # gobject.idle_add(self.emit, 'new-datasets', obj.results)
        self.widget.collect_btn_icon.set_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        self.widget.datasets_clean_btn.set_sensitive(True)
        self.widget.datasets_overlay.set_sensitive(True)
        self.collecting = False
        self.stopping = False

    def on_started(self, obj):
        self.start_time = time.time()
        self.widget.datasets_collect_btn.set_sensitive(True)
        self.widget.datasets_clean_btn.set_sensitive(False)
        self.widget.datasets_overlay.set_sensitive(False)
        logger.info("Data Acquisition Started.")

    def on_new_image(self, widget, file_path):
        directory = os.path.dirname(file_path)
        home_dir = misc.get_project_home()
        current_dir = directory.replace(home_dir, '~')
        self.widget.dsets_dir_fbk.set_text(current_dir)
        frame = os.path.splitext(os.path.basename(file_path))[0]
        self.image_viewer.add_frame(file_path)
        run_item = self.frame_manager.get(frame)
        if run_item:
            run_item.set_collected(frame)
            if self.collecting:
                action = 'Acquiring' if not self.stopping else 'Stopping'
                self.widget.collect_progress_lbl.set_text(
                    '{} dataset {}: {} ...'.format(action, run_item.props.info['name'], frame)
                )
            else:
                self.widget.collect_progress_lbl.set_text(
                    'Stopped at dataset {}: {} ...'.format(run_item.props.info['name'], frame)
                )
        logger.info('Frame acquired: {}'.format(frame))

    def on_collect_btn(self, obj):
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
            success, checked_runs = self.check_runlist(runs)
            if success:
                self.collecting = True
                self.widget.collect_btn_icon.set_from_icon_name("media-playback-stop-symbolic",
                                                                Gtk.IconSize.LARGE_TOOLBAR)
                self.widget.collect_progress_lbl.set_text("Starting acquisition ...")
                self.widget.collect_pbar.set_fraction(0)
                self.collector.configure(checked_runs)
                self.collector.start()
                self.image_viewer.set_collect_mode(True)
