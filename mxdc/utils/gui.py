import os
import zipfile
import json
from collections import OrderedDict
from collections import namedtuple
from enum import Enum

import gi
import numpy

gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, GObject, Gdk, Pango, Gio, GLib, GdkPixbuf
from mxdc.utils import colors
from mxdc.conf import load_cache, save_cache
from mxdc.utils.misc import slugify
from mxdc.conf import SHARE_DIR


class GUIFile(object):
    """
    GUI Resource File object

    :param name: Resource name (without the extension)
    :param root: top-level (root)
    """

    def __init__(self, name, root=None):
        self.name = name
        self.root = root
        self.wTree = Gtk.Builder()
        self.ui_path = '/org/mxdc/{}.ui'.format(self.name)
        if self.root is not None:
            self.wTree.add_objects_from_resource(self.ui_path, [self.root])
        else:
            self.wTree.add_from_resource(self.ui_path)

    def get_object(self, name):
        """
        Get a widget by name from the resource file.

        :param name: widget name
        :return: widget
        """
        return self.wTree.get_object(name)


class BuilderMixin(object):
    gui_roots = {
        'relative/path/to/file_without_extension': ['root_object']
    }

    def setup_gui(self):
        """
        Initial setup of the GUI based on the class attribute (gui_roots)
        :return:
        """
        self.gui_objects = {
            root: GUIFile(path, root)
            for path, roots in list(self.gui_roots.items()) for root in roots
        }

    def get_builder(self):
        return list(self.gui_objects.values())[0].wTree

    def build_gui(self):
        pass

    def clone(self):
        """
        Make a copy of the Widget
        """
        if self.gui_objects:
            builder = Builder({
                root: GUIFile(path, root)
                for path, roots in list(self.gui_roots.items()) for root in roots
            })
            builder.gui_top = self.gui_top
            builder.gui_roots = self.gui_roots
            return builder

    def __getattr__(self, item):
        if self.gui_objects:
            for root in list(self.gui_objects.values()):
                obj = root.get_object(item)
                if obj:
                    return obj
                obj = root.get_object(item.replace('_', '-'))
                if obj:
                    return obj
        raise AttributeError('{} does not have attribute: {}'.format(self, item))


class Builder(BuilderMixin):
    def __init__(self, objects=None):
        if not objects:
            self.setup_gui()
        else:
            self.gui_objects = objects


RowSpec = namedtuple('ColRow', ['data', 'title', 'type', 'text', 'expand'])


class ColumnSpec(object):
    def __init__(self, *columns):
        """Columns should be a list of 4-tupes
            ColumnNo(int), Title(str), renderer, Format(eg '{0.2f}'
        """

        self.specs = [
            RowSpec(*row) for row in columns
        ]
        self.info = OrderedDict(
            [(col.data, col) for col in self.specs]
        )

    def __getitem__(self, item):
        return self.info[item]

    def items(self):
        return list(self.info.items())

    def keys(self):
        return list(self.info.keys())

    def values(self):
        return list(self.info.values())


class ColumnType(object):
    TEXT = 'text'
    TOGGLE = 'toggle'
    ICON = 'pixbuf'
    NUMBER = 'number'
    COLORSCALE = 'colorscale'


