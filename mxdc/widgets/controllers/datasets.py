from gi.repository import GObject, Gio, Gtk
from twisted.python.components import globalRegistry

from mxdc.beamline.mx import IBeamline
from mxdc.utils.log import get_module_logger
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.widgets.rasterwidget import RasterWidget
from mxdc.widgets import datawidget, dialogs
from collections import OrderedDict

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
        'active-sample': (GObject.SignalFlags.RUN_FIRST, None, [GObject.TYPE_PYOBJECT, ]),
        'sample-selected': (GObject.SignalFlags.RUN_FIRST, None, [GObject.TYPE_PYOBJECT, ]),
    }

    def __init__(self, widget):
        super(DatasetsController, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.image_viewer = ImageViewer()
        self.raster_tool = RasterWidget()
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
        self.widget.raster_datasets_box.pack_start(self.raster_tool, True, True, 0)
        self.widget.datasets_add_btn.connect('clicked', self.on_add_run)
        self.widget.datasets_clear_btn.connect('clicked', self.on_clear_runs)
        self.run_editor.run_cancel_btn.connect('clicked', lambda x: self.run_editor.window.hide())
        self.run_editor.run_save_btn.connect('clicked', self.on_save_run)

    def update_run_config(self, item, config):
        config.run_name_lbl.set_text('Name_{suffix}'.format(**item.info))
        config.run_sample_lbl.set_text('{} / {}'.format('Sample Name', 'Group Name'))
        config.run_path_lbl.set_text('/full/path/to/datatset/frames')
        config.run_info_lbl.set_text(
            (
                'Will collect {range} deg total, with {delta} deg per frame, {exposure} sec exposure per frame, '
                'starting at frame #{first} and {start} deg omega, attenuating {attenuation} % of '
                'the beam at {energy} KeV. Hellical mode is {helical}; inverse beam is {inverse}; Auto-Processing is {process}'
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

    def on_add_run(self, obj):
        self.run_editor.configure({})
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
