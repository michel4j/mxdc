import os
from datetime import date
import time
import uuid
import copy
from gi.repository import Gtk, Gdk, GObject
from mxdc.beamline.mx import IBeamline
from mxdc.utils import gui, converter, config, misc, runlists, glibref
from mxdc.utils.config import settings
from twisted.python.components import globalRegistry


class StrategyType(object):
    SINGLE, FULL, SCREEN_2, SCREEN_3, SCREEN_4, POWDER = range(6)


STRATEGIES = {
    StrategyType.SINGLE: {'range': 1.0, 'delta': 1.0, 'start': 0.0, 'helical': False, 'inverse': False,
                          'task': 'test', 'desc': 'Single Frame'},
    StrategyType.FULL: {'range': 180, 'desc': 'Full Dataset', 'task': 'data'},
    StrategyType.SCREEN_4: {'delta': 1.0, 'range': 182, 'start': 0.0, 'helical': False, 'inverse': False,
                            'desc': 'Screen 0\xc2\xb0, 45\xc2\xb0, 90\xc2\xb0, 180\xc2\xb0', 'task': 'screen'},
    StrategyType.SCREEN_3: {'delta': 1.0, 'range': 92, 'start': 0.0, 'helical': False, 'inverse': False,
                            'desc': 'Screen 0\xc2\xb0, 45\xc2\xb0, 90\xc2\xb0', 'task': 'screen'},
    StrategyType.SCREEN_2: {'delta': 1.0, 'range': 92, 'start': 0.0, 'helical': False, 'inverse': False,
                            'desc': 'Screen 0\xc2\xb0, 90\xc2\xb0', 'task': 'screen'},
    StrategyType.POWDER: {'delta': 180.0, 'exposure': 30.0, 'range': 360.0, 'helical': False, 'inverse': False,
                          'desc': 'Powder', 'task': 'data'}
}


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
        (ACTIVE, ERROR, DRAFT, ADD, COMPLETE) = range(5)

    state = GObject.Property(type=int, default=StateType.DRAFT)
    position = GObject.Property(type=int, default=0)
    info = GObject.Property(type=GObject.TYPE_PYOBJECT)
    progress = GObject.Property(type=float, default=0.0)
    warning = GObject.Property(type=str, default="")
    title = GObject.Property(type=str, default="Add run ...")
    subtitle = GObject.Property(type=str, default="")
    created = GObject.Property(type=float, default=0.0)

    def __init__(self, info=None, state=StateType.DRAFT):
        super(RunItem, self).__init__()
        self.frames = []
        self.collected = []

        self.connect('notify::info', self.on_info_changed)
        self.props.state = state
        self.props.info = info
        self.props.created = time.time()
        self.uuid = str(uuid.uuid4())
        self.title = '...'
        self.subtitle = '...'

    def on_info_changed(self, item, param):
        if self.props.info:
            self.frames = runlists.generate_frame_names(self.props.info)
            num_frames = len(self.frames)
            self.props.title = '{},...'.format( self.frames[0])
            self.props.subtitle = '{} \xc3\x97 {:0.2g}\xc2\xb0/{:0.2g}s  @ {:0.5g} keV'.format(
                num_frames, self.props.info.get('delta'), self.props.info.get('exposure'), self.props.info.get('energy')
            )

    def set_collected(self, frame):
        self.collected.append(frame)
        prog = 100.0 * len(self.collected)/len(self.frames)
        self.props.progress = prog
        if 0.0 < prog < 100.0:
            self.props.state = RunItem.StateType.ACTIVE
        elif prog == 100.0:
            self.props.state = RunItem.StateType.COMPLETE

    @staticmethod
    def sorter(a_pointer, b_pointer):

        a = glibref.capi.to_object(a_pointer)
        b = glibref.capi.to_object(b_pointer)

        if a.props.state < b.props.state:
            return -1
        elif a.props.state > b.props.state:
            return 1
        else:
            if a.props.created > b.props.created:
                return 1
            elif a.props.created < b.props.created:
                return -1
            else:
                return 0

    def get_color(self):
        return  Gdk.RGBA(*STATE_COLORS[self.props.state])

    def __getitem__(self, item):
        if self.props.info:
            return self.props.info[item]

    def __str__(self):
        return '<Run Item: {} - {}|{}>'.format(self.props.position, self.props.title, self.props.subtitle)


