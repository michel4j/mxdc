import time
import uuid

from gi.repository import Gtk, Gdk, GObject, Gio
from twisted.python.components import globalRegistry

from mxdc.beamlines.mx import IBeamline
from mxdc.utils import gui, converter, datatools, glibref, misc
from mxdc.utils.datatools import StrategyType, Strategy


def calculate_skip(strategy, delta, first):
    if strategy in [StrategyType.FULL, StrategyType.SINGLE, StrategyType.POWDER]:
        return ''
    elif strategy == StrategyType.SCREEN_4:
        return '{}-{},{}-{},{}-{}'.format(
            first + int(2 / delta),
            first + int(90 / delta) - 1,
            first + int(92 / delta),
            first + int(180 / delta) - 1,
            first + int(182 / delta),
            first + int(270 / delta) - 1,
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
    uuid = GObject.Property(type=str, default="")
    progress = GObject.Property(type=float, default=0.0)
    warning = GObject.Property(type=str, default="")
    title = GObject.Property(type=str, default="Add run ...")
    subtitle = GObject.Property(type=str, default="")
    created = GObject.Property(type=float, default=0.0)

    def __init__(self, info=None, state=StateType.DRAFT, uid=None, created=None):
        super(RunItem, self).__init__()
        self.connect('notify::info', self.info_changed)
        self.frames = []
        self.collected = set()
        self.props.created = created if created else time.time()
        self.props.uuid = uid if uid else str(uuid.uuid4())
        self.props.state = state
        self.props.info = info

    def info_changed(self, *args, **kwargs):
        if self.props.info:
            self.frames = datatools.generate_frame_names(self.props.info)
            self.props.size = len(self.frames)
            if len(self.frames):
                self.props.title = '{},...'.format(self.frames[0])
            else:
                self.props.title = '...'
            self.props.subtitle = '{} \xc3\x97 {:0.4g}\xc2\xb0/{:0.2g}s  @ {:0.5g} keV'.format(
                self.props.size, self.props.info.get('delta'), self.props.info.get('exposure'),
                self.props.info.get('energy')
            )

    def set_collected(self, frame):
        state = self.props.state
        self.collected.add(frame)
        prog = (100.0 * len(self.collected)) / len(self.frames)
        self.props.progress = prog
        if 0.0 < prog < 100.0:
            self.props.state = RunItem.StateType.ACTIVE
        elif prog == 100.0:
            self.props.state = RunItem.StateType.COMPLETE

        return state != self.props.state  # return True if state changed

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


def exclude_by_value(model, column):
    """Generate a model from another model filtering by the boolean value of a specified column"""
    filter_model = model.filter_new()
    filter_model.set_visible_func(lambda model, itr, data: bool(model[itr][2]) in [0, column])
    return filter_model


class DataEditor(gui.BuilderMixin):
    gui_roots = {
        'data/data_form': ['data_form']
    }
    Specs = {
        # field: ['field_type', format, type, default]
        'resolution': ['entry', '{:0.1f}', float, 2.0],
        'delta': ['entry', '{:0.3g}', float, None],
        'range': ['entry', '{:0.4g}', float, 1.],
        'start': ['entry', '{:0.4g}', float, 0.],
        'wedge': ['entry', '{:0.4g}', float, 360.],
        'energy': ['entry', '{:0.3f}', float, 12.658],
        'distance': ['entry', '{:0.1f}', float, 200],
        'exposure': ['entry', '{:0.3g}', float, None],
        'attenuation': ['entry', '{:0.3g}', float, 0.0],
        'first': ['entry', '{}', int, 1],
        'frames': ['entry', '{}', int, ''],
        'name': ['entry', '{}', str, ''],
        'strategy': ['cbox', '{}', int, StrategyType.SINGLE],
        'point': ['pbox', '{}', tuple, None],
        'end_point': ['pbox', '{}', tuple, None],
        'vector_size': ['spin', '{}', int, 10],
    }
    disabled = []
    use_dialog = False

    def __init__(self):
        self.setup_gui()
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.points = Gtk.ListStore(str, object, int)
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
        info['distance'] = round(
            converter.resol_to_dist(info['resolution'], self.beamline.detector.mm_size, info['energy']), 1
        )
        defaults = self.get_default(info['strategy'])

        for name, details in self.Specs.items():
            field_type, fmt, conv, default = details
            field_name = 'data_{}_{}'.format(name, field_type)
            if default is None:
                default = defaults.get(field_name)
            value = info.get(name, default)
            field = getattr(self, field_name, None)
            if not field: continue
            with field.handler_block(self.handlers[name]):
                if field_type == 'entry':
                    field.set_text(fmt.format(value))
                elif field_type == 'check':
                    field.set_active(value)
                elif field_type == 'spin':
                    field.set_value(value)
                elif field_type == 'cbox':
                    field.set_active_id(str(value))
                elif field_type == 'pbox' and field.get_model():
                    if value:
                        point_name, point = value
                        field.set_active_id(point_name)
                    else:
                        field.set_active_id(None)
            if name in self.disabled:
                field.set_sensitive(False)

        if 'name' not in self.disabled:
            name_valid = bool(info.get('name'))
            if name_valid:
                self.data_name_entry.get_style_context().remove_class('warning')
            else:
                self.data_name_entry.get_style_context().add_class('warning')

        self.exposure_rate = info['delta']/float(info['exposure'])

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
            try:
                value = conv(raw_value)
            except (TypeError, ValueError):
                value = default
            info[name] = value

        # Fill in defaults
        defaults = self.get_default(info.get('strategy', 1))
        for k,v in info.items():
            if v is None:
                info[k] = defaults.get(k)

        # Calculate skip,
        info.update({
            'skip': calculate_skip(info['strategy'], info['delta'], info['first']),
            'strategy_desc': Strategy[info['strategy']]['desc'],
            'activity': Strategy[info['strategy']]['activity'],
        })

        # make sure point is not empty if end_point is set
        if info.get('end_point') and not info.get('point'):
            info['point'] = info.pop('end_point')

        return info

    def get_default(self, strategy_type=StrategyType.SINGLE):
        default = {
            name: details[-1] for name, details in self.Specs.items()
        }
        info = Strategy[strategy_type]
        delta, exposure = self.beamline.config['default_delta'], self.beamline.config['default_delta']
        rate = delta/float(exposure)
        if 'delta' not in info:
            info['delta'] = delta
        if 'exposure' not in info:
            info['exposure'] = info['delta']/rate
        default.update(info)
        default['skip'] = calculate_skip(strategy_type, default['delta'], default['first'])
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
                self.handlers[name] = field.connect('activate', self.on_entry_changed, name)
            elif field_type in ['cbox', 'pbox']:
                self.handlers[name] = field.connect('changed', self.on_entry_changed, None, name)
            elif field_type in ['spin']:
                self.handlers[name] = field.connect('value-changed', self.on_entry_changed, None, name)
            else:
                self.handlers[name] = field.connect('activate', self.on_entry_changed, None, name)
                field.connect('focus-out-event', self.on_entry_changed, name)
        for id, params in Strategy.items():
            field_name = 'data_strategy_cbox'
            field = getattr(self, field_name)
            field.append(str(id), params['desc'])

    def on_dir_template(self, btn):
        app = Gio.Application.get_default()
        app.activate_action('preferences')

    def on_entry_changed(self, obj, event, field_name):
        new_values = self.get_parameters()
        if field_name == 'name':
            new_values['name'] = misc.slugify(new_values['name'])
        if field_name in ['resolution', 'energy']:
            min_e, max_e = self.beamline.config['energy_range']
            min_d, max_d = self.beamline.config['distance_limits']

            # calculate resolution limits dynamically based on energy
            min_res = converter.dist_to_resol(min_d, self.beamline.detector.mm_size, new_values['energy'])
            max_res = converter.dist_to_resol(max_d, self.beamline.detector.mm_size, new_values['energy'])

            new_values['resolution'] = max(min_res, min(max_res, new_values['resolution']))
            new_values['energy'] = max(min_e, min(max_e, new_values['energy']))
            new_values['distance'] = converter.resol_to_dist(
                new_values['resolution'], self.beamline.detector.mm_size, new_values['energy']
            )

        elif field_name == 'strategy':
            defaults = Strategy.get(new_values['strategy'])
            default_rate = self.beamline.config['default_delta']/float(self.beamline.config['default_exposure'])
            if 'delta' in defaults and 'exposure' not in defaults:
                defaults['exposure'] = defaults['delta']/default_rate
            elif 'exposure' in defaults and 'delta' not in defaults:
                defaults['delta'] = default_rate/defaults['exposure']
            new_values.update(defaults)
        elif field_name == 'delta':
            new_values['delta'] = min(720.0, max(new_values['delta'], 0.01))
            new_values['exposure'] = new_values['delta']/self.exposure_rate
        elif field_name == 'range':
            new_values['range'] = min(1440.0, max(new_values['range'], 0.01))
        elif field_name == 'attenuation':
            new_values['attenuation'] = min(100.0, max(new_values['attenuation'], 0.0))
        elif field_name == 'first':
            new_values['first']  = max(1, new_values['first'])

        self.configure(new_values)

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
            return any(v != new_values.get(k) for k, v in info.items())
        elif self.item:
            return True
        return False


class RunEditor(DataEditor):
    class Column:
        NAME, COORDS, CHOICE = range(3)

    def build_gui(self):
        super(RunEditor, self).build_gui()
        self.points.connect('row-changed', self.on_points_updated)
        self.points.connect('row-deleted', self.on_points_updated)
        self.points.connect('row-inserted', self.on_points_updated)
        adjustment = Gtk.Adjustment(10, 2, 100, 1, 5, 0)
        self.data_vector_size_spin.set_adjustment(adjustment)
        self.data_end_point_pbox.bind_property(
            'active-id', self.data_vector_size_spin, 'sensitive', 0, lambda x, y: bool(y)
        )
        self.data_vector_size_spin.bind_property(
            'sensitive', self.data_wedge_entry, 'sensitive', 0,  lambda x, y: not y
        )
        for i, field_name in enumerate(['point', 'end_point']):
            field_name = 'data_{}_pbox'.format(field_name)
            field = getattr(self, field_name, None)
            if not field: continue
            renderer_text = Gtk.CellRendererText()
            field.pack_start(renderer_text, True)
            field.add_attribute(renderer_text, "text", self.Column.NAME)
            choice_column = i + 1
            field.set_model(self.points)
            field.set_id_column(self.Column.NAME)
            field.connect('changed', self.sync_choices, choice_column)

    def add_point(self, name, point):
        if not len(self.points):
            self.points.append([None, None, 0])
        names = self.get_point_names()
        if not name in names:
            self.points.append([name, point,  0])

    def set_points(self, points):
        if not points:
            self.clear_points()
        else:
            for i, point in enumerate(points):
                self.add_point('P{}'.format(i+1), points[i])

    def get_point(self, name):
        value = None

        if name:
            for row in self.points:
                if row[self.Column.NAME] == name:
                    value = (name, row[self.Column.COORDS])
                    break
        return value

    def get_point_names(self):
        return {row[self.Column.NAME] for row in self.points}

    def sync_choices(self, obj, column):
        name = obj.get_active_id()
        self.select_point(name, column)

    def select_point(self, name, column):
        for row in self.points:
            if name and row[self.Column.NAME] == name:
                row[2] = column
            elif row[2] == column:
                row[2] = 0

    def clear_points(self):
        self.points.clear()

    def on_points_updated(self, *args, **kwargs):
        num_points = len(self.points)
        self.data_vector_box.set_sensitive(num_points > 0)
        self.data_end_point_pbox.set_sensitive(num_points > 1)


class DataDialog(DataEditor):
    gui_roots = {
        'data/data_dialog': ['data_dialog'],
        'data/data_form': ['data_form_fields'],
    }
    disabled = ['name', 'inverse']
    use_dialog = True

    def build_gui(self):
        self.popover = self.data_dialog
        self.content_box.pack_start(self.data_form_fields, True, True, 0)
        super(DataDialog, self).build_gui()
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
            self.data_title.set_markup('Add run ...')
            self.data_subtitle.set_text('')
            self.data_title_box.set_orientation(Gtk.Orientation.HORIZONTAL)
        else:
            self.data_title.set_markup('{} [{}]'.format(self.item.title, self.item.info.get('strategy_desc', '')))
            self.data_subtitle.set_text(self.item.subtitle)
            self.data_title_box.set_orientation(Gtk.Orientation.VERTICAL)
