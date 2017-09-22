import uuid
from collections import OrderedDict
from collections import defaultdict
from copy import copy

from automounter import DewarController
from gi.repository import Gio, Gtk, Gdk, Pango, GObject
from mxdc.beamline.mx import IBeamline
from mxdc.engine import auto
from mxdc.utils.decorators import async
from twisted.python.components import globalRegistry
from zope.interface import Interface, implements


class ISampleStore(Interface):
    """Sample information database."""

    def get_current(self):
        pass

    def get_next(self):
        pass

    def has_port(self, port):
        pass

    def get_state(self, port):
        pass


class GroupItem(GObject.GObject):
    selected = GObject.Property(type=bool, default=False)
    name = GObject.Property(type=str, default="")

    def __init__(self, name, sample_model, items=()):
        super(GroupItem, self).__init__()
        self.props.name = name
        self.sample_model = sample_model
        self.items = {path: False for path in items}
        self.uuid = str(uuid.uuid4())
        self.notify_id = self.connect('notify::selected', self.on_selected)
        self.propagate = True

    def update_item(self, key, value):
        """propagate sample selection to whole group preventing cyclic propagation"""
        if key in self.items and self.items[key] != value:
            self.items[key] = value
            if self.propagate:
                selected = all(self.items.values())
                if self.props.selected != selected:
                    self.handler_block(self.notify_id)  # do not propagate if group was set/unset from item
                    self.props.selected = selected
                    self.handler_unblock(self.notify_id)

    def on_selected(self, obj, param):
        """Propagate group selection to individual samples preventing cyclic propagation"""
        for sample in self.sample_model:
            can_change = (
                sample[SampleStore.Data.GROUP] == self.props.name and
                sample[SampleStore.Data.SELECTED] != self.props.selected
            )
            if can_change:
                self.items[sample[SampleStore.Data.UUID]] = self.props.selected
                sample[SampleStore.Data.SELECTED] = self.props.selected
                sample[SampleStore.Data.PROGRESS] = SampleStore.Progress.NONE

    def __str__(self):
        return '<Group: {}|{}>'.format(self.props.name, self.props.selected)


