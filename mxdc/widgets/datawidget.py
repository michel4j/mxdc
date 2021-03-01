import time
import uuid

from gi.repository import Gtk, Gdk, Gio

from mxdc import Registry, IBeamline, Property, Object
from mxdc.devices.goniometer import GonioFeatures
from mxdc.utils import gui, converter, datatools, glibref
from mxdc.utils.datatools import StrategyType, Strategy
from mxdc.utils.gui import Validator


def calculate_skip(strategy, total_range, delta, first):
    if strategy in [StrategyType.FULL, StrategyType.SINGLE, StrategyType.POWDER]:
        return ''
    elif strategy == StrategyType.SCREEN_4:
        return '{}-{},{}-{},{}-{}'.format(
            first + int(total_range / delta),
            first + int(90 / delta) - 1,
            first + int((90 + total_range) / delta),
            first + int(180 / delta) - 1,
            first + int((180 + total_range) / delta),
            first + int(270 / delta) - 1,
        )

    elif strategy == StrategyType.SCREEN_3:
        return '{}-{},{}-{}'.format(
            first + int(total_range / delta),
            first + int(45 / delta) - 1,
            first + int((45 + total_range) / delta),
            first + int(90 / delta) - 1,
        )
    elif strategy == StrategyType.SCREEN_2:
        return '{}-{}'.format(
            first + int(total_range / delta),
            first + int(90 / delta) - 1,
        )


class RunItem(Object):
    class StateType:
        (ADD, DRAFT, ACTIVE, PAUSED, ERROR, COMPLETE) = range(6)

    state = Property(type=int, default=StateType.DRAFT)
    position = Property(type=int, default=0)
    size = Property(type=int, default=0)
    info = Property(type=object)
    uuid = Property(type=str, default="")
    progress = Property(type=float, default=0.0)
    warning = Property(type=str, default="")
    title = Property(type=str, default="Add run ...")
    subtitle = Property(type=str, default="")
    created = Property(type=float, default=0.0)

    def __init__(self, info=None, state=StateType.DRAFT, uid=None, created=None):
        super().__init__()
        self.connect('notify::info', self.info_changed)
        self.props.created = created if created else time.time()
        self.props.uuid = uid if uid else str(uuid.uuid4())
        self.props.state = state
        self.props.info = info

    def info_changed(self, *args, **kwargs):
        if self.props.info:
            self.props.size = datatools.count_frames(self.props.info)
            self.props.title = '{}_{:04d}, ...'.format(self.info['name'], self.info['first'])
            self.props.subtitle = '{}f {:0.4g}°/{:0.2g}s  @ {:0.5g} keV {}'.format(
                self.props.size, self.props.info.get('delta'), self.props.info.get('exposure'),
                self.props.info.get('energy'),
                '[INV]' if self.props.info.get('inverse') else ''
            )

    def set_progress(self, progress):
        state = self.props.state

        if state == RunItem.StateType.ADD:
            return False

        self.props.progress = progress
        if progress >= 0.95:
            self.props.state = RunItem.StateType.COMPLETE
        return state != self.props.state  # return True if state changed

    @staticmethod
    def sorter(a_pointer, b_pointer):
        # if objects correctly translated do not translate again
        if isinstance(a_pointer, RunItem):
            a = a_pointer
            b = b_pointer
        else:
            a = glibref.capi.to_object(a_pointer)
            b = glibref.capi.to_object(b_pointer)

        if a.props.state == b.props.state == RunItem.StateType.ADD:
            return 0
        elif a.props.state == RunItem.StateType.ADD:
            return 1
        elif b.props.state == RunItem.StateType.ADD:
            return -1
        else:
            if a.props.created > b.props.created:
                return 1
            elif a.props.created < b.props.created:
                return -1
            else:
                return 0

    def get_color(self):
        return Gdk.RGBA(*STATE_COLORS[self.state])

    def __getitem__(self, item):
        if self.props.info:
            return self.props.info[item]

    def __str__(self):
        return '<Run Item: {} - {}|{}>'.format(self.props.position, self.props.title, self.props.subtitle)


STATE_COLORS = {
    RunItem.StateType.ADD: (1.0, 1.0, 1.0, 0.0),
    RunItem.StateType.DRAFT: (1.0, 1.0, 1.0, 0.0),
    RunItem.StateType.ACTIVE: (1.0, 1.0, 0.0, 0.2),
    RunItem.StateType.PAUSED: (1.0, 1.0, 0.0, 0.1),
    RunItem.StateType.COMPLETE: (0.2, 1.0, 0.2, 0.5),
    RunItem.StateType.ERROR: (1.0, 0.0, 0.5, 0.1),
}

