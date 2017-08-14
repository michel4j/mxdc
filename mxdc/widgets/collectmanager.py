from bcm.beamline.interfaces import IBeamline
from bcm.engine.diffraction import DataCollector
from bcm.engine.scripting import get_scripts
from bcm.utils import runlists
from bcm.utils.log import get_module_logger
from mxdc.utils import config, gui
from mxdc.widgets.dialogs import warning, error, MyDialog
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.widgets.misc import ActiveLabel, ActiveProgressBar
from mxdc.widgets.mountwidget import MountWidget
from mxdc.widgets.runmanager import RunManager
from twisted.python.components import globalRegistry
import gobject
import gtk
import pango
import os
import time
import copy

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

(
    COLLECT_COLUMN_STATUS,
    COLLECT_COLUMN_ANGLE,
    COLLECT_COLUMN_RUN,
    COLLECT_COLUMN_NAME,
    COLLECT_COLUMN_AVERAGE,
    COLLECT_COLUMN_DATASET,
) = range(6)

(
    COLLECT_STATE_IDLE,
    COLLECT_STATE_RUNNING,
    COLLECT_STATE_PAUSED
) = range(3)

FRAME_STATE_PENDING = DataCollector.STATE_PENDING
FRAME_STATE_RUNNING = DataCollector.STATE_RUNNING
FRAME_STATE_DONE = DataCollector.STATE_DONE
FRAME_STATE_SKIPPED = DataCollector.STATE_SKIPPED

(
    MOUNT_ACTION_NONE,
    MOUNT_ACTION_DISMOUNT,
    MOUNT_ACTION_MOUNT,
    MOUNT_ACTION_MANUAL_DISMOUNT,
    MOUNT_ACTION_MANUAL_MOUNT
) = range(5)

(
    RESPONSE_REPLACE_ALL,
    RESPONSE_REPLACE_BAD,
    RESPONSE_SKIP,
    RESPONSE_CANCEL,
) = range(4)

RUN_CONFIG_FILE = 'run_config.json'