class SampleStore(GObject.GObject):
    implements(ISampleStore)

    class Data(object):
        (
            SELECTED, NAME, GROUP, CONTAINER, PORT, BARCODE,
            PRIORITY, COMMENTS, STATE, CONTAINER_TYPE, PROGRESS, UUID, DATA
        ) = range(13)
        TYPES = (
            bool, str, str, str, str, str,
            int, str, int, str, int, str, object
        )

    class Progress(object):
        NONE, PENDING, ACTIVE, DONE = range(4)

    class State(object):
        EMPTY, GOOD, UNKNOWN, MOUNTED, JAMMED, NONE = range(6)

    Column = OrderedDict([
        (Data.SELECTED, ''),
        (Data.STATE, ''),
        (Data.NAME, 'Name'),
        (Data.GROUP, 'Group'),
        (Data.CONTAINER, 'Container'),
        (Data.CONTAINER_TYPE, 'Type'),
        (Data.PORT, 'Port'),
        (Data.PRIORITY, 'Priority'),
    ])

    __gsignals__ = {
        'updated': (GObject.SignalFlags.RUN_LAST, None, []),
    }

    def __init__(self, view, widget):
        super(SampleStore, self).__init__()
        self.model = Gtk.ListStore(*self.Data.TYPES)
        self.search_model = self.model.filter_new()
        self.search_model.set_visible_func(self.search_data)
        self.filter_model = Gtk.TreeModelSort(model=self.search_model)
        self.group_model = Gio.ListStore(item_type=GroupItem)
        self.group_registry = {}
        self.next_sample = {}
        self.current_sample = {}
        self.ports = set()
        self.states = {}
        self.filter_text = ''

        self.view = view
        self.widget = widget
        self.view.set_model(self.filter_model)

        self.beamline = globalRegistry.lookup([], IBeamline)

        self.setup()
        self.model.connect('row-changed', self.on_sample_row_changed)
        self.widget.samples_selectall_btn.connect('clicked', lambda x: self.select_all(True))
        self.widget.samples_selectnone_btn.connect('clicked', lambda x: self.select_all(False))
        self.view.connect('key-press-event', self.on_key_press)
        self.widget.samples_reload_btn.connect('clicked', lambda x: self.import_mxlive())
        self.beamline.automounter.connect('mounted', self.on_sample_mounted)
        self.beamline.automounter.connect('port-state', self.on_automounter_states)
        self.widget.samples_mount_btn.connect('clicked', lambda x: self.mount_action())
        self.widget.samples_dismount_btn.connect('clicked', lambda x: self.dismount_action())
        self.widget.samples_search_entry.connect('search-changed', self.on_search)
        self.widget.connect('realize', self.import_mxlive)

        globalRegistry.register([], ISampleStore, '', self)

    def get_current(self):
        return self.current_sample

    def setup(self):
        # Selected Column
        for data, title in self.Column.items():
            if data == self.Data.SELECTED:
                renderer = Gtk.CellRendererToggle(activatable=True)
                renderer.connect('toggled', self.on_row_toggled, self.filter_model)
                column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer, active=data)
                column.set_fixed_width(30)
            elif data == self.Data.STATE:
                renderer = Gtk.CellRendererText(text=u"\u25c9")
                column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_fixed_width(20)
                column.set_cell_data_func(renderer, self.format_state)
            else:
                renderer = Gtk.CellRendererText()
                column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer, text=data)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_expand(True)
                column.set_sort_column_id(data)
                column.set_cell_data_func(renderer, self.format_progress)
                if data in [self.Data.NAME, self.Data.GROUP]:
                    column.set_resizable(True)
            column.set_clickable(True)
            column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
            self.view.append_column(column)

        self.selection = self.view.get_selection()
        self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        self.view.props.activate_on_single_click = False
        self.view.connect('row-activated', self.on_row_activated)
        self.view.set_enable_search(True)
        self.view.set_search_entry(self.widget.samples_search_entry)
        self.view.set_search_column(self.Data.NAME)
        self.view.set_tooltip_column(self.Data.COMMENTS)
        self.view.set_search_column(self.Data.NAME)
        self.model.set_sort_column_id(self.Data.PRIORITY, Gtk.SortType.DESCENDING)
        self.model.connect('sort-column-changed', lambda x: self.update_next_sample())
        self.update_current_sample()
        self.update_next_sample()

        self.widget.auto_groups_box.bind_model(self.group_model, self.create_group_selector)

        self.sample_dewar = DewarController(self.widget, self)
        self.sample_dewar.connect('selected', self.on_dewar_selected)

    def load_data(self, data):
        self.clear()
        groups = defaultdict(list)
        for item in data:
            key = self.add_item(item)
            groups[item['group']].append(key)
        for name, samples in groups.items():
            group_item = GroupItem(name, self.model, items=samples)
            self.group_model.append(group_item)
            self.group_registry[name] = group_item
        GObject.idle_add(self.emit, 'updated')

    def add_item(self, item):
        item['uuid'] = str(uuid.uuid4())
        self.model.append([
            item.get('selected', False),
            item.get('name', 'unknown'),
            item.get('group', ''),
            item.get('container', ''),
            item.get('port', ''),
            item.get('barcode', ''),
            item.get('priority', 0),
            item.get('comments', ''),
            self.states.get(item.get('port', ''), self.State.UNKNOWN),
            item.get('container_type', ''),
            self.Progress.NONE,
            item['uuid'],
            item
        ])
        self.ports.add(item.get('port'))
        return item['uuid']

    def create_group_selector(self, item):
        btn = Gtk.CheckButton(item.props.name)
        btn.set_active(item.selected)
        btn.connect('toggled', self.on_group_btn_toggled, item)
        item.connect('notify::selected', self.on_group_item_toggled, btn)
        return btn

    def on_group_btn_toggled(self, btn, item):
        if item.props.selected != btn.get_active():
            item.props.selected = btn.get_active()

    def on_group_item_toggled(self, item, param, btn):
        if item.props.selected != btn.get_active():
            btn.set_active(item.props.selected)

    def on_search(self, obj):
        self.filter_text = obj.get_text()
        self.search_model.refilter()

    def search_data(self, model, itr, dat):
        """Test if the row is visible"""
        search_text = " ".join([
            str(self.model.get_value(itr, col)) for col in
            [self.Data.NAME, self.Data.GROUP, self.Data.CONTAINER, self.Data.PORT, self.Data.COMMENTS,
             self.Data.BARCODE]
        ])
        return (not self.filter_text) or (self.filter_text in search_text)

    def import_mxlive(self, *args, **kwargs):
        data = self.beamline.lims.get_samples(self.beamline.name)
        if not 'error' in data:
            self.widget.notifier.notify('{} Samples Imported from MxLIVE'.format(len(data)))
            self.load_data(data)

    def format_state(self, column, cell, model, itr, data):
        value = model.get_value(itr, self.Data.STATE)
        if value in [self.State.UNKNOWN, self.State.NONE]:
            col = Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=1.0)
            cell.set_property("foreground-rgba", col)
            cell.set_property("text", u"\u25ef")
        else:
            col = Gdk.RGBA(alpha=1.0, **DewarController.Color[value])
            cell.set_property("foreground-rgba", col)
            cell.set_property("text", u"\u2b24")

    def format_progress(self, column, cell, model, itr, data):
        value = model.get_value(itr, self.Data.PROGRESS)
        if value == self.Progress.DONE:
            cell.set_property("style", Pango.Style.ITALIC)
        else:
            cell.set_property("style", Pango.Style.NORMAL)

    def update_next_sample(self):
        items = self.get_selected()
        if items:
            self.widget.samples_info1_lbl.set_markup('{} Selected'.format(len(items)))
            self.widget.auto_queue_lbl.set_markup('{} Selected Samples'.format(len(items)))
            self.next_sample = items[0]
            self.widget.samples_mount_btn.set_sensitive(True)
        else:
            self.widget.samples_info1_lbl.set_markup('')
            self.widget.auto_queue_lbl.set_markup('0 Selected Samples')
            self.next_sample = {}
            self.widget.samples_mount_btn.set_sensitive(False)

        self.widget.samples_next_sample.set_markup(
            '<span color="blue">{}</span>'.format(self.next_sample.get('name', '...'))
        )
        self.widget.samples_next_port.set_markup(
            '{}/{}'.format(self.next_sample.get('container_name', '...'), self.next_sample.get('port', '...'))
        )

    def update_current_sample(self):
        if self.current_sample:
            self.widget.samples_dismount_btn.set_sensitive(True)
        else:
            self.widget.samples_dismount_btn.set_sensitive(False)

        self.widget.samples_cur_sample.set_markup(
            '<span color="blue">{}</span>'.format(self.current_sample.get('name', '...'))
        )
        self.widget.samples_cur_port.set_markup(
            '{}/{}'.format(self.current_sample.get('container_name', '...'), self.current_sample.get('port', '...'))
        )
        GObject.idle_add(self.emit, 'updated')

    def get_next(self):
        itr = self.filter_model.get_iter_first()
        while itr and not self.filter_model.get_value(itr, self.Data.SELECTED):
            itr = self.filter_model.iter_next(itr)
        if itr:
            return Gtk.TreeRowReference.new(self.filter_model, self.filter_model.get_path(itr))

    def find_by_port(self, port):
        itr = self.model.get_iter_first()
        while itr and self.model.get_value(itr, self.Data.PORT) != port:
            itr = self.model.iter_next(itr)
        if itr:
            return self.model.get_value(itr, self.Data.DATA), itr
        else:
            return {}, None

    def get_state(self, port):
        return self.states.get(port, self.State.UNKNOWN)

    def get_selected(self):
        itr = self.model.get_iter_first()
        items = []
        while itr:
            sel = self.model.get_value(itr, self.Data.SELECTED)
            state = self.model.get_value(itr, self.Data.STATE)
            if sel and state not in [self.State.JAMMED, self.State.EMPTY]:
                item = self.model.get_value(itr, self.Data.DATA)
                item['path'] = self.model.get_path(itr)
                items.append(item)
            itr = self.model.iter_next(itr)
        return items

    def select_all(self, option=True):
        model, paths = self.selection.get_selected_rows()
        # toggle all selected rows otherwise toggle the whole list
        if len(paths) > 1:
            for path in paths:
                itr = self.filter_model.get_iter(path)
                sitr = self.filter_model.convert_iter_to_child_iter(itr)
                self.search_model.set_value(sitr, self.Data.SELECTED, option)
        else:
            itr = self.filter_model.get_iter_first()
            while itr:
                sitr = self.filter_model.convert_iter_to_child_iter(itr)
                state = self.search_model.get_value(sitr, self.Data.STATE)
                if state not in [self.State.JAMMED, self.State.EMPTY]:
                    self.search_model.set_value(sitr, self.Data.SELECTED, option)
                itr = self.filter_model.iter_next(itr)
                # self.update_next_sample()

    def clear(self):
        self.model.clear()
        self.group_model.remove_all()
        self.group_registry = {}
        GObject.idle_add(self.emit, 'updated')

    def has_port(self, port):
        return port in self.ports

    def toggle_row(self, path):
        itr = self.filter_model.convert_iter_to_child_iter(self.filter_model.get_iter(path))
        value = self.search_model.get_value(itr, self.Data.SELECTED)
        state = self.search_model.get_value(itr, self.Data.STATE)
        if state not in [self.State.JAMMED, self.State.EMPTY]:
            selected = not value
            self.search_model.set_value(itr, self.Data.SELECTED, selected)
            if selected:
                self.search_model.set_value(itr, self.Data.PROGRESS, self.Progress.NONE)

    def update_states(self, states):
        self.states.update(states)
        itr = self.model.get_iter_first()
        while itr:
            port = self.model.get_value(itr, self.Data.PORT)
            self.model.set(itr, self.Data.STATE, self.states.get(port, self.State.UNKNOWN))
            itr = self.model.iter_next(itr)

    def on_sample_row_changed(self, model, path, itr):
        if self.group_registry:
            val = model.get_value(itr, self.Data.SELECTED)
            group = model.get_value(itr, self.Data.GROUP)
            key = model.get_value(itr, self.Data.UUID)
            self.group_registry[group].update_item(key, val)
            self.update_next_sample()

    def on_automounter_states(self, obj, states):
        self.update_states(states)

    def on_dewar_selected(self, obj, port):
        self.next_sample, itr = self.find_by_port(port)
        if self.next_sample:
            self.widget.samples_mount_btn.set_sensitive(True)
        else:
            self.widget.samples_mount_btn.set_sensitive(False)
        self.widget.samples_next_sample.set_markup(
            '<span color="blue">{}</span>'.format(self.next_sample.get('name', '...'))
        )
        self.widget.samples_next_port.set_markup(
            '{}/{}'.format(self.next_sample.get('container_name', '...'), self.next_sample.get('port', '...'))
        )

    def on_sample_mounted(self, obj, info):
        if info:
            port, barcode = info
            self.current_sample, itr = self.find_by_port(port)
            self.model.set(
                itr, self.Data.SELECTED, False,
            )
            self.widget.samples_dismount_btn.set_sensitive(True)
        else:
            self.current_sample = {}

        self.widget.spinner.stop()
        # self.update_next_sample()
        self.update_current_sample()

    def on_key_press(self, obj, event):
        return self.widget.samples_search_entry.handle_event(event)

    def on_row_activated(self, obj, path, column):
        self.toggle_row(path)

    def on_row_toggled(self, cell, path, model):
        self.toggle_row(path)

    @async
    def mount_action(self):
        self.widget.spinner.start()
        if self.next_sample and self.beamline.automounter.is_mountable(self.next_sample['port']):
            auto.auto_mount_manual(self.beamline, self.next_sample['port'])

    @async
    def dismount_action(self):
        self.widget.spinner.start()
        if self.current_sample and self.beamline.automounter.is_mounted(self.current_sample['port']):
            auto.auto_dismount_manual(self.beamline, self.current_sample['port'])


