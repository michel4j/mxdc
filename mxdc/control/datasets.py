from gi.repository import GObject, Gio
from mxdc.beamline.mx import IBeamline
from mxdc.utils import converter
from mxdc.utils.config import settings
from mxdc.utils.log import get_module_logger
from mxdc.widgets import datawidget, dialogs
from mxdc.widgets.imageviewer import ImageViewer
from samplestore import ISampleStore
from twisted.python.components import globalRegistry

_logger = get_module_logger('mxdc.samples')


class RunItem(GObject.GObject):
    state = GObject.Property(type=int, default=0)
    position = GObject.Property(type=int, default=0)
    info = GObject.Property(type=GObject.TYPE_PYOBJECT)

    def __init__(self, info):
        super(RunItem, self).__init__()
        self.info = info

    def __getitem__(self, item):
        return self.info[item]


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
        self.image_viewer = ImageViewer()
        self.run_editor = datawidget.RunEditor()
        self.run_editor.window.set_transient_for(dialogs.MAIN_WINDOW)
        self.run_store = Gio.ListStore(item_type=RunItem)
        self.run_store.connect('items-changed', self.update_positions)
        self.setup()

    @staticmethod
    def update_positions(model, position, removed, added):
        pos = 0
        item = model.get_item(pos)
        while item:
            item.position = pos
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
        self.sample_store.connect('updated', self.on_store_updated)

    def update_run_config(self, item, config):
        sample = self.sample_store.get_current()
        config.run_name_lbl.set_text('{name}'.format(**item.info))
        config.run_sample_lbl.set_text('{} / {}'.format(sample.get('name', 'unknown'), sample.get('group', 'unknown')))
        config.run_path_lbl.set_text(settings.get_string('directory-template').format(**item.info))
        config.run_index_lbl.set_text('{}'.format(item.position))
        config.run_info_lbl.set_text(
            (
                'Will collect {range} deg total, with {delta} deg per frame, {exposure} sec exposure per frame, '
                'starting at frame #{first} and {start} deg omega, attenuating {attenuation} % of '
                'the beam at {energy} KeV. Helical mode is {helical}; inverse beam is {inverse}'
            ).format(**item.info)
        )

    def create_run_config(self, item):
        config = datawidget.RunConfig()
        self.update_run_config(item, config)
        config.delete_run_btn.connect('clicked', self.on_delete_run, item)
        config.edit_run_btn.connect('clicked', self.on_edit_run, item)
        config.copy_run_btn.connect('clicked', self.on_copy_run, item)
        item.connect('notify::state', self.on_item_state, config)
        item.connect('notify::info', self.on_item_info, config)
        return config.dataset_run_row

    def on_store_updated(self, obj):
        sample = self.sample_store.get_current()
        self.run_editor.set_sample(sample)

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
            item = RunItem(self.run_editor.get_parameters())
            self.run_store.append(item)
            self.run_editor.window.hide()
        else:
            item = self.run_editor.item
            item.info = self.run_editor.get_parameters()
            self.run_editor.window.hide()

    def on_delete_run(self, obj, item):
        self.run_store.remove(item.position)

    def on_edit_run(self, obj, item):
        self.run_editor.configure(item.info)
        self.run_editor.item = item
        self.run_editor.window.show_all()

    def on_copy_run(self, obj, item):
        self.run_editor.configure(item.info)
        self.run_editor.item = None
        self.run_editor.window.show_all()

    def on_item_info(self, item, param, config):
        self.update_run_config(item, config)

    def on_item_state(self, item, param, config):
        self.update_run_config(item, config)

    def on_clear_runs(self, obj):
        self.run_store.remove_all()