STATE_COLORS = {
    RunItem.StateType.ADD:       (1.0, 1.0, 1.0, 0.0),
    RunItem.StateType.DRAFT:     (1.0, 1.0, 1.0, 0.0),
    RunItem.StateType.ACTIVE:    (1.0, 1.0, 0.0, 0.1),
    RunItem.StateType.COMPLETE:  (0.2, 1.0, 0.2, 0.5),
    RunItem.StateType.ERROR:     (1.0, 0.0, 0.5, 0.1),
}


class DataEditor(gui.BuilderMixin):
    gui_roots = {
        'data/data_form': ['data_form']
    }
    Specs = {
        # field: ['field_type', format, type, default]
        'resolution': ['entry', '{:0.3g}', float, 2.0],
        'delta': ['entry', '{:0.3g}', float, 1.0],
        'range': ['entry', '{:0.4g}', float, 1.],
        'start': ['entry', '{:0.4g}', float, 0.],
        'wedge': ['entry', '{:0.4g}', float, 360.],
        'energy': ['entry', '{:0.5g}', float, 12.658],
        'distance': ['entry', '{:0.2f}', float, 200],
        'exposure': ['entry', '{:0.3g}', float, 1.0],
        'attenuation': ['entry', '{:0.3g}', float, 0.0],
        'first': ['entry', '{}', int, 1],
        'name': ['entry', '{}', str, ''],
        'strategy': ['cbox', '{}', int, StrategyType.SINGLE],
        'inverse': ['check', '{}', bool, False],
    }
    dialog_buttons = False

    def __init__(self):
        self.setup_gui()
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.new_run = True
        self.run_index = 0
        self.item = None
        self.item_link = None
        self.build_gui()

    def set_item(self, item):
        if self.item_link and self.item:
           self.item.handler_disconnect(self.item_link)

        self.item = item
        if item.props.state == RunItem.StateType.ADD:
            self.run_label.set_text('New Run')
            self.data_delete_btn.set_sensitive(False)
            self.data_copy_btn.set_sensitive(False)
        else:
            self.run_label.set_text('Edit Run: {}'.format(self.item.props.position))
            self.configure(item.info)
            self.data_delete_btn.set_sensitive(True)
            self.data_copy_btn.set_sensitive(True)
        self.data_save_btn.set_sensitive(True)

        self.item_link = self.item.connect('notify::state', self.on_item_state)

    def configure(self, info, disable=()):
        for name, details in self.Specs.items():
            field_type, fmt, conv, default = details
            field_name = 'data_{}_{}'.format(name, field_type)
            value = info.get(name, default)
            field = getattr(self, field_name)
            if field_type == 'entry':
                field.set_text(fmt.format(value))
            elif field_type == 'check':
                field.set_active(value)
            elif field_type == 'cbox':
                field.set_active_id(str(value))
            if name in disable:
                field.set_sensitive(False)
        name_exists = bool(info.get('name'))
        if self.has_changed(info) and name_exists:
            self.data_save_btn.set_sensitive(True)

    def get_parameters(self):
        info = {}
        for name, details in self.Specs.items():
            field_type, fmt, conv, default = details
            field_name = 'data_{}_{}'.format(name, field_type)
            field = getattr(self, field_name)
            raw_value = default
            if field_type == 'entry':
                raw_value = field.get_text()
            elif field_type == 'switch':
                raw_value = field.get_active()
            elif field_type == 'cbox':
                raw_value = field.get_active_id()

            try:
                value = conv(raw_value)
            except (TypeError, ValueError):
                value = default

            info[name] = value

        # Calculate skip,
        info.update({
            'skip': _calc_skip(info['strategy'], info['delta'], info['first']),
            'strategy_desc': STRATEGIES[info['strategy']]['desc'],
        })
        return info

    @classmethod
    def get_default(cls, strategy_type=StrategyType.SINGLE, delta=None):
        default = {
            name: details[-1] for name, details in cls.Specs.items()
        }
        info = STRATEGIES[strategy_type]
        default.update(info)
        if delta:
            default['delta'] = delta
        default['skip'] = _calc_skip(strategy_type, default['delta'], default['first'])
        default.update(STRATEGIES[strategy_type])
        default['strategy_desc'] = default.pop('desc')
        return default

    def build_gui(self):
        for name, details in self.Specs.items():
            field_type, fmt, conv, default = details
            field_name = 'data_{}_{}'.format(name, field_type)
            field = getattr(self, field_name)
            if field_type in ['switch']:
                field.connect('activate', self.on_entry_changed, name)
            elif field_type in ['cbox']:
                field.connect('changed', self.on_entry_changed, None, name)
            else:
                field.connect('activate', self.on_entry_changed, None, name)
                field.connect('focus-out-event', self.on_entry_changed, name)
        for id, params in STRATEGIES.items():
            field_name = 'data_strategy_cbox'
            field = getattr(self, field_name)
            field.append(str(id), params['desc'])

    def on_entry_changed(self, obj, event, field_name):
        new_values = self.get_parameters()
        if field_name in ['resolution', 'energy']:
            new_values['distance'] = converter.resol_to_dist(
                new_values['resolution'], self.beamline.detector.mm_size, new_values['energy']
            )
            new_values[field_name] = round(new_values[field_name], 1)
        elif field_name == 'strategy':
            defaults = STRATEGIES.get(new_values['strategy'])
            if new_values['strategy'] == StrategyType.FULL:
                defaults['delta'] = self.beamline.config['default_delta']
            if new_values['strategy'] in [StrategyType.FULL, StrategyType.SCREEN_4, StrategyType.SCREEN_3, StrategyType.SCREEN_2]:
                defaults['exposure'] = self.beamline.config['default_exposure']

            new_values.update(defaults)
        self.configure(new_values)

    def on_item_state(self, item, param):
        if self.item.props.state == RunItem.StateType.ADD:
            self.run_label.set_text('New Run')
            self.data_delete_btn.set_sensitive(False)
            self.data_copy_btn.set_sensitive(False)
        else:
            self.run_label.set_text('Edit Run: {}'.format(self.item.props.position))
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
    gui_roots = {
        'data/data_dialog': ['data_dialog'],
        'data/data_form': ['data_form_fields'],
    }
    dialog_buttons = True

    def build_gui(self):
        self.window = self.data_dialog
        self.window.set_property('use-header-bar', True)
        self.content_box.pack_start(self.data_form_fields, True, True, 0)
        super(RunEditor, self).build_gui()


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
        if self.item.state == self.item.StateType.ADD:
            self.saved_run_row.get_style_context().add_class('add-tool')
            self.data_title.set_markup('Add run ...')
            self.data_subtitle.set_text('')
            self.data_title_box.set_orientation(Gtk.Orientation.HORIZONTAL)
            self.data_icon.set_from_icon_name('list-add-symbolic', Gtk.IconSize.SMALL_TOOLBAR)
        else:
            self.saved_run_row.get_style_context().remove_class('add-tool')
            self.data_title.set_markup('{} [{}]'.format(
                self.item.title, self.item.info.get('strategy_desc', ''),
            ))
            self.data_subtitle.set_text(self.item.subtitle)
            self.data_title_box.set_orientation(Gtk.Orientation.VERTICAL)
            if self.item.state == self.item.StateType.DRAFT:
                self.data_icon.set_from_icon_name('content-loading-symbolic', Gtk.IconSize.SMALL_TOOLBAR)
            elif self.item.state == self.item.StateType.ACTIVE:
                self.data_icon.set_from_icon_name('emblem-synchronizing-symbolic', Gtk.IconSize.SMALL_TOOLBAR)
            elif self.item.state == self.item.StateType.COMPLETE:
                self.data_icon.set_from_icon_name("object-select-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
            else:
                self.data_icon.set_from_icon_name("dialog-warning-symbolic", Gtk.IconSize.SMALL_TOOLBAR)


