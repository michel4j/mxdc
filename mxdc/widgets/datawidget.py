import os
from datetime import date

from gi.repository import Gtk
from twisted.python.components import globalRegistry

from mxdc.beamline.mx import IBeamline
from mxdc.utils import gui, converter, config, misc
from mxdc.utils.config import settings

STRATEGIES = {
    0: {
        'range': 180, 'desc': 'Collect'
    },
    1: {
        'delta': 1.0, 'range': 182, 'start': 0.0, 'helical': False, 'inverse': False,
        'desc': 'Screen 0\xc2\xb0, 45\xc2\xb0, 90\xc2\xb0, 180\xc2\xb0'
    },
    2: {'delta': 1.0, 'range': 92, 'start': 0.0, 'helical': False, 'inverse': False,
        'desc': 'Screen 0\xc2\xb0, 45\xc2\xb0, 90\xc2\xb0'
        },
    3: {
        'delta': 1.0, 'range': 92, 'start': 0.0, 'helical': False, 'inverse': False,
        'desc': 'Screen 0\xc2\xb0, 90\xc2\xb0'
    },
    4: {
        'delta': 180.0, 'exposure': 30.0, 'range': 360.0, 'helical': False, 'inverse': False, 'desc': 'Powder',
    }
}


def _calc_skip(strategy, delta, first):
    if strategy in [0, 4]:
        return ''
    elif strategy == 1:
        return '{}-{},{}-{},{}-{}'.format(
            first + int(2 / delta),
            first + int(45 / delta) - 1,
            first + int(47 / delta),
            first + int(90 / delta) - 1,
            first + int(92 / delta),
            first + int(180 / delta) - 1
        )

    elif strategy == 2:
        return '{}-{},{}-{}'.format(
            first + int(2 / delta),
            first + int(45 / delta) - 1,
            first + int(47 / delta),
            first + int(90 / delta) - 1,
        )
    elif strategy == 3:
        return '{}-{}'.format(
            first + int(2 / delta),
            first + int(90 / delta) - 1,
        )


class RunEditor(gui.BuilderMixin):
    gui_roots = {
        'data/run_editor': ['run_editor']
    }
    Specs = {
        # field: ['field_type', format, type, default]
        'resolution': ['entry', '{:0.2f}', float, 2.0],
        'delta': ['entry', '{:0.2f}', float, 1.0],
        'range': ['entry', '{:0.1f}', float, 180.],
        'start': ['entry', '{:0.1f}', float, 0.],
        'wedge': ['entry', '{:0.1f}', float, 360.],
        'energy': ['entry', '{:0.3f}', float, 12.658],
        'distance': ['entry', '{:0.1f}', float, 200],
        'exposure': ['entry', '{:0.3f}', float, 1.0],
        'attenuation': ['entry', '{:0.1f}', float, 0.0],
        'first': ['entry', '{}', int, 1],
        'name': ['entry', '{}', str, ''],
        'strategy': ['cbox', '{}', int, 0],
        'helical': ['switch', '{}', bool, False],
        'inverse': ['switch', '{}', bool, False],
    }

    def __init__(self):
        self.setup_gui()
        self.window = self.run_editor
        self.window.set_property('use-header-bar', True)
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.new_run = True
        self.run_index = 0
        self.sample = None
        self.build_gui()

    def configure(self, info, disable=()):
        for name, details in self.Specs.items():
            field_type, fmt, conv, default = details
            field_name = 'run_{}_{}'.format(name, field_type)
            value = info.get(name, default)
            field = getattr(self, field_name)
            if field_type == 'entry':
                field.set_text(fmt.format(value))
            elif field_type == 'switch':
                field.set_active(value)
            elif field_type == 'cbox':
                field.set_active_id(str(value))
            if name in disable:
                field.set_sensitive(False)

    def set_sample(self, sample):
        self.run_sample_entry.set_text(sample.get('name', '...'))
        if not self.run_name_entry.get_text():
            self.run_name_entry.set_text(sample.get('name', 'test'))
        self.sample = sample

    def get_parameters(self):
        info = {}
        for name, details in self.Specs.items():
            field_type, fmt, conv, default = details
            field_name = 'run_{}_{}'.format(name, field_type)
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
            except ValueError:
                value = default

            info[name] = value

        # Calculate skip, and update sample variables info
        info.update({
            'skip': _calc_skip(info['strategy'], info['delta'], info['first']),
            'date': date.today().strftime('%Y%m%d'),
            'session': config.get_session(),
            'strategy_desc': STRATEGIES[info['strategy']]['desc'],
        })
        if self.sample:
            info.update({
                'sample': self.sample.get('name', info['name']),
                'sample_id': self.sample.get('id'),
                'port': self.sample.get('port', ''),
                'container': misc.slugify(self.sample.get('container', '')),
                'group': misc.slugify(self.sample.get('group', '')),
            })
        else:
            info.update({
                'sample': info['name'],
                'sample_id': '',
                'port': '',
                'container': '',
                'group': '',
            })
        dir_template = '{}/{}'.format(os.environ['HOME'], settings.get_string('directory-template'))
        info['directory'] = dir_template.format(**info).replace('//', '/')
        return info

    def build_gui(self):
        for name, details in self.Specs.items():
            field_type, fmt, conv, default = details
            field_name = 'run_{}_{}'.format(name, field_type)
            field = getattr(self, field_name)
            if field_type in ['switch']:
                field.connect('activate', self.on_entry_changed, name)
            elif field_type in ['cbox']:
                field.connect('changed', self.on_entry_changed, None, name)
            else:
                field.connect('focus-out-event', self.on_entry_changed, name)
        for id, params in STRATEGIES.items():
            self.run_strategy_cbox.append(str(id), params['desc'])

    def on_entry_changed(self, obj, event, field_name):
        params = self.get_parameters()
        if field_name in ['resolution', 'energy']:
            params['distance'] = converter.resol_to_dist(
                params['resolution'], self.beamline.detector.mm_size, params['energy']
            )
        elif field_name == 'strategy':
            defaults = STRATEGIES.get(params['strategy'])
            if params['strategy'] == 0:
                defaults['delta'] = self.beamline.config['default_delta']
            if params['strategy'] in [0, 1, 2]:
                defaults['exposure'] = self.beamline.config['default_exposure']

            params.update(defaults)
        self.configure(params)


