import uuid
from collections import OrderedDict
from collections import defaultdict
from copy import copy

from gi.repository import Gio, Gtk, Gdk, Pango, GObject
from twisted.python.components import globalRegistry
from zope.interface import Interface, implements

from automounter import DewarController
from mxdc.beamlines.mx import IBeamline
from mxdc.conf import load_cache, save_cache
from mxdc.engines import auto
from mxdc.utils.automounter import Port, PortColors


class ISampleStore(Interface):
    """Sample information database."""

    def get_current(self):
        pass

    def get_next(self):
        pass

    def get_state(self, port):
        pass


class GroupItem(GObject.GObject):
    selected = GObject.Property(type=bool, default=False)
    name = GObject.Property(type=str, default="")
    changed = GObject.Property(type=object)

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
        changed = set()
        for sample in self.sample_model:
            can_change = (
                sample[SampleStore.Data.GROUP] == self.props.name and
                sample[SampleStore.Data.SELECTED] != self.props.selected
            )
            if can_change:
                self.items[sample[SampleStore.Data.UUID]] = self.props.selected
                valid_ports = [Port.GOOD, Port.UNKNOWN, Port.MOUNTED]
                if sample[SampleStore.Data.PORT] and sample[SampleStore.Data.STATE] in valid_ports:
                    sample[SampleStore.Data.SELECTED] = self.props.selected
                    sample[SampleStore.Data.PROGRESS] = SampleStore.Progress.NONE
                    changed.add(sample[SampleStore.Data.DATA]['id'])
        self.props.changed = changed

    def __str__(self):
        return '<Group: {}|{}>'.format(self.props.name, self.props.selected)


