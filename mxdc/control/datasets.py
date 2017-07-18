from gi.repository import GObject, Gio, Gtk, Gdk
from mxdc.beamline.mx import IBeamline
from mxdc.utils import converter, runlists
from mxdc.utils.config import settings
from mxdc.utils.log import get_module_logger
from mxdc.widgets import datawidget, dialogs
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.engine.diffraction import DataCollector
from samplestore import ISampleStore
import common
import uuid
import copy
import time
import os
from twisted.python.components import globalRegistry

_logger = get_module_logger('mxdc.samples')


(
    RESPONSE_REPLACE_ALL,
    RESPONSE_REPLACE_BAD,
    RESPONSE_SKIP,
    RESPONSE_CANCEL,
) = range(4)


class RunItem(GObject.GObject):
    class StateType:
        (DRAFT, ACTIVE, COMPLETE, ERROR) = range(4)

    state = GObject.Property(type=int, default=0)
    position = GObject.Property(type=int, default=0)
    info = GObject.Property(type=GObject.TYPE_PYOBJECT)
    progress = GObject.Property(type=float, default=0.0)
    warning = GObject.Property(type=str, default="")

    def __init__(self, info):
        super(RunItem, self).__init__()
        self.frames = []
        self.collected = []

        self.connect('notify::info', self.on_info_changed)
        self.props.info = info
        self.uuid = str(uuid.uuid4())

    def on_info_changed(self, item, param):
        self.frames = runlists.generate_frame_names(self.props.info)

    def set_collected(self, frame):
        self.collected.append(frame)
        prog = 100.0 * len(self.collected)/len(self.frames)
        self.props.progress = prog
        if 0.0 < prog < 100.0:
            self.props.state = RunItem.StateType.ACTIVE
        elif prog == 100.0:
            self.props.state = RunItem.StateType.COMPLETE

    def get_color(self):
        return  Gdk.RGBA(*STATE_COLORS[self.props.state][self.props.position % 2])

    def __getitem__(self, item):
        return self.info[item]

    def __unicode__(self):
        return '<Run Item: {}|{}|{}>'.format(self.props.position, self.props.info['strategy_desc'], self.uuid)


STATE_COLORS = {
    RunItem.StateType.DRAFT:     [(1.0, 1.0, 1.0, 0.0), (0.9, 0.9, 0.9, 0.5)],
    RunItem.StateType.ACTIVE:    [(1.0, 1.0, 0.0, 0.1), (1.0, 1.0, 0.0, 0.2)],
    RunItem.StateType.COMPLETE:  [(0.0, 1.0, 0.0, 0.1), (0.0, 1.0, 0.0, 0.2)],
    RunItem.StateType.ERROR:     [(1.0, 0.0, 0.5, 0.1), (1.0, 0.0, 0.0, 0.2)],
}