STATE_PROPERTIES = {
    RunItem.StateType.ADD: ('add-tool', 'list-add-symbolic'),
    RunItem.StateType.DRAFT: ('draft-run', 'content-loading-symbolic'),
    RunItem.StateType.ACTIVE: ('active-run', 'system-run-symbolic'),
    RunItem.StateType.PAUSED: ('paused-run', 'media-playback-pause-symbolic'),
    RunItem.StateType.COMPLETE: ('complete-run', 'object-select-symbolic'),
    RunItem.StateType.ERROR: ('error-run', 'dialog-warning-symbolic'),
}


class DataForm(gui.FormManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # update converters based on beamline configuration
        self.beamline = Registry.get_utility(IBeamline)
        self.fields['energy'].set_converter(
            Validator.Float(*self.beamline.config['energy_range'], self.beamline.config['default_energy'])
        )
        self.fields['distance'].set_converter(
            Validator.Float(*self.beamline.config['distance_limits'], self.beamline.config['default_distance'])
        )

        self.exposure_rate = 1.

    def on_change(self, field, event, name):
        super().on_change(field, event, name)

        if name == 'delta':
            delta = self.get_value('delta')
            exposure = delta / self.exposure_rate
            self.set_value('exposure', exposure)
        elif name == 'exposure':
            exposure = self.get_value('exposure')
            delta = self.get_value('delta')
            self.exposure_rate = delta / exposure
        elif name == 'energy':
            # calculate resolution limits based on energy
            energy = self.get_value('energy')
            resolution = self.get_value('resolution')
            min_res = converter.dist_to_resol(
                self.beamline.config['distance_limits'][0], self.beamline.detector.mm_size, energy
            )
            max_res = converter.dist_to_resol(
                self.beamline.config['distance_limits'][1], self.beamline.detector.mm_size, energy
            )
            self.fields['resolution'].set_converter(
                Validator.Float(min_res, max_res, default=2.0)
            )
            resolution = converter.dist_to_resol(self.get_value('distance'), self.beamline.detector.mm_size, energy)
            self.set_value('resolution', resolution)

        if name == 'resolution':
            resolution = self.get_value('resolution')
            energy = self.get_value('energy')
            distance = converter.resol_to_dist(resolution, self.beamline.detector.mm_size, energy)
            self.set_value('distance', distance)

        if name == 'strategy':
            strategy = self.get_value('strategy')
            defaults = Strategy.get(strategy)
            default_rate = self.beamline.config['default_delta'] / float(self.beamline.config['default_exposure'])
            if 'delta' in defaults and 'exposure' not in defaults:
                defaults['exposure'] = defaults['delta'] / default_rate
            elif 'exposure' in defaults and 'delta' not in defaults:
                defaults['delta'] = default_rate / defaults['exposure']
                self.exposure_rate = default_rate

            inverse = self.get_field('inverse')
            inverse.set_sensitive((strategy == StrategyType.FULL and 'inverse' not in self.disabled))
            self.set_values(defaults)

        if name == 'inverse':
            inverse = self.get_value('inverse')
            if inverse:
                self.set_value('range', min(180., self.get_value('range')))

        if name in ['delta', 'strategy', 'range', 'inverse']:
            range = self.get_value('range')
            inverse = self.get_value('inverse')
            if inverse:
                range = min(180., range)
                self.set_value('range', range)
            strategy = self.get_value('strategy')
            delta = self.get_value('delta')
            first = self.get_value('first')
            skip = calculate_skip(strategy, range, delta, first)
            frames = datatools.calc_num_frames(strategy, delta, range, skip=skip)
            self.set_value('frames', frames)


class DataEditor(gui.BuilderMixin):
    gui_roots = {
        'data/data_form': ['data_form']
    }

    class Column:
        ID, LABEL, VALUE = range(3)

    Fields = (
        gui.FieldSpec('resolution', 'entry', '{:0.3g}', Validator.Float(0.5, 50, 2.0)),
        gui.FieldSpec('delta', 'entry', '{:0.3g}', Validator.AngleFrac(0.001, 720, 1.)),
        gui.FieldSpec('range', 'entry', '{:0.4g}', Validator.Float(0.05, 10000, 1.)),
        gui.FieldSpec('start', 'entry', '{:0.4g}', Validator.Float(-360., 360., 0.)),
        gui.FieldSpec('wedge', 'entry', '{:0.4g}', Validator.Float(0.05, 720., 360.)),
        gui.FieldSpec('energy', 'entry', '{:0.3f}', Validator.Float(1.0, 25.0, 12.658)),
        gui.FieldSpec('distance', 'entry', '{:0.1f}', Validator.Float(50., 1000., 200)),
        gui.FieldSpec('exposure', 'entry', '{:0.3g}', Validator.Float(0.001, 720., 0.5)),
        gui.FieldSpec('attenuation', 'entry', '{:0.3g}', Validator.Float(0, 100, 0.0)),
        gui.FieldSpec('first', 'entry', '{}', Validator.Int(1, 10000, 1)),
        gui.FieldSpec('frames', 'entry', '{}', Validator.Int(1, 100000, 1)),
        gui.FieldSpec('name', 'entry', '{}', Validator.Slug(30)),
        gui.FieldSpec('strategy', 'cbox', '{}', Validator.Int(None, None, StrategyType.SINGLE)),
        gui.FieldSpec('inverse', 'check', '{}', Validator.Bool(False)),
        gui.FieldSpec('p0', 'mbox', '{}', Validator.Int(None, None)),
        gui.FieldSpec('p1', 'mbox', '{}', Validator.Int(None, None)),
        gui.FieldSpec('vector_size', 'spin', '{}', Validator.Int(1, 100, 10)),
    )
    disabled = ()
    use_dialog = False

    def __init__(self):
        self.setup_gui()
        self.beamline = Registry.get_utility(IBeamline)
        self.points = Gtk.ListStore(int, str, object)
        self.form = DataForm(self, fields=self.Fields, prefix='data', persist=False, disabled=self.disabled)
        self.new_run = True
        self.run_index = 0
        self.item = None
        self.item_links = []
        self.handlers = {}
        self.build_gui()
        self.exposure_rate = 1.0
        self.dir_template_btn.connect('clicked', self.on_dir_template)

    def set_item(self, item):
        if self.item:
            for link in self.item_links:
                self.item.handler_disconnect(link)
        self.item = item
        self.update()

        self.item_links = [
            self.item.connect('notify::state', self.update),
            self.item.connect('notify::info', self.update),
        ]

    def configure(self, info):
        info['frames'] = datatools.count_frames(info)
        info['distance'] = converter.resol_to_dist(info['resolution'], self.beamline.detector.mm_size, info['energy'])

        min_res = converter.dist_to_resol(
            self.beamline.config['distance_limits'][0], self.beamline.detector.mm_size, info['energy']
        )
        max_res = converter.dist_to_resol(
            self.beamline.config['distance_limits'][1], self.beamline.detector.mm_size, info['energy']
        )
        self.form.fields['resolution'].set_converter(
            Validator.Float(min_res, max_res, default=2.0)
        )

        defaults = self.get_default(info['strategy'])
        defaults.update(info)
        self.form.set_values(info)

        # disable/enable inverse field
        inverse = self.form.get_field('inverse')
        strategy = self.form.get_value('strategy')
        inverse.set_sensitive((strategy == StrategyType.FULL and 'inverse' not in self.disabled))

    def get_parameters(self):
        info = self.form.get_values()

        # Calculate skip,
        info.update({
            'skip': calculate_skip(info['strategy'], info['range'], info['delta'], info['first']),
            'strategy_desc': Strategy[info['strategy']]['desc'],
            'activity': Strategy[info['strategy']]['activity'],
        })

        return info

    def get_default(self, strategy_type=StrategyType.SINGLE):
        default = self.form.get_defaults()
        info = Strategy[strategy_type]
        delta, exposure = self.beamline.config['default_delta'], self.beamline.config['default_exposure']
        rate = delta / float(exposure)
        if 'delta' not in info:
            info['delta'] = delta
        if 'exposure' not in info:
            info['exposure'] = info['delta'] / rate
        default.update(info)
        default['skip'] = calculate_skip(strategy_type, default['range'], default['delta'], default['first'])
        default.update(Strategy[strategy_type])
        default['strategy_desc'] = default.pop('desc')
        return default

    def build_gui(self):
        strategy_field = self.form.get_field('strategy')
        for id, params in list(Strategy.items()):
            strategy_field.append(str(id), params['desc'])

    def set_points(self, points):
        self.points.clear()
        self.points.append([0, '', None])
        for i, point in enumerate(points):
            self.points.append([i, 'P{}'.format(i + 1), tuple(point)])

    def get_point(self, index):
        for i, row in enumerate(self.points):
            if i == index:
                return row[self.Column.VALUE]

    def on_dir_template(self, btn):
        app = Gio.Application.get_default()
        app.window.activate_action('preferences')

    def update(self, *args, **kwargs):
        if self.item.props.state == RunItem.StateType.ADD:
            self.run_label.set_text('New Run')
            self.data_delete_btn.set_sensitive(False)
            self.data_copy_btn.set_sensitive(False)
            self.data_form.set_sensitive(False)
        else:
            self.run_label.set_text('Edit Run')
            self.configure(self.item.info)
            self.data_delete_btn.set_sensitive(True)
            self.data_copy_btn.set_sensitive(True)
            self.data_form.set_sensitive(True)

    def has_changed(self, new_values):
        if self.item and self.item.info:
            info = self.item.info
            return any(v != new_values.get(k) for k, v in list(info.items()))
        elif self.item:
            return True
        return False


class RunEditor(DataEditor):

    def build_gui(self):
        super().build_gui()
        self.points.connect('row-changed', self.on_points_updated)
        self.points.connect('row-deleted', self.on_points_updated)
        self.points.connect('row-inserted', self.on_points_updated)

        adjustment = Gtk.Adjustment(10, 1, 100, 1, 5, 0)
        self.data_vector_size_spin.set_adjustment(adjustment)
        self.data_p1_mbox.bind_property(
            'active-id', self.data_vector_size_spin, 'sensitive', 0, lambda *args: bool(args[1])
        )
        # self.data_vector_size_spin.bind_property(
        #     'sensitive', self.data_wedge_entry, 'sensitive', 0, lambda *args: not args[1]
        # )
        for i, name in enumerate(['p0', 'p1']):
            field = self.form.get_field(name)
            if not field: continue
            renderer_text = Gtk.CellRendererText()
            field.pack_start(renderer_text, True)
            field.add_attribute(renderer_text, "text", self.Column.LABEL)
            field.set_model(self.points)
            field.set_id_column(self.Column.LABEL)
            # field.connect('changed', self.sync_choices, choice_column)

    def on_points_updated(self, *args, **kwargs):
        num_points = len(self.points)
        self.data_vector_box.set_sensitive(num_points > 1)

    def configure(self, info):
        super().configure(info)

        # disable/enable point fields
        num_points = len(self.points)
        self.data_vector_box.set_sensitive(num_points > 1)
        vector_size = self.form.get_field('vector_size')
        if self.beamline.goniometer.supports(GonioFeatures.SCAN4D):
            self.form.set_value('vector_size', 1)
            vector_size.set_sensitive(False)
        else:
            vector_size.set_sensitive(True)


class DataDialog(DataEditor):
    gui_roots = {
        'data/data_dialog': ['data_dialog'],
        'data/data_form': ['data_form_fields'],
    }
    disabled = ('name', 'inverse', 'energy')
    use_dialog = True

    def build_gui(self):
        self.popover = self.data_dialog
        self.content_box.pack_start(self.data_form_fields, True, True, 0)
        super().build_gui()
        self.data_cancel_btn.connect('clicked', lambda x: self.popover.hide())
        self.data_save_btn.connect_after('clicked', lambda x: self.popover.hide())


class RunConfig(gui.Builder):
    gui_roots = {
        'data/data_form': ['saved_run_row']
    }
    ROW_SIZE_GROUP = Gtk.SizeGroup(Gtk.SizeGroupMode.VERTICAL)

    def get_widget(self):
        row = Gtk.ListBoxRow()
        self.ROW_SIZE_GROUP.add_widget(row)
        row.get_style_context().add_class('run-row')
        row.add(self.saved_run_row)
        self.update()
        return row

    def set_item(self, item):
        self.item = item
        for param in ['state', 'title', 'progress', 'subtitle', 'info', 'position']:
            item.connect('notify::{}'.format(param), self.on_item_changed)

    def on_item_changed(self, item, param):
        self.update()

    def update(self):
        style_context = self.saved_run_row.get_style_context()
        for state, (style_class, icon_name) in STATE_PROPERTIES.items():
            if self.item.state == state:
                style_context.add_class(style_class)
                self.data_icon.set_from_icon_name(icon_name, Gtk.IconSize.SMALL_TOOLBAR)
            else:
                style_context.remove_class(style_class)

        if self.item.state == self.item.StateType.ADD:
            self.data_header.set_text('')
            self.data_title.set_markup('Add run ...')
            self.data_subtitle.set_text('')
        else:
            self.data_header.set_text(self.item.info.get('strategy_desc', ''))
            self.data_title.set_markup(f'<small><b>{self.item.title}</b></small>')
            self.data_subtitle.set_markup(f'<small>{self.item.subtitle}</small>')
