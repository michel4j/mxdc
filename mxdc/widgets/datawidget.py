from gi.repository import Gtk
from mxdc.utils import gui, converter, config
from twisted.python.components import globalRegistry
from datetime import date
from mxdc.beamline.mx import IBeamline


STRATEGIES = {
    0: {'range': 180},
    1: {'delta': 1.0, 'range': 92, 'start': 0.0, 'helical': False, 'inverse': False},
    2: {'delta': 1.0, 'range': 92, 'start': 0.0, 'helical': False, 'inverse': False},
    3: {'delta': 180.0, 'exposure': 30.0, 'range': 360.0, 'helical': False, 'inverse': False}
}


def _calc_skip(strategy, delta, first):
    if strategy in [0, 3]:
        return ''
    elif strategy == 1:
        return '{}-{},{}-{}'.format(
            first + int(2/delta),
            first + int(45/delta) - 1,
            first + int(47/delta),
            first + int(90/delta) - 1,
        )
    elif strategy == 2:
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
        self.build_gui()

    def configure(self, info):
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
            'sample': self.sample.get('name'),
            'sample_id': self.sample.get('id'),
            'date': date.today().strftime('%Y%m%d'),
            'group': self.sample.get('group'),
            'session': config.get_session(),
            'port': self.sample.get('port')
        })

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
        'data/run_editor': ['dataset_run_row']
    }


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