class TreeManager(GObject.GObject):
    class Data(Enum):  A, B = list(range(2))
    Types = [int, int]
    Columns = ColumnSpec(
        (Data.A, 'A', ColumnType.TEXT, '{}', True),
        (Data.B, 'B', ColumnType.TOGGLE, '{:0.3f}', False),
    )
    Icons = {  # (icon-name, color)
        Data.A: ('', '#770000'),
        Data.B: ('', '#770000'),
    }
    tooltips = None
    parent = Data.A  # The column used to group items under the same parent
    flat = False  # whether tree is flat single level or not
    single_click = False
    select_multiple = False

    def __init__(self, view, model=None, colormap=None):
        super().__init__()
        if not model:
            self.model = Gtk.TreeStore(*self.Types)  # make a new model if none is provided
        else:
            self.model = model

        self.view = view
        self.colormap = colormap or colors.PERCENT_COLORMAP
        self.view.set_model(self.model)
        self.add_columns()
        self.selection = self.view.get_selection()
        if self.select_multiple:
            self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        self.selection.connect('changed', self.do_selection_changed)
        self.model.connect('row-changed', self.row_changed)
        self.model.connect('row-deleted', self.row_deleted)
        self.model.connect('row-inserted', self.row_inserted)
        self.view.props.activate_on_single_click = self.single_click
        self.view.connect('row-activated', self.row_activated)
        self.keys = [item.name.lower() for item in self.Data]

    def add_item(self, item, add_parent=True):
        """
        Add an item to the tree
        :param item: a dict
        :return: a tuple of Gtk.TreePath objects for (parent, child), parent path is None for flat trees
        """
        if not self.flat:
            parent_path = None
            parent_itr = self.find_parent_iter(item)
            if parent_itr:
                if not self.model.iter_has_child(parent_itr) and add_parent:
                    row = list(self.model[parent_itr])
                    self.model.append(parent_itr, row=row)
                parent_path = self.model.get_path(parent_itr)
        else:
            parent_itr = parent_path = None
        row = [item.get(key) for key in self.keys]
        child_itr = self.model.append(parent_itr, row=row)
        child_path = self.model.get_path(child_itr)
        return parent_path, child_path

    def find_parent_iter(self, item):
        """
        Find the parent row for a given item.
        :param item: a dict of values for the item about to be added
        :return: a Gtk.TreeItr or None pointing to the parent row
        """
        parent_key = self.keys[self.parent.value]
        parent = self.model.get_iter_first()
        while parent:
            if self.model[parent][self.parent.value] == item.get(parent_key):
                break
            parent = self.model.iter_next(parent)
        return parent

    def add_items(self, items):
        """
        Add a list of items to the data store
        :param items: a list of dicts corresponding to the items
        :return: number of groups added
        """
        groups = set()
        for item in items:
            parent_path, child_path = self.add_item(item)
            groups.add(parent_path)
        return len(groups)

    def row_to_dict(self, row):
        """
        Convert a model row into a dictionary
        :param row: TreeModelRow
        :return: dict representing the item
        """
        return dict(list(zip(self.keys, row)))

    def get_item(self, itr):
        """
        Retrieve the item pointed to by itr
        :param itr: Gtk.TreeItr
        :return:  dict representing the item
        """
        return self.row_to_dict(self.model[itr])

    def get_items(self, itr):
        """
        Retrieve all items under the given parent, if itr is a child, retrieve all siblings. For flat
        Trees, the list will contain a single item.
        :param itr: Gtk.TreeItr
        :return:  a list of dicts representing the children or siblings
        """
        runs = []


        if not self.flat:
            if self.model.iter_has_child(itr):
                parent_itr = itr
            else:
                parent_itr = self.model.iter_parent(itr)
            itr = self.model.iter_children(parent_itr)
            while itr:
                item = self.get_item(itr)
                itr = self.model.iter_next(itr)
                runs.append(item)
        else:
            item = self.get_item(itr)
            runs.append(item)
        return runs

    def clear(self):
        """
        Remove all items from the data store
        """
        self.model.clear()

    def clear_selection(self):
        """Remove all selected items"""
        model, selected = self.selection.get_selected_rows()
        for path in selected:
            row = model[path]
            model.remove(row.iter)


    def make_parent(self, row):
        """
        Make a parent item for a given item
        :param row: a dict for an item
        :return: a dict suitable for adding to the model as a parent
        """
        parent_row = ['']*len(self.keys)
        parent_row[list(self.Columns.keys())[0].value] = row[self.parent.value]
        return parent_row

    def add_columns(self):
        """
        Add Columns to the TreeView and link all signals
        """

        for data, spec in list(self.Columns.items()):
            if spec.type == ColumnType.TOGGLE:
                renderer = Gtk.CellRendererToggle(activatable=True)
                renderer.connect('toggled', self.row_toggled, spec)
                column = Gtk.TreeViewColumn(title=spec.title, cell_renderer=renderer, active=spec.data.value)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_fixed_width(32)
                self.view.append_column(column)
            elif spec.type == ColumnType.COLORSCALE:
                renderer = Gtk.CellRendererText()
                column = Gtk.TreeViewColumn(title=spec.title, cell_renderer=renderer)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_fixed_width(32)
                column.set_cell_data_func(renderer, self.format_colorscale, spec)
                self.view.append_column(column)
            elif spec.type == ColumnType.ICON:
                renderer = Gtk.CellRendererPixbuf()
                column = Gtk.TreeViewColumn(title=spec.title, cell_renderer=renderer)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_fixed_width(32)
                column.set_cell_data_func(renderer, self.format_icon, spec)
                self.view.append_column(column)
            elif spec.type in [ColumnType.TEXT, ColumnType.NUMBER]:
                renderer = Gtk.CellRendererText()
                column = Gtk.TreeViewColumn(title=spec.title, cell_renderer=renderer, text=spec.data.value)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                renderer.props.ellipsize = Pango.EllipsizeMode.END
                column.set_expand(spec.expand)
                column.set_sort_column_id(spec.data.value)
                column.set_cell_data_func(renderer, self.format_cell, spec)
                if spec.type == ColumnType.NUMBER:
                    renderer.set_alignment(0.8, 0.5)
                    #renderer.props.family = 'Monospace'
                self.view.append_column(column)
            if self.tooltips:
                self.view.set_tooltip_column(self.tooltips.value)

    def format_colorscale(self, column, renderer, model, itr,spec):
        """
        Format a colorscale color based on a percentage value
        :param column: Gtk.TreeViewColumn
        :param renderer: Gtk.CellRenderer
        :param model: Gtk.TreeModel
        :param itr: Gtk.TreeIter
        :param spec:    RowSpec
        :return:
        """
        if model.iter_has_child(itr):
            renderer.set_property('text', '')
        else:
            value = model[itr][spec.data.value]
            color = Gdk.RGBA(**self.colormap.rgba(value))
            renderer.set_property("foreground-rgba", color)
            renderer.set_property("text", "\u25a0")

    def format_icon(self, column, renderer, model, itr, spec):
        """
        Format an icon based on a field value
        :param column: Gtk.TreeViewColumn
        :param renderer: Gtk.CellRenderer
        :param model: Gtk.TreeModel
        :param itr: Gtk.TreeIter
        :param spec:    RowSpec
        :return:
        """
        if model.iter_has_child(itr):
            renderer.set_property('icon-name', None)
        else:
            value = model[itr][spec.data.value]
            name, color = self.Icons.get(value, (None, '#ffffff'))
            rgba = Gdk.RGBA()
            rgba.parse(color)
            theme = Gtk.IconTheme.get_default()
            info = theme.lookup_icon(name, 16, Gtk.IconLookupFlags.FORCE_SYMBOLIC)
            icon, is_symbolic = info.load_symbolic(rgba, None, None, None)
            renderer.props.pixbuf = icon

    def format_cell(self, column, renderer, model, itr, spec):
        """
        Method to format cell when values change
        :param column: Gtk.TreeViewColumn
        :param renderer: Gtk.CellRenderer
        :param model: Gtk.TreeModel
        :param itr: Gtk.TreeIter
        :param spec:    RowSpec
        :return:
        """
        if model.iter_has_child(itr):
            parent_row = self.make_parent(model[itr])
            renderer.set_property('text', parent_row[spec.data.value])
        else:
            renderer.set_property('text', spec.text.format(model[itr][spec.data.value]))

    def row_toggled(self, cell, path, spec):
        """
        Method to handle toggling of cells
        :param cell: Gtk.CellRendererToggle
        :param path: Gtk.TreePath
        :param spec: RowSpec
        :return:
        """
        model = self.view.get_model()
        model[path][spec.data.value] = not self.model[path][spec.data.value]

    def do_selection_changed(self, selection):
        """
        Handle changes to the selection
        :param selection: Gtk.TreeSelection
        :return:
        """
        if selection.get_mode() != Gtk.SelectionMode.MULTIPLE:
            model, itr = selection.get_selected()
            return self.selection_changed(model, itr)

    def selection_changed(self, model, itr):
        """
        Handle changes to the selection
        :param selection: Gtk.TreeModel
        :param itr: Gtk.TreeIter
        :return:
        """
        pass

    def row_activated(self, view, path, column):
        """
        Handle activation of rows
        :param view: Gtk.TreeView
        :param path: Gtk.TreePath
        :param column: Gtk.TreeViewColumn
        :return:
        """

    def row_changed(self, model, path, itr):
        """
        :param model: Gtk.TreeModel
        :param path: Gtk.TreePath
        :param itr: Gtk.TreeIter
        :return:
        """

    def row_inserted(self, model, path, itr):
        """
        :param model: Gtk.TreeModel
        :param path: Gtk.TreePath
        :param itr: Gtk.TreeIter
        :return:
        """
        parent_itr = model.iter_parent(itr)
        if parent_itr:
            parent = model.get_path(parent_itr)
            self.view.expand_row(parent, False)
        child = model.get_path(itr)
        self.view.scroll_to_cell(child, None, True, 0.5, 0.5)

    def row_deleted(self, model, path):
        """
        :param model: Gtk.TreeModel
        :param path: Gtk.TreePath
        :return:
        """


