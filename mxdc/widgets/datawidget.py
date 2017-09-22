import time
import uuid

from gi.repository import Gtk, Gdk, GObject
from mxdc.beamline.mx import IBeamline
from mxdc.utils import gui, converter, datatools, glibref, misc
from mxdc.utils.datatools import StrategyType, Strategy
from twisted.python.components import globalRegistry



def _calc_skip(strategy, delta, first):
    if strategy in [StrategyType.FULL, StrategyType.SINGLE, StrategyType.POWDER]:
        return ''
    elif strategy == StrategyType.SCREEN_4:
        return '{}-{},{}-{},{}-{}'.format(
            first + int(2 / delta),
            first + int(45 / delta) - 1,
            first + int(47 / delta),
            first + int(90 / delta) - 1,
            first + int(92 / delta),
            first + int(180 / delta) - 1
        )

    elif strategy == StrategyType.SCREEN_3:
        return '{}-{},{}-{}'.format(
            first + int(2 / delta),
            first + int(45 / delta) - 1,
            first + int(47 / delta),
            first + int(90 / delta) - 1,
        )
    elif strategy == StrategyType.SCREEN_2:
        return '{}-{}'.format(
            first + int(2 / delta),
            first + int(90 / delta) - 1,
        )


class RunItem(GObject.GObject):
    class StateType:
        (ADD, DRAFT, ACTIVE, ERROR, COMPLETE) = range(5)

    state = GObject.Property(type=int, default=StateType.DRAFT)
    position = GObject.Property(type=int, default=0)
    size = GObject.Property(type=int, default=0)
    info = GObject.Property(type=object)
    progress = GObject.Property(type=float, default=0.0)
    warning = GObject.Property(type=str, default="")
    title = GObject.Property(type=str, default="Add run ...")
    subtitle = GObject.Property(type=str, default="")
    created = GObject.Property(type=float, default=0.0)

    def __init__(self, info=None, state=StateType.DRAFT):
        super(RunItem, self).__init__()
        self.frames = []
        self.collected = set()

        self.connect('notify::info', self.on_info_changed)
        self.props.state = state
        self.props.info = info
        self.props.created = time.time()
        self.uuid = str(uuid.uuid4())
        self.title = '...'
        self.subtitle = '...'

    def on_info_changed(self, item, param):
        if self.props.info:
            self.frames = datatools.generate_frame_names(self.props.info)
            self.props.size = len(self.frames)
            self.props.title = '{},...'.format(self.frames[0])
            self.props.subtitle = '{} \xc3\x97 {:0.2g}\xc2\xb0/{:0.2g}s  @ {:0.5g} keV'.format(
                self.props.size, self.props.info.get('delta'), self.props.info.get('exposure'), self.props.info.get('energy')
            )

    def set_collected(self, frame):
        self.collected.add(frame)
        prog = (100.0 * len(self.collected)) / len(self.frames)
        self.props.progress = prog
        if 0.0 < prog < 100.0:
            self.props.state = RunItem.StateType.ACTIVE
        elif prog == 100.0:
            self.props.state = RunItem.StateType.COMPLETE

    @staticmethod
    def sorter(a_pointer, b_pointer):

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
        return Gdk.RGBA(*STATE_COLORS[self.props.state])

    def __getitem__(self, item):
        if self.props.info:
            return self.props.info[item]

    def __str__(self):
        return '<Run Item: {} - {}|{}>'.format(self.props.position, self.props.title, self.props.subtitle)


STATE_COLORS = {
    RunItem.StateType.ADD: (1.0, 1.0, 1.0, 0.0),
    RunItem.StateType.DRAFT: (1.0, 1.0, 1.0, 0.0),
    RunItem.StateType.ACTIVE: (1.0, 1.0, 0.0, 0.1),
    RunItem.StateType.COMPLETE: (0.2, 1.0, 0.2, 0.5),
    RunItem.StateType.ERROR: (1.0, 0.0, 0.5, 0.1),
}

STATE_PROPERTIES = {
    RunItem.StateType.ADD: ('add-tool', 'list-add-symbolic'),
    RunItem.StateType.DRAFT: ('draft-run', 'content-loading-symbolic'),
    RunItem.StateType.ACTIVE: ('active-run', 'emblem-synchronizing-symbolic'),
    RunItem.StateType.COMPLETE: ('complete-run', 'object-select-symbolic'),
    RunItem.StateType.ERROR: ('error-run', 'dialog-warning-symbolic'),
}


def exlude_by_column(model, column, invert=True):
    """Generate a model from another model filtering by the boolean value of a specified column"""
    filter_model = model.filter_new()
    filter_model.set_visible_func(lambda model, itr, data: bool(model[itr][column]) != invert)
    return filter_model