class SampleStore(GObject.GObject):
    implements(ISampleStore)

    class Data(object):
        (
            SELECTED, NAME, GROUP, CONTAINER, PORT, LOCATION, BARCODE,
            PRIORITY, COMMENTS, STATE, CONTAINER_TYPE, PROGRESS, UUID, DATA
        ) = range(14)
        TYPES = (
            bool, str, str, str, str, str, str,
            int, str, int, str, int, str, object
        )

    class Progress(object):
        NONE, PENDING, ACTIVE, DONE = range(4)

    Column = OrderedDict([
        (Data.SELECTED, ''),
        (Data.STATE, ''),
        (Data.NAME, 'Name'),
        (Data.GROUP, 'Group'),
        (Data.PORT, 'Port'),
        (Data.LOCATION, 'Container'),
        (Data.PRIORITY, 'Priority'),
    ])

    __gsignals__ = {
        'updated': (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    cache = GObject.Property(type=object)
    current_sample = GObject.Property(type=object)
    next_sample = GObject.Property(type=object)
    ports = GObject.Property(type=object)
    containers = GObject.Property(type=object)

    def __init__(self, view, widget):
        super(SampleStore, self).__init__()
        self.model = Gtk.ListStore(*self.Data.TYPES)
        self.search_model = self.model.filter_new()
        self.search_model.set_visible_func(self.search_data)
        self.filter_model = Gtk.TreeModelSort(model=self.search_model)
        self.group_model = Gio.ListStore(item_type=GroupItem)
        self.group_registry = {}

        # initialize properties
        self.props.next_sample = {}
        self.props.current_sample = {}
        self.props.ports = {}
        self.props.containers = {}

        try:
            cache = load_cache('samples')
            self.props.cache = set() if not cache else set(cache)
        except:
            self.props.cache = set()

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
        self.beamline.automounter.connect('notify::sample', self.on_sample_mounted)
        self.beamline.automounter.connect('notify::ports', self.update_states)
        self.widget.samples_mount_btn.connect('clicked', lambda x: self.mount_action())
        self.widget.samples_dismount_btn.connect('clicked', lambda x: self.dismount_action())
        self.widget.samples_search_entry.connect('search-changed', self.on_search)
        self.widget.mxdc_main.connect('realize', self.import_mxlive)
        self.connect('notify::cache', self.on_cache)
        self.connect('notify::current-sample', self.on_cur_changed)
        self.connect('notify::next-sample', self.on_next_changed)

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
        self.model.connect('sort-column-changed', lambda x: self.roll_next_sample())
        self.roll_next_sample()

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
            group_item.connect('notify::changed', self.on_group_changed)
            self.group_model.append(group_item)
            self.group_registry[name] = group_item
        GObject.idle_add(self.emit, 'updated')

    def add_item(self, item):
        item['uuid'] = str(uuid.uuid4())
        state = self.beamline.automounter.ports.get(item.get('port'), Port.UNKNOWN)
        state = state if state in [Port.BAD, Port.MOUNTED, Port.EMPTY] else Port.GOOD
        self.model.append([
            item['id'] in self.cache,
            item.get('name', 'unknown'),
            item.get('group', ''),
            item.get('container', ''),
            item.get('port', ''),
            '{} ({})'.format(item.get('container'), item.get('location')),
            item.get('barcode', ''),
            item.get('priority', 0),
            item.get('comments', ''),
            state,
            item.get('container_type', ''),
            self.Progress.NONE,
            item['uuid'],
            item
        ])

        if item.get('port'):
            self.props.ports[item['port']] = state
            container_location = item.get('port', '').rsplit(item['location'], 1)[0]
            self.containers[container_location] = item['container']
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

    def on_group_changed(self, item, *args, **kwargs):
        if item.selected:
            cache = self.cache | item.changed
        else:
            cache = self.cache - item.changed
        self.props.cache = cache

    def on_search(self, obj):
        self.filter_text = obj.get_text()
        self.search_model.refilter()

    def on_cache(self, *args, **kwargs):
        save_cache(list(self.props.cache), 'samples')

    def on_next_changed(self, *args, **kwargs):
        self.widget.samples_next_sample.set_text(self.next_sample.get('name', '...'))
        port = self.next_sample.get('port', '...') or '<manual>'
        self.widget.samples_next_port.set_text(port)
        self.widget.samples_mount_btn.set_sensitive(bool(self.next_sample))

    def on_cur_changed(self, *args, **kwargs):
        self.widget.samples_cur_sample.set_text(self.current_sample.get('name', '...'))
        port = self.current_sample.get('port', '...') or '<manual>'
        self.widget.samples_cur_port.set_text(port)
        self.widget.samples_dismount_btn.set_sensitive(bool(self.current_sample))

        GObject.idle_add(self.emit, 'updated')

    def search_data(self, model, itr, dat):
        """Test if the row is visible"""
        row = model[itr]
        search_text = " ".join([
            str(row[col]) for col in
            [self.Data.NAME, self.Data.GROUP, self.Data.CONTAINER, self.Data.PORT, self.Data.COMMENTS,
             self.Data.BARCODE]
        ])
        return (not self.filter_text) or (self.filter_text in search_text)

    def import_mxlive(self, *args, **kwargs):
        data = self.beamline.lims.get_samples(self.beamline.name)
        if not 'error' in data:
            self.widget.notifier.notify('{} Samples Imported from MxLIVE'.format(len(data)))
            self.load_data(data)
        else:
            self.widget.notifier.notify(data['error'])

    def format_state(self, column, cell, model, itr, data):
        value = model[itr][self.Data.STATE]
        loaded = model[itr][self.Data.PORT]
        if not loaded:
            cell.set_property("text", u"")
        elif value in [Port.EMPTY]:
            col = Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=0.5)
            cell.set_property("foreground-rgba", col)
            cell.set_property("text", u"\u2b24")
        elif value in [Port.UNKNOWN]:
            col = Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=1.0)
            cell.set_property("foreground-rgba", col)
            cell.set_property("text", u"\u25ef")
        else:
            col = Gdk.RGBA(**PortColors[value])
            cell.set_property("foreground-rgba", col)
            cell.set_property("text", u"\u2b24")

    def format_progress(self, column, cell, model, itr, data):
        value = model.get_value(itr, self.Data.PROGRESS)
        if value == self.Progress.DONE:
            cell.set_property("style", Pango.Style.ITALIC)
        else:
            cell.set_property("style", Pango.Style.NORMAL)

    def roll_next_sample(self):
        items = self.get_selected()
        if items:
            self.widget.samples_info1_lbl.set_markup('{} Selected'.format(len(items)))
            self.props.next_sample = items[0]
        else:
            self.widget.samples_info1_lbl.set_markup('')
            self.props.next_sample = {}

    def get_next(self):
        itr = self.filter_model.get_iter_first()
        while itr and not self.filter_model.get_value(itr, self.Data.SELECTED):
            itr = self.filter_model.iter_next(itr)
        if itr:
            return Gtk.TreeRowReference.new(self.filter_model, self.filter_model.get_path(itr))

    def find_by_port(self, port):
        for row in self.model:
            if row[self.Data.PORT] == port:
                return row

    def find_by_id(self, sample_id):
        for row in self.model:
            if row[self.Data.DATA].get('id') == sample_id:
                return row

    def get_name(self, port):
        row = self.find_by_port(port)
        if row:
            return row[self.Data.NAME]
        else:
            return '...'

    def get_selected(self):
        return [
            row[self.Data.DATA] for row in self.model
            if row[self.Data.SELECTED] and row[self.Data.STATE] not in [Port.BAD, Port.EMPTY]
        ]

    def select_all(self, option=True):
        model, paths = self.selection.get_selected_rows()
        # toggle all selected rows otherwise toggle the whole list
        changed = set()
        if len(paths) > 1:
            for path in paths:
                path = self.filter_model.convert_path_to_child_path(path)
                row = self.search_model[path]
                if row[self.Data.STATE] not in [Port.EMPTY, Port.BAD]:
                    row[self.Data.SELECTED] = option
                    changed.add(row[self.Data.DATA]['id'])
        else:
            for item in self.filter_model:
                row = self.search_model[self.filter_model.convert_iter_to_child_iter(item.iter)]
                if row[self.Data.STATE] not in [Port.EMPTY, Port.BAD]:
                    row[self.Data.SELECTED] = option
                    changed.add(row[self.Data.DATA]['id'])

        cache = self.props.cache
        if changed:
            if option:
                cache |= changed
            else:
                cache -= changed
            self.props.cache = cache

    def clear(self):
        self.model.clear()
        self.group_model.remove_all()
        self.group_registry = {}
        GObject.idle_add(self.emit, 'updated')

    def toggle_row(self, path):
        path = self.filter_model.convert_path_to_child_path(path)
        row = self.search_model[path]
        if row[self.Data.STATE] not in [Port.BAD, Port.EMPTY]:
            selected = not row[self.Data.SELECTED]
            row[self.Data.SELECTED] = selected
            cache = self.cache
            if selected:
                row[self.Data.PROGRESS] = self.Progress.NONE
                cache.add(row[self.Data.DATA]['id'])
            else:
                cache.remove(row[self.Data.DATA]['id'])
            self.props.cache = cache

    def update_states(self, *args, **kwargs):
        for row in self.model:
            port = row[self.Data.PORT]
            if port:
                state = self.beamline.automounter.ports.get(port, Port.UNKNOWN)
                state = state if state in [Port.BAD, Port.MOUNTED, Port.EMPTY] else Port.GOOD
                row[self.Data.STATE] = state
                self.props.ports[port] = state
        self.props.ports = self.ports

    def on_sample_row_changed(self, model, path, itr):
        if self.group_registry:
            val = model[path][self.Data.SELECTED]
            group = model[path][self.Data.GROUP]
            key = model[path][self.Data.UUID]
            self.group_registry[group].update_item(key, val)

    def on_dewar_selected(self, obj, port):
        row = self.find_by_port(port)
        if row:
            self.props.next_sample = row[self.Data.DATA]
        elif self.beamline.is_admin():
            self.props.next_sample = {
                'port': port
            }
        else:
            self.props.next_sample = {}

    def on_sample_mounted(self, obj, param):
        if self.beamline.automounter.sample:
            port = self.beamline.automounter.sample.get('port', '')
            row = self.find_by_port(port)
            if row:
                self.props.current_sample = row[self.Data.DATA]
                row[self.Data.SELECTED] = False
                self.widget.samples_dismount_btn.set_sensitive(True)
            elif self.beamline.is_admin():
                self.props.current_sample = {
                    'port': port,
                }
                self.widget.samples_dismount_btn.set_sensitive(True)
            else:
                self.props.current_sample = {
                    'port': port,
                }
                self.widget.samples_dismount_btn.set_sensitive(False)
        else:
            self.props.current_sample = {}

        self.widget.spinner.stop()
        self.roll_next_sample()

    def on_key_press(self, obj, event):
        return self.widget.samples_search_entry.handle_event(event)

    def on_row_activated(self, cell, path, column):
        path = self.filter_model.convert_path_to_child_path(path)
        row = self.search_model[path]
        self.props.next_sample = row[self.Data.DATA]

    def on_row_toggled(self, cell, path, model):
        path = Gtk.TreePath.new_from_string(path)
        self.toggle_row(path)

    def mount_action(self):
        if not self.next_sample.get('port'):
            if self.current_sample:
                self.dismount_action()
                self.widget.notifier.notify('Switching from Automounter to Manual. Try again after '
                                            'current sample is done dismounting!')
            else:
                self.widget.notifier.notify('Manual Mode: Please mount it manually before proceeding')
                self.props.current_sample = self.next_sample
                self.props.next_sample = {}
        elif self.next_sample and self.beamline.automounter.is_mountable(self.next_sample['port']):
            if self.current_sample and not self.current_sample.get('port'):
                self.widget.notifier.notify('Switching from Manual to Autmounter. Try again after '
                                            'current sample is has been dismounted manually!')
            else:
                self.widget.spinner.start()
                auto.auto_mount(self.beamline, self.next_sample['port'])

    def dismount_action(self):
        if not self.current_sample.get('port'):
            self.widget.notifier.notify('Sample was mounted manually. Please dismount it manually')
            item = self.find_by_id(self.current_sample.get('id'))
            item[self.Data.SELECTED] = False
            self.props.current_sample = {}
            self.roll_next_sample()
        elif self.current_sample and self.beamline.automounter.is_mounted(self.current_sample['port']):
            self.widget.spinner.start()
            auto.auto_dismount(self.beamline)


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
        processed = model[itr][SampleStore.Data.PROGRESS]
        if processed == SampleStore.Progress.ACTIVE:
            cell.set_property("icon-name", 'emblem-synchronizing-symbolic')
        elif processed == SampleStore.Progress.DONE:
            cell.set_property("icon-name", "object-select-symbolic")
        else:
            cell.set_property("icon-name", "content-loading-symbolic")

    def format_processed(self, column, cell, model, itr, data):
        value = model[itr][SampleStore.Data.PROGRESS]
        if value == SampleStore.Progress.DONE:
            cell.set_property("foreground-rgba", Gdk.RGBA(red=0.0, green=0.5, blue=0.0, alpha=1.0))
        else:
            cell.set_property("foreground-rgba", None)

    def get_samples(self):
        return [
            copy(row[SampleStore.Data.DATA])
            for row in self.auto_queue if row[SampleStore.Data.SELECTED]
        ]