class RunConfigFull(Gtk.ListBoxRow, gui.BuilderMixin):
    gui_roots = {
        'data/run_editor': ['dataset_run_row']
    }

    def __init__(self):
        super(RunConfigFull, self).__init__()
        self.setup_gui()
        self.add(self.dataset_run_row)


class RunConfig(gui.Builder):
    gui_roots = {
        'data/run_editor': ['dataset_run_row', 'empty_run_row']
    }
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
        'directory': '{}',
    }

    def get_widget(self):
        if self.item.state == self.item.StateType.ADD:
            return self.empty_run_row
        else:
            return self.dataset_run_row

    def set_item(self, item):
        self.item = item
        if self.item.state != self.item.StateType.ADD:
            for param in ['state', 'info', 'position', 'progress', 'warning']:
                item.connect('notify::{}'.format(param), self.on_item_changed)
            self.update()

    def on_item_changed(self, item, param):
        self.update()

    def update(self):
        self.run_error_msg.set_text(self.item.props.warning)
        self.run_error_msg.set_visible(self.item.props.state == self.item.StateType.ERROR)
        for name, format in self.Formats.items():
            field_name = 'run_{}_lbl'.format(name, name)
            field = getattr(self, field_name, None)
            if field and name in self.item.props.info:
                field.set_text(format.format(self.item.props.info[name]))
        if self.item.props.progress > 0.0:
            self.run_progress_lbl.set_text('{:0.1f} %'.format(self.item.props.progress))
        self.dataset_run_row.override_background_color(Gtk.StateFlags.NORMAL, self.item.get_color())
        if self.item.props.state == self.item.StateType.COMPLETE:
            self.edit_run_btn.set_sensitive(False)


class EmptyConfigFull(Gtk.ListBoxRow, gui.BuilderMixin):
    gui_roots = {
        'data/run_editor': ['empty_run_row']
    }

    def __init__(self):
        super(EmptyConfigFull, self).__init__()
        self.setup_gui()
        self.add(self.empty_run_row)


class EmptyConfig(gui.BuilderMixin):
    gui_roots = {
        'data/run_editor': ['empty_run_row']
    }