class DataEditor(gui.BuilderMixin):
    gui_roots = {
        'data/data_form': ['data_form']
    }
    Specs = {
        # field: ['field_type', format, type, default]
        'resolution': ['entry', '{:0.1f}', float, 2.0],
        'delta': ['entry', '{:0.3g}', float, 1.0],
        'range': ['entry', '{:0.4g}', float, 1.],
        'start': ['entry', '{:0.4g}', float, 0.],
        'wedge': ['entry', '{:0.4g}', float, 360.],
        'energy': ['entry', '{:0.3f}', float, 12.658],
        'distance': ['entry', '{:0.1f}', float, 200],
        'exposure': ['entry', '{:0.3g}', float, 1.0],
        'attenuation': ['entry', '{:0.3g}', float, 0.0],
        'first': ['entry', '{}', int, 1],
        'frames': ['entry', '{}', int, ''],
        'name': ['entry', '{}', str, ''],
        'strategy': ['cbox', '{}', int, StrategyType.SINGLE],
        'inverse': ['check', '{}', bool, False],
        'point': ['pbox', '{}', tuple, None],
        'end_point': ['pbox', '{}', tuple, None],
        'vector_size': ['spin', '{}', int, 10],
    }
    disabled = []
    use_dialog = False

    def __init__(self):
        self.setup_gui()
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.points = Gtk.ListStore(str, object, bool, bool)
        self.new_run = True
        self.run_index = 0
        self.item = None
        self.item_links = []
        self.build_gui()

    def set_item(self, item):
        for link in self.item_links:
            self.item.handler_disconnect(link)
        self.item = item
        self.update()
        self.data_save_btn.set_sensitive(True)

        self.item_links = [
            self.item.connect('notify::state', self.update),
            self.item.connect('notify::info', self.update),
        ]

    def configure(self, info):
        frames = datatools.generate_frame_names(info)
        info['frames'] = len(frames)
        info['distance'] = round(
            converter.resol_to_dist(info['resolution'], self.beamline.detector.mm_size, info['energy']), 1
        )

        for name, details in self.Specs.items():
            field_type, fmt, conv, default = details
            field_name = 'data_{}_{}'.format(name, field_type)
            value = info.get(name, default)
            field = getattr(self, field_name, None)
            if not field: continue
            if field_type == 'entry':
                field.set_text(fmt.format(value))
            elif field_type == 'check':
                field.set_active(value)
            elif field_type == 'spin':
                field.set_value(value)
            elif field_type == 'cbox':
                field.set_active_id(str(value))
            elif field_type == 'pbox':
                if value:
                    name, point = value
                    field.set_active_id(name)
                else:
                    field.set_active_id(None)
            if name in self.disabled:
                field.set_sensitive(False)

        if 'name' not in self.disabled:
            name_exists = bool(info.get('name'))
            self.data_save_btn.set_sensitive(name_exists and self.has_changed(info))
            if not name_exists:
                self.data_name_entry.get_style_context().add_class('error')
            else:
                self.data_name_entry.get_style_context().remove_class('error')
        if self.use_dialog:
            self.data_save_btn.set_sensitive(True)


    def get_parameters(self):
        info = {}
        for name, details in self.Specs.items():
            field_type, fmt, conv, default = details
            field_name = 'data_{}_{}'.format(name, field_type)
            field = getattr(self, field_name, None)
            if not field: continue
            raw_value = default
            if field_type == 'entry':
                raw_value = field.get_text()
            elif field_type == 'switch':
                raw_value = field.get_active()
            elif field_type == 'cbox':
                raw_value = field.get_active_id()
            elif field_type == 'spin':
                raw_value = field.get_value()
            elif field_type == 'pbox':
                point_name = field.get_active_id()
                raw_value = self.get_point(point_name)
                if not raw_value: continue
            try:
                value = conv(raw_value)
            except (TypeError, ValueError):
                value = default

            info[name] = value

        # Calculate skip,
        info.update({
            'skip': _calc_skip(info['strategy'], info['delta'], info['first']),
            'strategy_desc': Strategy[info['strategy']]['desc'],
            'activity': Strategy[info['strategy']]['activity'],
        })

        # make sure point is not empty if end_point is set
        if info.get('end_point') and not info.get('point'):
            info['point'] = info.pop('end_point')

        return info

    @classmethod
    def get_default(cls, strategy_type=StrategyType.SINGLE, delta=None):
        default = {
            name: details[-1] for name, details in cls.Specs.items()
        }
        info = Strategy[strategy_type]
        default.update(info)
        if delta:
            default['delta'] = delta
        default['skip'] = _calc_skip(strategy_type, default['delta'], default['first'])
        default.update(Strategy[strategy_type])
        default['strategy_desc'] = default.pop('desc')
        return default

    def build_gui(self):
        for name, details in self.Specs.items():
            field_type, fmt, conv, default = details
            field_name = 'data_{}_{}'.format(name, field_type)
            field = getattr(self, field_name, None)
            if not field: continue
            if field_type in ['switch']:
                field.connect('activate', self.on_entry_changed, name)
            elif field_type in ['cbox', 'pbox']:
                field.connect('changed', self.on_entry_changed, None, name)
            else:
                field.connect('activate', self.on_entry_changed, None, name)
                field.connect('focus-out-event', self.on_entry_changed, name)
        for id, params in Strategy.items():
            field_name = 'data_strategy_cbox'
            field = getattr(self, field_name)
            field.append(str(id), params['desc'])

    def on_entry_changed(self, obj, event, field_name):
        new_values = self.get_parameters()
        if field_name == 'name':
            new_values['name'] = misc.slugify(new_values['name'])
        if field_name in ['resolution', 'energy']:
            new_values['distance'] = converter.resol_to_dist(
                new_values['resolution'], self.beamline.detector.mm_size, new_values['energy']
            )
            new_values[field_name] = round(new_values[field_name], 1)
        elif field_name == 'strategy':
            defaults = Strategy.get(new_values['strategy'])
            if new_values['strategy'] == StrategyType.FULL:
                defaults['delta'] = self.beamline.config['default_delta']
            if new_values['strategy'] not in [StrategyType.SINGLE, StrategyType.POWDER]:
                defaults['exposure'] = self.beamline.config['default_exposure']
            new_values.update(defaults)
        elif field_name == 'end_point':
            if new_values.get('end_point'):
                self.data_vector_size_spin.set_sensitive(True)
            else:
                self.data_vector_size_spin.set_sensitive(False)

        self.configure(new_values)

    def update(self, *args, **kwargs):
        if self.item.props.state == RunItem.StateType.ADD:
            self.run_label.set_text('New Run')
            self.data_delete_btn.set_sensitive(False)
            self.data_copy_btn.set_sensitive(False)
        else:
            self.run_label.set_text('Edit Run')
            self.configure(self.item.info)
            self.data_delete_btn.set_sensitive(True)
            self.data_copy_btn.set_sensitive(True)

    def has_changed(self, new_values):
        if self.item and self.item.info:
            info = self.item.info
            return set(info.items()) - set(new_values.items())
        elif self.item:
            return True