class FilteredTreeManager(TreeManager):
    def __init__(self, view, model=None, colormap=None):
        super().__init__()
        if not model:
            self.src_model = Gtk.TreeStore(*self.Types)  # make a new model if none is provided
        else:
            self.src_model = model

        self.view = view
        self.colormap = colormap or colors.PERCENT_COLORMAP
        self.view.set_model(self.model)
        self.add_columns()
        self.selection = self.view.get_selection()
        self.selection.connect('changed', self.do_selection_changed)
        self.model.connect('row-changed', self.row_changed)
        self.view.props.activate_on_single_click = self.single_click
        self.view.connect('row-activated', self.row_activated)
        self.keys = [item.name.lower() for item in self.Data]


class Validator(object):
    """
    Collection of Field Validation Converters
    """
    class Clip(object):
        """
        Convert a value to the specified type and clip it between the specified limits
        """
        def __init__(self, dtype, lo, hi, default=None):
            self.dtype = dtype
            self.lo = lo
            self.hi = hi
            self.default = self.lo if default is None else default

        def __call__(self, val):
            try:
                if self.lo is None and self.hi is None:
                    return self.dtype(val)
                elif self.lo is None:
                    return min(self.dtype(val), self.hi)
                elif self.hi is None:
                    return max(self.lo, self.dtype(val))
                else:
                    return min(max(self.lo, self.dtype(val)), self.hi)
            except (TypeError, ValueError):
                return self.default

    class Float(Clip):
        """
        Convert a value to the specified type and clip it between the specified limits
        """

        def __init__(self, lo, hi, default=None):
            super().__init__(float, lo, hi, default)

    class AngleFrac(Float):

        def fix(self, val):
            return 180. / round(180. / val)

        def __call__(self, val):
            val = super().__call__(val)
            return self.fix(val)


    class Int(Clip):
        """
        Convert a value to the specified type and clip it between the specified limits
        """
        def __init__(self, lo, hi, default=None):
            super().__init__(int, lo, hi, default)

    class String(object):
        """
        Enforce maximum string length
        """
        def __init__(self, max_length, default=''):
            self.max_length = max_length
            self.default = default

        def __call__(self, val):
            return str(val)[:self.max_length]

    class Slug(String):
        def __init__(self, max_length, default=''):
            super().__init__(max_length, default)

        def __call__(self, val):
            return slugify(str(val)[:self.max_length])

    class Enum(object):
        """
        Make sure integer value is within the valid values for an emum type
        """
        def __init__(self, dtype, default=None):
            self.dtype = dtype
            if isinstance(default, self.dtype):
                self.default = default.value
            else:
                try:
                    self.default = self.dtype(default).value
                except ValueError:
                    self.default = list(self.dtype)[0].value

        def __call__(self, val):
            if isinstance(val, self.dtype):
                return val.value
            else:
                try:
                    return self.dtype(int(val)).value
                except (TypeError, ValueError):
                    return self.default

    class Bool(object):
        """
        Convert a value to the specified type
        """
        def __init__(self, default=False):
            self.default = default

        def __call__(self, val):
            try:
                return bool(val)
            except (TypeError, ValueError):
                return self.default

    class Value(object):
        """
        Convert a value to the specified type
        """
        def __init__(self, dtype, default=None):
            self.dtype = dtype
            self.default = default

        def __call__(self, val):
            try:
                return self.dtype(val)
            except (TypeError, ValueError):
                return self.default

    class Pass(object):
        def __call__(self, val):
            return val


