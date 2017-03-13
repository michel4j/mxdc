from mxdc.interface.beamlines import IBeamline
from mxdc.engine.diffraction import DataCollector
from mxdc.engine.scripting import get_scripts
from mxdc.utils import runlists
from mxdc.utils.log import get_module_logger
from mxdc.utils import config, gui
from mxdc.widgets.dialogs import warning, error, MyDialog
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.widgets.misc import ActiveLabel, ActiveProgressBar
from mxdc.widgets.mountwidget import MountWidget
from mxdc.widgets.runmanager import RunManager
from twisted.python.components import globalRegistry
from gi.repository import GObject
from gi.repository import Gtk, GdkPixbuf
from gi.repository import Pango
import sys
import os
import time


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
        'energy': ['entry', '{:0.4f}', float, 12.658],
        'distance': ['entry', '{:0.1f}', float, 200],
        'exposure': ['entry', '{:0.3f}', float, 1.0],
        'attenuation': ['entry', '{:0.1f}', float, 0.0],
        'first': ['entry', '{}', int, 1],
        'suffix': ['entry', '{}', str, ''],
        'skip': ['entry', '{}', str, ''],
        'helical': ['switch', '{}', bool, False],
        'process': ['switch', '{}', bool, False],
        'inverse': ['switch', '{}', bool, False],
    }

    def __init__(self):
        self.setup_gui()
        self.window = self.run_editor
        self.new_run = True
        self.run_index = 0

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

            try:
                value = conv(raw_value)
            except ValueError:
                value = default

            info[name] = value
        return info


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