class RunEditor(DataEditor):
    class Column:
        NAME, COORDS, CHOICE1, CHOICE2 = range(4)

    def build_gui(self):
        super(RunEditor, self).build_gui()
        self.points.connect('row-changed', self.on_points_updated)
        self.points.connect('row-deleted', self.on_points_updated)
        self.points.connect('row-inserted', self.on_points_updated)
        adjustment = Gtk.Adjustment(10, 2, 100, 1, 5, 0)
        self.data_vector_size_spin.set_adjustment(adjustment)
        for i, field_name in enumerate(['point', 'end_point']):
            field_name = 'data_{}_pbox'.format(field_name)
            field = getattr(self, field_name, None)
            if not field: continue
            renderer_text = Gtk.CellRendererText()
            field.pack_start(renderer_text, True)
            field.add_attribute(renderer_text, "text", self.Column.NAME)
            choice_column = self.Column.CHOICE1 + i
            field.set_model(exlude_by_column(self.points, choice_column))
            field.set_id_column(self.Column.NAME)
            field.connect('changed', self.sync_choices, choice_column)

    def add_point(self, name, point):
        if not len(self.points):
            self.points.append([None, None, False, False])
        self.points.append([name, point, False, False])

    def get_point(self, name):
        value = None
        if name:
            for row in self.points:
                if row[self.Column.NAME] == name:
                    value = (name, row[self.Column.COORDS])
        return value

    def sync_choices(self, obj, column):
        name = obj.get_active_id()
        self.select_point(name, column)

    def select_point(self, name, column):
        for row in self.points:
            if name and row[self.Column.NAME] == name:
                for col in [self.Column.CHOICE1, self.Column.CHOICE2]:
                    row[col] = (col != column)
            else:
                row[self.Column.CHOICE1] = False
                row[self.Column.CHOICE2] = False

    def clear_points(self):
        self.points.clear()

    def on_points_updated(self, *args, **kwargs):
        num_points = len(self.points)
        self.data_vector_box.set_sensitive(num_points > 1)
        self.data_end_point_pbox.set_sensitive(num_points > 2)


class DataDialog(DataEditor):
    gui_roots = {
        'data/data_dialog': ['data_dialog'],
        'data/data_form': ['data_form_fields'],
    }
    disabled = ['name', 'inverse']
    use_dialog = True

    def build_gui(self):
        self.window = self.data_dialog
        self.window.set_property('use-header-bar', True)
        self.content_box.pack_start(self.data_form_fields, True, True, 0)
        super(DataDialog, self).build_gui()


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
            self.data_title.set_markup('Add run ...')
            self.data_subtitle.set_text('')
            self.data_title_box.set_orientation(Gtk.Orientation.HORIZONTAL)
        else:
            self.data_title.set_markup('{} [{}]'.format(self.item.title, self.item.info.get('strategy_desc', '')))
            self.data_subtitle.set_text(self.item.subtitle)
            self.data_title_box.set_orientation(Gtk.Orientation.VERTICAL)
