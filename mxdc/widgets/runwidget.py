from bcm.beamline.mx import IBeamline
from bcm.utils import science, misc
from mxdc.utils import gui, config
from mxdc.widgets import dialogs
from mxdc.widgets.predictor import Predictor
from twisted.python.components import globalRegistry
import gobject
import gtk
import os

(
    COLUMN_LABEL,
    COLUMN_ENERGY,
    COLUMN_EDITABLE,
    COLUMN_CHANGED,
) = range(4)

DEFAULT_PARAMETERS = {
    'name': 'test',
    'directory': config.SESSION_INFO.get('current_path', config.SESSION_INFO['path']),
    'distance': 250.0,
    'delta_angle': 1.0,
    'exposure_time': 1.0,
    'start_angle': 0,
    'total_angle': 180.0,
    'first_frame': 1,
    'num_frames': 180,
    'inverse_beam': False,
    'wedge': 360.0,
    'energy': [12.658],
    'energy_label': ['E0'],
    'attenuation': 0.0,
    'number': 1,
    'two_theta': 0.0,
    'skip': '',
    'crystal_id': None,
    'experiment_id': None,
    'comments': '',
    'scattering_factors': None,
}

_ENERGY_DB = science.get_energy_database()


class RunWidget(gtk.Alignment):
    def __init__(self, num=0):
        gtk.Alignment.__init__(self, 0.5, 0.5, 1, 1)
        self._xml = gui.GUIFile(os.path.join(os.path.dirname(__file__), 'data/run_widget'),
                                'run_widget')

        self.add(self.run_widget)
        self.update_btn.connect('clicked', self.on_update_parameters)
        self.reset_btn.connect('clicked', self.on_reset_parameters)
        self.entry = {}

        # Data for entries (name: (col, row, length, [unit]))
        entries = ['name', 'distance', 'delta_angle', 'exposure_time', 'first_frame',
                   'start_angle', 'num_frames', 'total_angle', 'wedge',
                   'attenuation', 'inverse_beam', 'skip', 'dafs']
        for e in entries:
            self.entry[e] = self._xml.get_widget(e)
            if isinstance(self.entry[e], gtk.Entry) and e not in ['name', ]:
                self.entry[e].set_alignment(1)

        self.beamline = globalRegistry.lookup([], IBeamline)
        self.folder_entry = dialogs.FolderSelector(self.directory_btn)
        self.entry['directory'] = self.folder_entry

        # entry signals
        self.entry['name'].connect('focus-out-event', self.on_prefix_changed)
        self.entry['start_angle'].connect('focus-out-event', self.on_start_angle_changed)
        self.entry['delta_angle'].connect('focus-out-event', self.on_delta_changed)
        self.entry['total_angle'].connect('focus-out-event', self.on_total_angle_changed)
        self.entry['num_frames'].connect('focus-out-event', self.on_total_frames_changed)
        self.entry['first_frame'].connect('focus-out-event', self.on_start_frame_changed)
        self.entry['distance'].connect('focus-out-event', self.on_distance_changed)
        self.entry['exposure_time'].connect('focus-out-event', self.on_time_changed)
        self.entry['wedge'].connect('focus-out-event', self.on_wedge_changed)
        self.entry['attenuation'].connect('focus-out-event', self.on_attenuation_changed)
        self.entry['skip'].connect('focus-out-event', self.on_skip_changed)

        self.entry['name'].connect('activate', self.on_prefix_changed)
        self.entry['start_angle'].connect('activate', self.on_start_angle_changed)
        self.entry['delta_angle'].connect('activate', self.on_delta_changed)
        self.entry['total_angle'].connect('activate', self.on_total_angle_changed)
        self.entry['num_frames'].connect('activate', self.on_total_frames_changed)
        self.entry['first_frame'].connect('activate', self.on_start_frame_changed)
        self.entry['distance'].connect('activate', self.on_distance_changed)
        self.entry['exposure_time'].connect('activate', self.on_time_changed)
        self.entry['wedge'].connect('activate', self.on_wedge_changed)
        self.entry['attenuation'].connect('activate', self.on_attenuation_changed)
        self.entry['skip'].connect('activate', self.on_skip_changed)

        # Energy
        self.energy_store = gtk.ListStore(
            gobject.TYPE_STRING,
            gobject.TYPE_PYOBJECT,
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_BOOLEAN,
        )
        self.energy_list = gtk.TreeView(model=self.energy_store)
        self.energy_list.set_hover_selection(True)
        self.energy_list.connect('focus-out-event', self.on_energy_changed)
        self.energy_list.connect('button-press-event', self.on_delete_clicked)

        self.energy_list.set_rules_hint(True)
        self.energy_view.add(self.energy_list)

        # Energy column
        renderer = gtk.CellRendererText()
        renderer.set_data('column', COLUMN_ENERGY)
        renderer.connect("edited", self.on_energy_edited, self.energy_store)
        renderer.connect("editing-started", self.on_editing_started)
        renderer.set_property('xalign', 0.5)
        column1 = gtk.TreeViewColumn('Energy (KeV)', renderer, text=COLUMN_ENERGY, editable=COLUMN_EDITABLE)
        column1.set_cell_data_func(renderer, self._cell_format, COLUMN_ENERGY)
        column1.set_expand(True)
        column1.set_alignment(0.0)
        self.energy_list.append_column(column1)

        # Label column
        renderer = gtk.CellRendererText()
        renderer.set_data('column', COLUMN_LABEL)
        renderer.connect("edited", self.on_energy_edited, self.energy_store)
        renderer.set_property('xalign', 0.5)
        column1 = gtk.TreeViewColumn('Label', renderer, text=COLUMN_LABEL, editable=COLUMN_EDITABLE)
        column1.set_cell_data_func(renderer, self._cell_format, COLUMN_LABEL)
        column1.set_min_width(80)
        column1.set_expand(False)
        column1.set_alignment(0.5)
        self.energy_list.append_column(column1)
        self.expand_separator.set_expand(True)

        # Delete column
        renderer = gtk.CellRendererPixbuf()
        renderer.set_property("stock-size", gtk.ICON_SIZE_MENU)
        renderer.set_property('xalign', 0.7)
        column1 = gtk.TreeViewColumn('', renderer)
        column1.set_cell_data_func(renderer, self._icon_format)
        column1.set_min_width(20)
        column1.set_expand(False)
        self.energy_list.append_column(column1)
        self._delete_column = column1  # need to remember its reference

        self.predictor = None

        # connect signals
        self.save_btn.connect('clicked', self.on_save)
        self.show_all()
        self.set_no_show_all(True)

        # initialize parameters
        self.parameters = {}
        self.parameters.update(DEFAULT_PARAMETERS)
        self.set_number(num)
        self.set_parameters(self.parameters)

        # active database
        self.active_sample = {}
        self.active_strategy = {}

        self._changes_pending = False

    def __getattr__(self, key):
        try:
            return super(RunWidget).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def _set_energies(self, edict):
        self.energy_store.clear()
        if edict == {}:
            _e_value = self.beamline.energy.get_position()
            edict = {'energy': [_e_value], 'energy_label': ['E0']}

        for i in range(len(edict['energy'])):
            item = [edict['energy_label'][i], edict['energy'][i], True, False]
            itr = self.energy_store.append()
            self.energy_store.set(itr,
                                  COLUMN_LABEL, item[COLUMN_LABEL],
                                  COLUMN_ENERGY, item[COLUMN_ENERGY],
                                  COLUMN_EDITABLE, item[COLUMN_EDITABLE],
                                  COLUMN_CHANGED, item[COLUMN_CHANGED],
                                  )
        itr = self.energy_store.append()
        self.energy_store.set(itr,
                              COLUMN_LABEL, '',
                              COLUMN_ENERGY, None,
                              COLUMN_EDITABLE, True,
                              COLUMN_CHANGED, False,
                              )

    def _cell_format(self, cell, renderer, model, itr, column):
        value = model.get_value(itr, COLUMN_ENERGY)
        if column == COLUMN_ENERGY:
            if value:
                txt = '%0.4f' % value
                renderer.set_property('text', txt)
            else:
                renderer.set_property('markup', '<i>Click to add</i>')
        if value and model.get_value(itr, COLUMN_CHANGED):
            renderer.set_property("foreground", '#cc00cc')
        elif value:
            renderer.set_property("foreground", None)
        else:
            renderer.set_property("foreground", '#cccccc')
        return

    def _icon_format(self, cell, renderer, model, itr):
        value = model.get_value(itr, COLUMN_ENERGY)
        path = model.get_path(itr)
        size = model.iter_n_children(None)
        if path == (0,) and size == 2:
            renderer.set_property('stock-id', 'gtk-refresh')
            renderer.set_property('sensitive', True)
        elif value:
            renderer.set_property('stock-id', 'gtk-remove')
            renderer.set_property('sensitive', True)
        else:
            renderer.set_property('stock-id', 'gtk-add')
            renderer.set_property('sensitive', False)

    def _set_energy_changed(self, state=False):
        model = self.energy_list.get_model()
        itr = model.get_iter_first()
        while itr:
            model.set(itr, COLUMN_CHANGED, state)
            itr = model.iter_next(itr)

    def _delete_energy_row(self, itr):
        size = self.energy_store.iter_n_children(None)
        path = self.energy_store.get_path(itr)
        last_row = (path[0] == size - 1)
        last_iter = self.energy_store.get_iter((size - 1,))
        last_val = self.energy_store.get_value(last_iter, COLUMN_ENERGY)

        if not last_row:
            self.energy_store.remove(itr)
            if last_val:
                last_iter = self.energy_store.append()

        self.energy_store.set(last_iter, COLUMN_EDITABLE, True)
        self.energy_store.set(last_iter, COLUMN_ENERGY, None)
        self.energy_store.set(last_iter, COLUMN_LABEL, "")

    def _reset_energy_row(self, itr):
        cur_e = self.beamline.energy.get_position()
        self.energy_store.set(itr, COLUMN_ENERGY, cur_e)
        self.dafs.set_active(False)
        self.dafs.hide()

    def on_delete_clicked(self, treeview, event):
        if event.button == 1:
            path, column = treeview.get_path_at_pos(int(event.x), int(event.y))[:2]
            if column == self._delete_column:
                size = self.energy_store.iter_n_children(None)
                itr = self.energy_store.get_iter(path)
                if path == (0,) and size == 2:
                    self._reset_energy_row(itr)
                else:
                    self._delete_energy_row(itr)

    def on_editing_started(self, cell, editable, path):
        model = self.energy_store
        itr = model.get_iter(path)
        value = model.get_value(itr, COLUMN_ENERGY)
        # editable.connect('focus-out-event', self.on_editing_finished)
        if not value:
            editable.delete_selection()

    def on_editing_finished(self, editable, event):
        editable.editing_done()

    def on_energy_edited(self, cell, path_string, new_text, model):
        itr = model.get_iter_from_string(path_string)
        column = cell.get_data("column")
        new_text = new_text.strip()
        path = model.get_path(itr)
        size = model.iter_n_children(None)
        last_row = (path[0] == size - 1)
        e_value = model.get_value(itr, COLUMN_ENERGY)

        if column == COLUMN_ENERGY:
            if new_text == "":
                if path == (0,) and size == 2:
                    self._reset_energy_row(itr)
                else:
                    self._delete_energy_row(itr)
            else:
                try:
                    _e = float(new_text)
                except:
                    # Allow using edge name such as "Se-K"
                    _e = _ENERGY_DB.get(new_text, (e_value,))[0]

                    # Show DAFS button if this is the case
                    self.dafs.show()

                model.set(itr, COLUMN_ENERGY, _e)
                if _e is not None:
                    lbl = model.get_value(itr, COLUMN_LABEL)
                    if not lbl:
                        model.set(itr, COLUMN_LABEL, 'E%d' % path)

                    if last_row and size < 4:
                        # Add a new row if we add to the last row
                        tail = model.append()
                        model.set(tail, COLUMN_EDITABLE, True)
                        model.set(tail, COLUMN_ENERGY, None)
                        model.set(tail, COLUMN_LABEL, "")

        elif column == COLUMN_LABEL:
            if not e_value:
                model.set(itr, COLUMN_LABEL, "")
            else:
                new_text = misc.slugify(new_text, empty='E%d' % path)
                model.set(itr, COLUMN_LABEL, new_text)

    def set_parameters(self, info):
        for key in ['distance', 'delta_angle', 'start_angle', 'total_angle', 'wedge', 'exposure_time', 'attenuation']:
            if key in info:
                self.entry[key].set_text("%0.2f" % info[key])
            else:
                self.entry[key].set_text("%0.2f" % DEFAULT_PARAMETERS[key])
        for key in ['first_frame', 'num_frames']:
            if key in info:
                self.entry[key].set_text("%d" % info[key])
            else:
                self.entry[key].set_text("%d" % DEFAULT_PARAMETERS[key])
        if 'total_angle' in info:
            self.entry['num_frames'].set_text('%d' % int(info['total_angle'] / info['delta_angle']))

        if 'name' in info:
            self.entry['name'].set_text("%s" % info['name'])
        if info.get('directory') is not None and os.path.exists(info['directory']):
            self.entry['directory'].set_current_folder("%s" % info['directory'])

        # always display up to date active crystal
        if self.active_sample:
            txt = '%s [ID:%s]' % (self.active_sample['name'], self.active_sample['id'])
            self.crystal_entry.set_text(txt)
        elif info.get('crystal_id'):
            txt = '[ID:%s]' % (info['crystal_id'])
            self.crystal_entry.set_text(txt)
        else:
            self.crystal_entry.set_text('[ Unknown ]')

        self.set_number(info['number'])
        self.entry['inverse_beam'].set_active(info['inverse_beam'])
        # self.entry['dafs'].set_active(info.get('dafs', False))

        # Add energy entries
        self._set_energies(info)

        self.entry['skip'].set_text(info.get('skip', ''))

        _cmt_buf = self.comments_entry.get_buffer()
        _cmt_buf.set_text(info.get('comments', ''))

        self.parameters.update(info)
        self.check_changes()

    def get_parameters(self):
        run_data = self.parameters.copy()

        run_data['name'] = self.entry['name'].get_text().strip()
        run_data['directory'] = self.entry['directory'].get_current_folder()
        energy = []
        energy_label = []
        model = self.energy_list.get_model()
        itr = model.get_iter_first()
        while itr:
            e = model.get_value(itr, COLUMN_ENERGY)
            n = model.get_value(itr, COLUMN_LABEL)
            if e is None:
                break
            energy.append(e)
            energy_label.append(n)
            itr = model.iter_next(itr)

        run_data['energy'] = energy
        run_data['energy_label'] = energy_label
        run_data['inverse_beam'] = self.entry['inverse_beam'].get_active()
        run_data['dafs'] = self.entry['dafs'].get_active()
        run_data['number'] = self.number
        run_data['two_theta'] = self.beamline.two_theta.get_position()

        for key in ['distance', 'delta_angle', 'start_angle', 'total_angle', 'wedge', 'exposure_time', 'attenuation']:
            run_data[key] = float(self.entry[key].get_text())

        for key in ['first_frame', 'num_frames']:
            run_data[key] = int(self.entry[key].get_text())

        for key in ['skip']:
            run_data[key] = self.entry[key].get_text()
        _cmt_buf = self.comments_entry.get_buffer()
        run_data['comments'] = _cmt_buf.get_text(_cmt_buf.get_start_iter(), _cmt_buf.get_end_iter())
        return run_data

    def is_enabled(self):
        return self.enable_btn.get_active()

    def disable_run(self):
        self.enable_btn.set_active(False)

    def enable_run(self):
        self.enable_btn.set_active(True)

    def set_number(self, num=0):
        self.number = num
        self.parameters['number'] = num
        self.run_title.set_text('<big><b>Run %d</b></big>' % self.number)
        self.run_title.set_use_markup(True)
        # Hide controls for Run 0
        if num == 0:
            #            for key in ['total_angle','num_frames','wedge','inverse_beam', 'skip']:
            #                self.entry[key].set_sensitive(False)
            self.energy_list.set_sensitive(False)
            self.comments_frame.hide()
            self.energy_view.hide()
            self.delete_btn.set_sensitive(False)
            if self.predictor is None:
                # add Predictor
                self.predictor = Predictor(self.beamline.detector.resolution, min(self.beamline.detector.size))
                self.predictor.set_size_request(180, 180)
                self.predictor.set_border_width(12)
                self.run_widget.pack_end(self.predictor, expand=True, fill=True)

    def update_active_data(self, sample=None, strategy=None):
        if sample is not None:
            self.active_sample = sample
            params = self.get_parameters()
            params['crystal_id'] = self.active_sample.get('id', None)
            params['experiment_id'] = self.active_sample.get('experiment_id', None)
            if self.active_sample.get('comments') is not None:
                params['comments'] = self.active_sample['comments']
            else:
                params['comments'] = ''
            self.set_parameters(params)
            self.check_changes()

        if strategy is not None:
            self.active_strategy = strategy

    def check_changes(self):
        new_values = self.get_parameters()
        if self.predictor is not None and self.number == 0:
            self.predictor.configure(distance=new_values['distance'],
                                     energy=self.beamline.energy.get_position(),
                                     two_theta=self.beamline.two_theta.get_position())

        for key in self.parameters.keys():
            # skip some keys 
            if key in ['energy_label', 'crystal_id', 'experiment_id', 'comments', 'two_theta', 'scattering_factors']:
                continue

            if key == 'energy':
                widget = None
                _energy_changed = False
                if len(new_values['energy']) != len(self.parameters['energy']):
                    _energy_changed = True
                else:
                    for i in range(len(new_values['energy'])):
                        if ((abs(new_values['energy'][i] - self.parameters['energy'][i]) > 0.0001) or
                                (new_values['energy_label'][i] != self.parameters['energy_label'][i])):
                            _energy_changed = True
                self._changes_pending = True
                self._set_energy_changed(_energy_changed)
                # self.energy_list.get_selection().unselect_all()
            elif key == 'number':
                widget = self.run_title
            elif key == 'directory':
                widget = self.entry['directory'].get_child()
            else:
                widget = self.entry[key]

            if widget is None:
                continue
            if new_values[key] != self.parameters.get(key):
                widget.modify_text(gtk.STATE_NORMAL, gtk.gdk.color_parse("magenta"))
                widget.modify_fg(gtk.STATE_NORMAL, gtk.gdk.color_parse("magenta"))
                self._changes_pending = True
            else:
                widget.modify_text(gtk.STATE_NORMAL, None)
                widget.modify_fg(gtk.STATE_NORMAL, None)
                self._changes_pending = False

    def on_energy_changed(self, widget, event=None):
        selection = self.energy_list.get_selection()
        selection.unselect_all()
        self.check_changes()

    def on_prefix_changed(self, widget, event=None):
        prefix = self.entry['name'].get_text()
        prefix = misc.slugify(prefix.strip(), empty="data")
        self.entry['name'].set_text(prefix)
        self.check_changes()

    def on_start_angle_changed(self, widget, event=None):
        try:
            start_angle = float(self.entry['start_angle'].get_text())
        except:
            start_angle = 0

        start_angle = min(360.0, max(-360.0, start_angle))
        if start_angle < 0:
            start_angle += 360.0
        self.entry['start_angle'].set_text('%0.2f' % start_angle)
        self.check_changes()
        return False

    def on_skip_changed(self, widget, event=None):
        try:
            skip = self.entry['skip'].get_text()
        except:
            skip = ''
        skip_list = []
        for w in skip.split(','):
            try:
                wi = map(int, w.split('-'))
                if len(wi) == 1:
                    skip_list.append('%d' % wi[0])
                elif len(wi) == 2:
                    skip_list.append('%d-%d' % (wi[0], wi[1]))
            except:
                pass

        skip = ','.join(skip_list)
        self.entry['skip'].set_text(skip)
        self.check_changes()
        return False

    def on_total_angle_changed(self, widget, event=None):
        delta = float(self.entry['delta_angle'].get_text())
        try:
            total_angle = float(self.entry['total_angle'].get_text())
            total_frames = int(total_angle / delta)
        except:
            total_frames = int(self.entry['num_frames'].get_text())
            total_angle = total_frames * delta

        self.entry['total_angle'].set_text('%0.2f' % total_angle)
        self.entry['num_frames'].set_text('%d' % total_frames)
        self.check_changes()
        return False

    def on_delta_changed(self, widget, event=None):

        max_dps = self.beamline.config.get('max_omega_velocity', 20.0)
        try:
            delta = float(self.entry['delta_angle'].get_text())
            time = float(self.entry['exposure_time'].get_text())
        except:
            delta = 1.0
        delta = min(360.0, max(delta, 0.05))
        self.entry['delta_angle'].set_text('%0.2f' % delta)
        total_angle = float(self.entry['total_angle'].get_text())
        total_frames = max(1, int(total_angle / delta))
        self.entry['total_angle'].set_text('%0.2f' % (total_frames * delta))
        self.entry['num_frames'].set_text('%d' % total_frames)
        new_time = round(delta / min(max_dps, delta / time), 1)
        if new_time != time:
            self.entry['exposure_time'].set_text('%0.2f' % new_time)
        self.check_changes()
        return False

    def on_time_changed(self, widget, event=None):
        """Check the validity of the exposure time and adjust both 
           time and delta to be compatible with the beamline maximum 
           omega velocity"""

        max_dps = self.beamline.config.get('max_omega_velocity', 20.0)
        delta = float(self.entry['delta_angle'].get_text())
        try:
            time = float(self.entry['exposure_time'].get_text())
        except:
            time = 1.0

        time = max(0.05, time)
        self.entry['exposure_time'].set_text('%0.2f' % round(time, 2))
        new_delta = round(time * min(max_dps, delta / time), 2)
        if new_delta != delta:
            self.entry['delta_angle'].set_text('%0.2f' % new_delta)
        self.check_changes()
        return False

    def on_start_frame_changed(self, widget, event=None):
        try:
            start_frame = int(float(self.entry['first_frame'].get_text()))
        except:
            start_frame = 1

        start_frame = max(start_frame, 1)
        self.entry['first_frame'].set_text('%d' % start_frame)
        self.check_changes()
        return False

    def on_total_frames_changed(self, widget, event=None):
        delta = float(self.entry['delta_angle'].get_text())
        try:
            total_frames = max(1, int(self.entry['num_frames'].get_text()))
            total_angle = total_frames * delta
        except:
            total_angle = float(self.entry['total_angle'].get_text())
            total_frames = int(total_angle / delta)

        self.entry['num_frames'].set_text('%d' % total_frames)
        self.entry['total_angle'].set_text('%0.2f' % total_angle)
        self.check_changes()
        return False

    def on_wedge_changed(self, widget, event=None):
        try:
            wedge = float(self.entry['wedge'].get_text())
        except:
            wedge = 360.0
        wedge = min(max(1.0, wedge), 360.0)
        self.entry['wedge'].set_text('%0.2f' % wedge)
        self.check_changes()
        return False

    def on_attenuation_changed(self, widget, event=None):
        try:
            attenuation = float(self.entry['attenuation'].get_text())
        except:
            attenuation = 0.0
        attenuation = max(0.0, min(100.0, attenuation))
        self.entry['attenuation'].set_text('%0.0f' % attenuation)
        self.check_changes()
        return False

    def on_distance_changed(self, widget, event=None):
        two_theta = self.parameters.get('two_theta', 0)
        try:
            distance = float(self.entry['distance'].get_text())
        except:
            distance = 250.0

        if two_theta <= 20.0:
            d_min = 100.0
        elif two_theta <= 34.0:
            d_min = (70.0 / 14.0) * (two_theta - 20.0) + 100.0
        else:
            d_min = 100.0

        if two_theta == 0:
            d_max = 1000.0
        elif two_theta <= 18.0:
            d_max = 850.0
        elif two_theta <= 34.0:
            d_max = (680 / -16.0) * (two_theta - 18.0) + 850.0
        else:
            d_max = 1000.0

        distance = max(d_min, min(distance, d_max))

        self.entry['distance'].set_text('%0.1f' % distance)
        self.check_changes()
        return False

    def on_folder_changed(self, obj):
        self.check_changes()

    def on_save(self, widget):
        self.enable_btn.set_active(True)
        entry = self.get_toplevel().get_focus()
        if isinstance(entry, gtk.Entry):
            entry.activate()
        self.parameters = self.get_parameters()
        self.check_changes()
        return True

    def on_reset_parameters(self, obj):
        params = self.get_parameters()
        for k in ['attenuation', 'distance', 'two_theta', 'energy', 'energy_label',
                  'start_angle', 'delta_angle', 'total_angle', 'first_frame', 'skip', 'wedge', 'inverse_beam']:
            params[k] = DEFAULT_PARAMETERS[k]
        params['exposure_time'] = self.beamline.config['default_exposure']
        params['crystal_id'] = self.active_sample.get('id', None)

        self.set_parameters(params)
        self.check_changes()
        return True

    def on_update_parameters(self, obj):
        params = self.get_parameters()
        if self.active_sample:
            params['name'] = self.active_sample.get('name', params['name'])
        params['distance'] = self.active_strategy.get('distance', self.beamline.distance.get_position())
        params['attenuation'] = self.active_strategy.get('attenuation', self.beamline.attenuator.get())
        params['two_theta'] = self.beamline.two_theta.get_position()
        params['energy'] = self.active_strategy.get('energy', [self.beamline.energy.get_position()])
        params['energy_label'] = self.active_strategy.get('energy_label', ['E0'])
        params['start_angle'] = self.active_strategy.get('start_angle', self.beamline.omega.get_position())
        params['delta_angle'] = self.active_strategy.get('delta_angle', 1.0)
        params['exposure_time'] = self.active_strategy.get('exposure_time', self.beamline.config['default_exposure'])
        params['total_angle'] = self.active_strategy.get('total_angle', 180.0)
        params['first_frame'] = 1
        params['skip'] = ""
        params['wedge'] = 360.0
        params['inverse_beam'] = False
        params['scattering_factors'] = self.active_strategy.get('scattering_factors', None)
        self.set_parameters(params)
        self.check_changes()
        return True