class SampleQueue(GObject.GObject):
    Column = OrderedDict([
        (SampleStore.Data.STATE, ''),
        (SampleStore.Data.NAME, 'Name'),
        (SampleStore.Data.GROUP, 'Group'),
        (SampleStore.Data.CONTAINER, 'Container'),
        (SampleStore.Data.PORT, 'Port'),
    ])

    def __init__(self, view):
        super(SampleQueue, self).__init__()
        self.view = view
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        self.model = self.sample_store.model
        self.auto_queue = self.model.filter_new()
        self.auto_queue.set_visible_func(self.queued_data)
        self.view.set_model(self.auto_queue)

        self.setup()

    def setup(self):
        # Selected Column
        for data, title in self.Column.items():
            if data == SampleStore.Data.STATE:
                renderer = Gtk.CellRendererPixbuf()
                column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_fixed_width(32)
                column.set_cell_data_func(renderer, self.format_state)
            else:
                renderer = Gtk.CellRendererText()
                column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer, text=data)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_expand(True)

                column.set_cell_data_func(renderer, self.format_processed)
                if data in [SampleStore.Data.NAME, SampleStore.Data.GROUP]:
                    column.set_resizable(True)
            column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
            self.view.append_column(column)
        self.view.set_tooltip_column(SampleStore.Data.COMMENTS)
        self.model.set_sort_column_id(SampleStore.Data.PRIORITY, Gtk.SortType.DESCENDING)

    def mark_progress(self, uuid, state):
        for item in self.auto_queue:
            if item[SampleStore.Data.UUID] == uuid:
                item[SampleStore.Data.PROGRESS] = state
                break

    def queued_data(self, model, itr, dat):
        """Test if the row is visible"""
        return (
            self.model.get_value(itr, SampleStore.Data.SELECTED) or
            self.model.get_value(itr, SampleStore.Data.PROGRESS) != SampleStore.Progress.NONE
        )

    def clean(self):
        for item in self.model:
            item[SampleStore.Data.PROGRESS] = SampleStore.Progress.NONE

    def format_state(self, column, cell, model, itr, data):
        value = model.get_value(itr, SampleStore.Data.STATE)
        processed = model.get_value(itr, SampleStore.Data.PROGRESS)
        if processed == SampleStore.Progress.ACTIVE:
            # cell.set_property("foreground-rgba", Gdk.RGBA(alpha=1.0, **DewarController.Color[value]))
            cell.set_property("icon-name", 'emblem-synchronizing-symbolic')
        elif processed == SampleStore.Progress.DONE:
            # cell.set_property("foreground-rgba", Gdk.RGBA(red=0.0, green=0.5, blue=0.0, alpha=1.0))
            cell.set_property("icon-name", "object-select-symbolic")
        else:
            cell.set_property("icon-name", "content-loading-symbolic")

    def format_processed(self, column, cell, model, itr, data):
        value = model.get_value(itr, SampleStore.Data.PROGRESS)
        if value == SampleStore.Progress.DONE:
            cell.set_property("foreground-rgba", Gdk.RGBA(red=0.0, green=0.5, blue=0.0, alpha=1.0))
        else:
            cell.set_property("foreground-rgba", None)

    def get_samples(self):
        return [
            copy(item[SampleStore.Data.DATA])
            for item in self.auto_queue if item[SampleStore.Data.SELECTED]
        ]