class FieldSpec(object):
    """
    Detailed Specification of a single config field in a GUI.
    """

    def __init__(self, name, suffix, text_format, converter=Validator.Pass):
        """
        :param name: field name
        :param suffix: field suffix type
        :param text_format: text format
        :param converter: validator or converter
        """
        self.name = name
        self.suffix = suffix
        self.text_format = text_format
        self.converter = converter

    def set_converter(self, converter):
        """
        Change the converter of the field

        :param converter:
        """
        self.converter = converter

    def field_from(self, builder, prefix):
        """
        Get reference to GUI input widget referenced by the field spec.

        :param builder: The GUI builder containing the widget
        :param prefix: the prefix or the widget
        """

        field_name = f'{prefix}_{self.name}_{self.suffix}'
        return getattr(builder, field_name, None)

    def value_from(self, builder, prefix):
        """
        Get the value contained in the GUI input widget referenced by the field spec

        :param builder: The GUI builder containing the widget
        :param prefix: the prefix or the widget
        """
        field = self.field_from(builder, prefix)
        if field:
            if self.suffix == 'entry':
                raw_value = field.get_text()
            elif self.suffix in ['switch', 'check']:
                raw_value = field.get_active()
            elif self.suffix == 'cbox':
                raw_value = field.get_active_id()
            elif self.suffix == 'spin':
                raw_value = field.get_value()
            elif self.suffix == 'mbox' and field.get_model():
                raw_value = field.get_active()
            else:
                raw_value = None
            return self.converter(raw_value)

    def update_to(self, builder, prefix, value):
        """
        Validate and Update the value contained in the GUI input widget referenced by the field spec

        :param builder: The GUI builder containing the widget
        :param prefix: the prefix or the widget
        :param value:  New value to update to
        """

        field = self.field_from(builder, prefix)
        new_value = self.converter(value)

        if field:
            if self.suffix == 'entry':
                field.set_text(self.text_format.format(new_value))
            elif self.suffix in ['switch', 'check']:
                field.set_active(new_value)
            elif self.suffix == 'cbox':
                field.set_active_id(str(new_value))
            elif self.suffix == 'spin':
                field.set_value(new_value)
            elif self.suffix == 'mbox' and field.get_model():
                new_value = -1 if new_value in [0, None] else new_value
                field.set_active(new_value)

    def connect_to(self, builder, prefix, callback):
        """
        Connect the field to a given callback

        :param builder: The GUI builder containing the widget
        :param prefix: the prefix or the widget
        :param callback: callback function
        :return:  source id of connection
        """

        field = self.field_from(builder, prefix)
        if field:
            if self.suffix in ['switch']:
                return field.connect('activate', callback, self.name)
            elif self.suffix in ['cbox', 'mbox']:
                return field.connect('changed', callback, None, self.name)
            elif self.suffix == 'spin':
                return field.connect('value-changed', callback, None, self.name)
            else:
                field.connect('focus-out-event', callback, self.name)
                return field.connect('activate', callback, None, self.name)