class CollectManager(gtk.Alignment):
    __gsignals__ = {
        'new-datasets': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT, ]),
    }

    def __init__(self):
        gtk.Alignment.__init__(self, 0.5, 0.5, 1, 1)
        self._xml = gui.GUIFile(os.path.join(os.path.dirname(__file__), 'data/collect_widget'),
                                'collect_widget')
        self.run_data = []
        self.run_list = []

        self.collect_state = COLLECT_STATE_IDLE
        self.frame_pos = None
        self.total_frames = 1
        self.start_time = 0
        self._first_launch = False
        self.await_response = False

        self._create_widgets()

        self.active_sample = {}
        self.selected_sample = {}
        self.active_strategy = {}
        self.connect('realize', lambda x: self.update_data())
        self.scripts = get_scripts()

    def __getattr__(self, key):
        try:
            return super(CollectManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def do_new_datasets(self, dataset):
        pass

    def _create_widgets(self):
        self.image_viewer = ImageViewer(size=640)
        self.run_manager = RunManager()
        self.collector = DataCollector()
        self.mount_widget = MountWidget()
        self.beamline = globalRegistry.lookup([], IBeamline)

        self.collect_state = COLLECT_STATE_IDLE
        self.sel_mount_action = MOUNT_ACTION_NONE
        self.sel_mounting = False  # will be sent to true when mount command has been sent and false when it is done
        self.frame_pos = None

        pango_font = pango.FontDescription("monospace 8")
        self.strategy_view.modify_font(pango_font)

        # Run List
        self.listmodel = gtk.ListStore(
            gobject.TYPE_UINT,
            gobject.TYPE_FLOAT,
            gobject.TYPE_UINT,
            gobject.TYPE_STRING,
            gobject.TYPE_FLOAT,
            gobject.TYPE_STRING
        )

        self.listview = gtk.TreeView(self.listmodel)
        self.listview.set_rules_hint(True)
        self._add_columns()
        sw = self._xml.get_widget('run_list_window')
        sw.add(self.listview)

        self.mnt_hbox.add(self.mount_widget)

        self.collect_btn.set_label('mxdc-collect')
        self.stop_btn.set_label('mxdc-stop')
        self.stop_btn.set_sensitive(False)

        # Run progress
        self.progress_bar = ActiveProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.idle_text('0%')
        self.control_box.pack_start(self.progress_bar, expand=False, fill=True)

        # Current Position
        pos_table = self._xml.get_widget('position_table')
        if self.beamline is not None:
            pos_table.attach(ActiveLabel(self.beamline.omega, fmt='%7.2f'), 1, 2, 0, 1)
            pos_table.attach(ActiveLabel(self.beamline.diffractometer.two_theta, fmt='%7.2f'), 1, 2, 1, 2)
            pos_table.attach(ActiveLabel(self.beamline.diffractometer.distance, fmt='%7.2f'), 1, 2, 2, 3)
            pos_table.attach(ActiveLabel(self.beamline.monochromator.energy, fmt='%7.4f'), 1, 2, 3, 4)
            pos_table.attach(ActiveLabel(self.beamline.attenuator, fmt='%7.2f'), 1, 2, 4, 5)
            # Image Viewer
        self.frame_book.add(self.image_viewer)
        self.collect_widget.pack_end(self.run_manager, expand=True, fill=True)

        # automounter signals
        self.beamline.automounter.connect('busy', self.on_mount_busy)
        self.beamline.automounter.connect('mounted', self.on_mount_done)
        self.beamline.manualmounter.connect('mounted', self.on_mount_done)

        # diagnostics
        # self.diagnostics = DiagnosticsWidget()
        # self.tool_book.append_page(self.diagnostics, tab_label=gtk.Label('Run Diagnostics'))
        # self.tool_book.connect('realize', lambda x: self.tool_book.set_current_page(0))
        # self.diagnostics.set_sensitive(False)

        self.collect_btn.set_sensitive(False)
        self.collect_btn.connect('clicked', self.on_activate)
        self.stop_btn.connect('clicked', self.on_stop)
        self.run_manager.connect('saved', self.save_runs)
        self.clear_strategy_btn.connect('clicked', self.on_clear_strategy)

        for w in [self.collect_btn, self.stop_btn]:
            w.set_property('can-focus', False)

        self.collector.connect('done', self.on_done)
        self.collector.connect('error', self.on_error)
        self.collector.connect('paused', self.on_pause)
        self.collector.connect('new-image', self.on_new_image)
        self.collector.connect('stopped', self.on_stopped)
        self.collector.connect('progress', self.on_progress)
        self.collector.connect('started', self.on_started)

        self._load_config()
        self.add(self.collect_widget)
        self.run_manager.set_current_page(0)
        self.show_all()

        # prepare pixbufs for status icons
        self._wait_img = gtk.gdk.pixbuf_new_from_file(os.path.join(os.path.dirname(__file__),
                                                                   'data/tiny-wait.png'))
        self._ready_img = gtk.gdk.pixbuf_new_from_file(os.path.join(os.path.dirname(__file__),
                                                                    'data/tiny-ready.png'))
        self._error_img = gtk.gdk.pixbuf_new_from_file(os.path.join(os.path.dirname(__file__),
                                                                    'data/tiny-error.png'))
        self._skip_img = gtk.gdk.pixbuf_new_from_file(os.path.join(os.path.dirname(__file__),
                                                                   'data/tiny-skip.png'))

    def _load_config(self):
        if not config.SESSION_INFO.get('new', False):
            data = config.load_config(RUN_CONFIG_FILE)
            if data is not None:
                for section in data.keys():
                    run = int(section)
                    data[run] = data[section]
                    self.add_run(data[run])

    def _save_config(self):
        save_data = {}
        for run in self.run_manager.runs:
            data = run.get_parameters()
            save_data[data['number']] = data
        config.save_config(RUN_CONFIG_FILE, save_data)

    def update_data(self, sample=None, strategy=None):
        # pass in {} to delete the current setting or None to ignore it
        # self.mount_widget.update_data(sample)
        # handle strategy data
        if strategy is not None:
            # if number of keys in strategy is 6 or more then replace it
            # otherwise simply update it
            if strategy == {} or len(strategy.keys()) > 5:
                self.active_strategy = strategy
            else:
                self.active_strategy.update(strategy)

            # send updated strategy parameters to runs, do not send active sample
            self.run_manager.update_active_data(strategy=self.active_strategy)

            if self.active_strategy != {}:
                # display text in strategy_view
                txt = ""
                for key in ['start_angle', 'delta_angle', 'exposure_time', 'attenuation', 'distance', 'total_angle']:
                    if key in self.active_strategy:
                        txt += '%15s: %7.2f\n' % (key, self.active_strategy[key])
                if 'energy' in self.active_strategy:
                    scat_fac = self.active_strategy.get('scattering_factors')
                    if scat_fac is None:
                        txt += "%15s:\n" % ('energies')
                        for val, lbl, sf in zip(self.active_strategy['energy'], self.active_strategy['energy_label']):
                            txt += "%15s = %7.4f\n" % (lbl, val)
                    else:
                        txt += "%15s:\n" % ('energies')
                        txt += "%6s %7s %6s %6s\n" % ('name', 'energy', 'f\'', 'f"')
                        txt += "  --------------------------\n"
                        for val, lbl, sf in zip(self.active_strategy['energy'], self.active_strategy['energy_label'],
                                                scat_fac):
                            txt += "%6s %7.4f %6.2f %6.2f\n" % (lbl, val, sf['fp'], sf['fpp'])
                buf = self.strategy_view.get_buffer()
                buf.set_text(txt)
                # self.active_strategy_box.set_visible(True)
                self.active_strategy_box.show()
            else:
                # self.active_strategy_box.set_visible(False)
                self.active_strategy_box.hide()

    def update_active_sample(self, sample=None):
        # send updated parameters to runs
        if sample is None:
            self.active_sample = {}
        else:
            self.active_sample = sample
        self.mount_widget.update_active_sample(self.active_sample)
        self.run_manager.update_active_data(sample=self.active_sample)

    def update_selected(self, sample=None):
        self.mount_widget.update_selected(sample)

    def on_clear_strategy(self, obj):
        self.update_data(strategy={})

    def on_mount_busy(self, obj, busy):
        if busy:
            self.progress_bar.busy_text(self.mount_widget.busy_text)
        else:
            self.progress_bar.idle_text('')

    def on_mount_done(self, obj, state):
        if obj.__class__.__name__ is "ManualMounter":
            if state is not None:
                done_text = "Manual Mount"
            else:
                done_text = "Manual Dismount"
        else:
            if state is not None and obj.health_state[0] == 0:
                done_text = "Mount Succeeded"
            elif obj.health_state[0] == 0:
                done_text = "Dismount Succeeded"
            else:
                done_text = obj.health_state[1]
        self.progress_bar.idle_text(done_text)

    def _add_item(self, item):
        itr = self.listmodel.append()
        if item['saved']:
            status = FRAME_STATE_DONE
        else:
            status = FRAME_STATE_PENDING
        self.listmodel.set(itr,
                           COLLECT_COLUMN_STATUS, status,
                           COLLECT_COLUMN_ANGLE, item['start_angle'],
                           COLLECT_COLUMN_RUN, item.get('number', 1),
                           COLLECT_COLUMN_NAME, item['frame_name'],
                           COLLECT_COLUMN_AVERAGE, 0.0,
                           COLLECT_COLUMN_DATASET, item['dataset'],
                           )
        self.total_frames = self.listmodel.get_path(itr)[0]

    def _saved_pixbuf(self, column, renderer, model, itr):
        value = model.get_value(itr, COLLECT_COLUMN_STATUS)
        if value == FRAME_STATE_PENDING:
            renderer.set_property('pixbuf', None)
        elif value == FRAME_STATE_RUNNING:
            renderer.set_property('pixbuf', self._wait_img)
        elif value == FRAME_STATE_DONE:
            renderer.set_property('pixbuf', self._ready_img)
        elif value == FRAME_STATE_SKIPPED:
            renderer.set_property('pixbuf', self._skip_img)
        else:
            renderer.set_property('pixbuf', None)

    def _saved_color(self, column, renderer, model, itr):
        status = model.get_value(itr, COLLECT_COLUMN_STATUS)
        _state_colors = {
            FRAME_STATE_PENDING: None,
            FRAME_STATE_RUNNING: '#990099',
            FRAME_STATE_SKIPPED: '#777777',
            FRAME_STATE_DONE: '#006600',
        }
        renderer.set_property("foreground", _state_colors.get(status))
        return

    def _float_format(self, column, renderer, model, itr, fmt):
        value = model.get_value(itr, COLLECT_COLUMN_ANGLE)
        renderer.set_property('text', fmt % value)
        self._saved_color(column, renderer, model, itr)
        return

    def _add_columns(self):
        # Saved Column
        renderer = gtk.CellRendererPixbuf()
        column = gtk.TreeViewColumn('', renderer)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(24)
        column.set_cell_data_func(renderer, self._saved_pixbuf)
        self.listview.append_column(column)

        # Name Column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Name', renderer, text=COLLECT_COLUMN_NAME)
        column.set_cell_data_func(renderer, self._saved_color)
        self.listview.append_column(column)

        # Angle Column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Angle', renderer, text=COLLECT_COLUMN_ANGLE)
        column.set_cell_data_func(renderer, self._float_format, '%5.2f')
        self.listview.append_column(column)

    def save_runs(self, obj=None):
        self.clear_runs()
        run_num = self.run_manager.get_current_page()

        for run in self.run_manager.runs:
            data = run.get_parameters()
            if run_num == 0 and data['number'] == 0:
                data['energy'] = [self.beamline.monochromator.energy.get_position()]
                data['energy_label'] = ['E0']
                self.run_data = [data]
                break
            elif (run_num == data['number'] or run.is_enabled()) and data['number'] != 0:
                self.run_data.append(data)

        self._save_config()
        self.create_runlist()

    def add_run(self, data):
        self.run_manager.add_new_run(data)

    def clear_runs(self):
        del self.run_data[:]
        self.run_data = []
        self.listmodel.clear()
        self.collect_btn.set_sensitive(False)

    def create_runlist(self):
        self.run_list = runlists.generate_run_list(self.run_data)
        self.gen_sequence()

    def gen_sequence(self):
        self.listmodel.clear()
        for item in self.run_list:
            self._add_item(item)
        self.total_frames = len(self.run_list)
        if self.total_frames:
            self.collect_btn.set_sensitive(True)
        else:
            self.collect_btn.set_sensitive(False)

    def check_runlist(self):
        existing, bad = runlists.check_frame_list(
            self.run_list, self.beamline.detector.file_extension, detect_bad=False
        )
        config_data = copy.deepcopy(self.run_data)
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

            response = warning(header, sub_header, buttons=buttons)
            if response == RESPONSE_SKIP:
                success = True
                for run in config_data:
                    run['skip'] = ','.join([existing.get(run['name'], ''), run.get('skip', '')])
            elif response == RESPONSE_REPLACE_ALL:
                success = True
                self.reset_frame_states()
            else:
                success = False
        return success, config_data

    def on_pause(self, obj, paused, info):
        if paused:
            # Build the dialog message
            title = info.get('reason', '')
            msg = info.get('details', '')
            self.pause_dialog = MyDialog(
                gtk.MESSAGE_WARNING, title, msg,
                buttons=(('Stop', gtk.RESPONSE_NO), ('OK', gtk.RESPONSE_YES))
            )
            self.progress_bar.busy_text("Waiting for Beam!")
            response = self.pause_dialog()
            if response == gtk.RESPONSE_NO:
                self.collector.stop()
                self.pause_dialog = None
        else:
            if self.pause_dialog:
                self.pause_dialog.dialog.destroy()
                self.pause_dialog = None

    def on_error(self, widget, msg):
        msg_title = msg
        msg_sub = 'Connection to detector was lost. '
        msg_sub += 'Data collection can not proceed reliably.'
        error(msg_title, msg_sub)

    def on_activate(self, widget):
        if not self.run_list:
            msg1 = 'Dataset list is empty!'
            msg2 = 'Please create dataset runs before collecting.'
            warning(msg1, msg2)
            return

        self.start_collection()
        self.progress_bar.set_fraction(0)

    def on_done(self, obj=None):
        self.on_complete(obj)
        text = 'Completed in %s' % time.strftime('%H:%M:%S', time.gmtime(time.time() - self.start_time))
        self.progress_bar.idle_text(text)

    def on_stopped(self, obj=None):
        self.progress_bar.idle_text("Stopped!")
        self.on_complete(obj)

    def on_complete(self, obj=None):
        self.collect_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)
        self.run_manager.set_sensitive(True)
        gobject.idle_add(self.emit, 'new-datasets', obj.results)
        self.beamline.lims.upload_datasets(self.beamline, obj.results)

    def on_started(self, obj):
        self.start_time = time.time()
        self.stop_btn.set_sensitive(True)
        self.collect_btn.set_sensitive(False)
        _logger.info("Data Collection Started.")

    def on_new_image(self, widget, file_path):
        frame = os.path.splitext(os.path.basename(file_path))[0]
        itr = self.listmodel.get_iter_first()
        while itr:
            fname = self.listmodel.get_value(itr, COLLECT_COLUMN_NAME)
            if fname == frame:
                self.listmodel.set(itr, COLLECT_COLUMN_STATUS, FRAME_STATE_DONE)
                path = self.listmodel.get_path(itr)
                self.listview.scroll_to_cell(path, use_align=True, row_align=0.7)
                break
            else:
                state = self.listmodel.get_value(itr, COLLECT_COLUMN_STATUS)
                if state == FRAME_STATE_PENDING:
                    self.listmodel.set(itr, COLLECT_COLUMN_STATUS, FRAME_STATE_SKIPPED)
            itr = self.listmodel.iter_next(itr)

        self.image_viewer.add_frame(file_path)
        _logger.info('Frame collected: {}'.format(frame))

    def reset_frame_states(self):
        itr = self.listmodel.get_iter_first()
        while itr:
            self.listmodel.set(itr, COLLECT_COLUMN_STATUS, FRAME_STATE_PENDING)
            itr = self.listmodel.iter_next(itr)

    def on_progress(self, obj, fraction):
        used_time = time.time() - self.start_time
        remaining_time = (1 - fraction) * used_time / fraction
        eta_time = remaining_time
        frame_time = (used_time + remaining_time) / self.total_frames
        eta_format = eta_time >= 3600 and '%H:%M:%S' or '%M:%S'
        text = "ETA %s @ %0.1fs/f" % (time.strftime(eta_format, time.gmtime(eta_time)), frame_time)
        self.progress_bar.set_complete(fraction, text)

    def on_energy_changed(self, obj, val):
        run_zero = self.run_manager.runs[0]
        data = run_zero.get_parameters()
        data['energy'] = [val]
        run_zero.set_parameters(data)

    def update_values(self, dct):
        for key in dct.keys():
            self.labels[key].set_text(dct[key])

    def start_collection(self):
        success, config_data = self.check_runlist()
        if success:
            self.collect_btn.set_sensitive(False)
            self.progress_bar.busy_text("Starting acquisition ...")
            self.collector.configure(config_data)
            self.collector.start()
            self.run_manager.set_sensitive(False)
            self.image_viewer.set_collect_mode(True)

    def on_stop(self, obj):
        self.stop_btn.set_sensitive(False)
        self.progress_bar.busy_text("Stopping acquisition ...")
        self.collector.stop()