class DatasetsController(GObject.GObject):
    __gsignals__ = {
        'samples-changed': (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT,)),
        'active-sample': (GObject.SignalFlags.RUN_LAST, None, [GObject.TYPE_PYOBJECT, ]),
        'sample-selected': (GObject.SignalFlags.RUN_LAST, None, [GObject.TYPE_PYOBJECT, ]),
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
        self.run_editor = datawidget.RunEditor()
        self.run_editor.window.set_transient_for(dialogs.MAIN_WINDOW)
        self.run_store = Gio.ListStore(item_type=RunItem)
        self.run_store.connect('items-changed', self.update_positions)

        self.collector.connect('done', self.on_done)
        self.collector.connect('paused', self.on_pause)
        self.collector.connect('new-image', self.on_new_image)
        self.collector.connect('stopped', self.on_stopped)
        self.collector.connect('progress', self.on_progress)
        self.collector.connect('started', self.on_started)
        self.setup()

    @staticmethod
    def update_positions(model, position, removed, added):
        pos = 0
        item = model.get_item(pos)
        while item:
            item.props.position = pos
            pos += 1
            item = model.get_item(pos)

    def setup(self):
        self.widget.datasets_list.bind_model(self.run_store, self.create_run_config)
        self.widget.datasets_viewer_box.add(self.image_viewer)
        self.widget.datasets_add_btn.connect('clicked', self.on_add_run)
        self.widget.datasets_clear_btn.connect('clicked', self.on_clear_runs)
        self.run_editor.run_cancel_btn.connect('clicked', lambda x: self.run_editor.window.hide())
        self.run_editor.run_save_btn.connect('clicked', self.on_save_run)
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        self.sample_store.connect('updated', self.on_sample_updated)

        labels = {
            'omega': (self.beamline.omega, self.widget.dsets_omega_fbk, '{:0.1f} deg'),
            'energy': (self.beamline.energy, self.widget.dsets_energy_fbk, '{:0.3f} keV'),
            #'sample': (self.sample_store, self.widget.dsets_sample_fbk, '{}'),
            'attenuation': (self.beamline.attenuator, self.widget.dsets_attenuation_fbk, '{:0.0f} %'),
            #'maxres': self.widget.dsets_maxres_fbk,
            'aperture': (self.beamline.aperture, self.widget.dsets_aperture_fbk,'{:0.0f} um'),
            'two_theta': (self.beamline.two_theta, self.widget.dsets_2theta_fbk,'{:0.0f} deg'),
        }
        self.monitors = {
            name: common.DeviceMonitor(dev, lbl, fmt)
            for name, (dev, lbl, fmt) in labels.items()
        }
        self.widget.datasets_collect_btn.connect('clicked', self.on_collect_btn)

    def create_run_config(self, item):
        config = datawidget.RunConfig()
        config.set_item(item)
        config.delete_run_btn.connect('clicked', self.on_delete_run, item)
        config.edit_run_btn.connect('clicked', self.on_edit_run, item)
        config.copy_run_btn.connect('clicked', self.on_copy_run, item)
        return config.dataset_run_row

    def generate_run_list(self):
        runs = []
        self.frame_manager = {} # initialize frame manager
        pos = 0
        item = self.run_store.get_item(pos)
        while item:
            if item.state != item.StateType.COMPLETE:
                run = {'uuid': item.uuid}
                run.update(item.info)
                runs.append(run)
                self.frame_manager.update({
                    frame: item for frame in item.frames
                })
            pos += 1
            item = self.run_store.get_item(pos)
        return runs

    def check_runlist(self, runs):
        frame_list = runlists.generate_run_list(runs)
        existing, bad = runlists.check_frame_list(
            frame_list, self.beamline.detector.file_extension, detect_bad=False
        )
        config_data = copy.deepcopy(runs)
        success = True
        if any(existing.values()):
            details = '\n'.join(['{}: {}'.format(k, v) for k, v in existing.items()])
            header = 'Frames from this sequence already exist!\n'
            sub_header = details + (
                '\n\n<b>What would you like to do with them? </b>\n'
                'NOTE: Re-collecting will delete existing frames!\n'
            )
            buttons = (
                ('Cancel', RESPONSE_CANCEL),
                ('Re-Collect', RESPONSE_REPLACE_ALL),
                ('Continue', RESPONSE_SKIP)
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
            if item.props.state !=  item.StateType.COMPLETE:
                if item.props.info['name'] in names:
                    item.props.warning = 'Dataset with this name already exists!'
                    item.props.state = item.StateType.ERROR
                else:
                    item.props.warning = ''
                    item.props.state = item.StateType.DRAFT
                names.add(item.props.info['name'])
            count += 1
            item = self.run_store.get_item(count)
        self.widget.datasets_collect_btn.set_sensitive(count > 0)

    def on_sample_updated(self, obj):
        sample = self.sample_store.get_current()
        self.run_editor.set_sample(sample)
        sample_text = '{name}|{group}|{container}|{port}'.format(
            name=sample.get('name', '...'), group=sample.get('group', '...'), container=sample.get('container', '...'),
            port=sample.get('port', '...')
        ).replace('|...', '')
        self.widget.dsets_sample_fbk.set_text(sample_text)

    def on_add_run(self, obj):
        sample = self.sample_store.get_current()
        energy = self.beamline.bragg_energy.get_position()
        distance = self.beamline.distance.get_position()
        resolution = converter.dist_to_resol(
            distance, self.beamline.detector.mm_size, energy
        )
        config = {
            'resolution': resolution,
            'delta': self.beamline.config['default_delta'],
            'range': 180.,
            'start': 0.,
            'wedge': 360.,
            'energy': energy,
            'distance': distance,
            'exposure': self.beamline.config['default_delta'],
            'attenuation': 0.,
            'first': 1,
            'name': sample.get('name', 'test'),
            'helical': False,
            'inverse': False,
        }
        self.run_editor.configure(config)
        self.run_editor.item = None
        self.run_editor.window.show_all()

    def on_save_run(self, obj):
        if not self.run_editor.item:
            # insert item after all other draft items
            pos = 0
            item = self.run_store.get_item(pos)
            while item and item.props.state in [item.StateType.DRAFT, item.StateType.ACTIVE]:
                pos += 1
                item = self.run_store.get_item(pos)
            new_item = RunItem(self.run_editor.get_parameters())
            self.run_store.insert(pos, new_item)
            self.run_editor.window.hide()
        else:
            item = self.run_editor.item
            item.info = self.run_editor.get_parameters()
            self.run_editor.window.hide()
        self.check_run_store()

    def on_delete_run(self, obj, item):
        self.run_store.remove(item.position)
        self.check_run_store()

    def on_edit_run(self, obj, item):
        self.run_editor.configure(item.info)
        self.run_editor.item = item
        self.run_editor.window.show_all()

    def on_copy_run(self, obj, item):
        self.run_editor.configure(item.info)
        self.run_editor.item = None
        self.run_editor.window.show_all()

    def on_clear_runs(self, obj):
        self.run_store.remove_all()

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
        #gobject.idle_add(self.emit, 'new-datasets', obj.results)
        #self.beamline.lims.upload_datasets(self.beamline, obj.results)
        self.widget.collect_btn_icon.set_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        self.widget.datasets_add_btn.set_sensitive(True)
        self.widget.datasets_clear_btn.set_sensitive(True)
        self.widget.datasets_list.set_sensitive(True)
        self.collecting = False
        self.stopping = False

    def on_started(self, obj):
        self.start_time = time.time()
        self.widget.datasets_collect_btn.set_sensitive(True)
        self.widget.datasets_add_btn.set_sensitive(False)
        self.widget.datasets_clear_btn.set_sensitive(False)
        self.widget.datasets_list.set_sensitive(False)
        _logger.info("Data Acquisition Started.")

    def on_new_image(self, widget, file_path):
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
        _logger.info('Frame acquired: {}'.format(frame))

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
                self.widget.collect_btn_icon.set_from_icon_name("media-playback-stop-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
                self.widget.collect_progress_lbl.set_text("Starting acquisition ...")
                self.widget.collect_pbar.set_fraction(0)
                self.collector.configure(checked_runs)
                self.collector.start()
                self.image_viewer.set_collect_mode(True)