class FormManager(object):
    """
    A controller which manages a set of fields in a form within a user interface monitoring, validating inputs
    and managing persistence between application instances.
    """

    def __init__(self, builder, fields=(), prefix='widget', disabled=(), persist=False):
        """
        :param builder: widget collection
        :param fields: a list of FieldSpec objects
        :param prefix: widget prefix
        :param disabled: tuple of disabled field names
        :param persist: Persist the configuration between instances
        """

        self.builder = builder
        self.fields = {
            spec.name: spec
            for spec in fields
        }
        self.persist = persist
        self.prefix = prefix
        self.disabled = disabled
        self.handlers = {}
        for name, spec in self.fields.items():
            field = spec.field_from(self.builder, self.prefix)
            if field:
                self.handlers[spec.name] = spec.connect_to(self.builder, self.prefix, self.on_change)
            if name in self.disabled:
                field.set_sensitive(False)

        # see if values exist in cache
        if self.persist:
            info = load_cache(self.prefix)
            if info:
                self.set_values(info)

    def set_value(self, name, value, propagate=False):
        """
        Set the value of a field by name

        :param name: name of field
        :param value: value to set
        :param propagate: re-process the form data to update linked fields
        """

        spec = self.fields[name]
        field = spec.field_from(self.builder, self.prefix)
        if field:
            with field.handler_block(self.handlers[name]):
                spec.update_to(self.builder, self.prefix, value)
            if propagate:
                self.on_change(field, None, name)

    def get_value(self, name):
        """
        Get the value of a field by name
        :param name:
        :return: value
        """
        spec = self.fields[name]
        return spec.value_from(self.builder, self.prefix)

    def set_values(self, info, propagate=False):
        """
        Set the values of the fields

        :param info: Dictionary of name value pairs to set. Only pairs present are set
        :param propagate: re-process the form data to update linked fields
        """
        for name, value in info.items():
            if name in self.fields:
                self.set_value(name, value, propagate=propagate)

    def get_values(self):
        """
        Get the dictionary of all name value pairs
        """
        return {
            name: spec.value_from(self.builder, self.prefix)
            for name, spec in self.fields.items()
        }

    def get_defaults(self):
        """
        Return default values
        :return: dictionary
        """

        return {
            name: spec.converter.default
            for name, spec in self.fields.items()
            if hasattr(spec.converter, 'default')
        }

    def on_change(self, field, event, name):
        """
        Handle the change event and validate the field, updating accordingly

        :param field: the field that emitted the event
        :param event: change event data or None
        :param name: name of field
        """

        spec = self.fields.get(name)
        if spec:
            value = spec.value_from(self.builder, self.prefix)
            with field.handler_block(self.handlers[name]):
                spec.update_to(self.builder, self.prefix, value)
            if self.persist:
                self.save()

    def get_field(self, name):
        """
        Fetch the field by name

        :param name: name of field
        :return: widget containing the field
        """

        spec = self.fields.get(name)
        if spec:
            return spec.field_from(self.builder, self.prefix)

    def save(self):
        """
        Save the state of the Form
        """
        save_cache(self.get_values(), self.prefix)


def color_palette(colormap):
    data = 255 * numpy.array(colormap.colors)
    data[-1] = [255, 255, 255]
    return data.ravel().astype(numpy.uint8)


def get_symbol(name, catalog, size=None):
    cat_file = os.path.join(SHARE_DIR, 'data', f'{catalog}.sym')
    with zipfile.ZipFile(cat_file, 'r') as sym:
        index = json.loads(sym.read('symbol.json'))
        if name in index:
            data = sym.read(name)
            stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
            if size is not None:
                pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(
                    stream, *size, True
                )
            else:
                pixbuf = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
            return pixbuf



def register_icons():
    """
    Register named icons
    """
    theme = Gtk.IconTheme.get_default()
    theme.add_resource_path('/org/mxdc/data/icons')