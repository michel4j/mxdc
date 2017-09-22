import os
from collections import OrderedDict
from collections import namedtuple

import gi
from enum import Enum

gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, GObject, Gdk
from mxdc.utils import colors

class GUIFile(object):
    def __init__(self, name, root=None):
        self.name = name
        self.root = root
        self.wTree = Gtk.Builder()
        self.ui_file = "%s.ui" % self.name
        if os.path.exists(self.ui_file):
            if self.root is not None:
                self.wTree.add_objects_from_file(self.ui_file, [self.root])
            else:
                self.wTree.add_from_file(self.ui_file)

    def get_widget(self, name):
        return self.wTree.get_object(name)


def make_icon_label(txt, stock_id=None):
    aln = Gtk.Alignment(xalign=0.5, yalign=0.5, xscale=1, yscale=1)
    aln.set_padding(0, 0, 6, 6)
    box = Gtk.Box(False, 2, orientation=Gtk.Orientation.HORIZONTAL)
    aln.label = Gtk.Label(label=txt)
    aln.label.set_use_markup(True)
    box.pack_end(aln.label, False, False, 0)
    aln.icon = Gtk.Image()
    box.pack_start(aln.icon, False, False, 0)
    if stock_id is not None:
        aln.icon.set_from_stock(stock_id, Gtk.IconSize.MENU)
    aln.add(box)
    aln.show_all()
    return aln


def make_tab_label(txt):
    label = Gtk.Label(label=txt)
    label.set_padding(6, 0)
    return label


class BuilderMixin(object):
    gui_top = os.path.join(os.environ['MXDC_PATH'], 'mxdc', 'widgets')
    gui_roots = {
        'relative/path/to/file_without_extension': ['root_object']
    }

    def setup_gui(self):
        self.gui_objects = {
            root: GUIFile(os.path.join(self.gui_top, path), root)
            for path, roots in self.gui_roots.items() for root in roots
        }

    def build_gui(self):
        pass

    def clone(self):
        if self.gui_objects:
            builder = Builder({
                root: GUIFile(os.path.join(self.gui_top, path), root)
                for path, roots in self.gui_roots.items() for root in roots
            })
            builder.gui_top = self.gui_top
            builder.gui_roots = self.gui_roots
            return builder

    def __getattr__(self, item):
        if self.gui_objects:
            for xml in self.gui_objects.values():
                obj = xml.get_widget(item)
                if obj:
                    return obj
        raise AttributeError('{} does not have attribute: {}'.format(self, item))


class Builder(BuilderMixin):
    def __init__(self, objects=None):
        if not objects:
            self.setup_gui()
        else:
            self.gui_objects = objects


RowSpec = namedtuple('ColRow', ['data', 'title', 'type', 'text'])


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
        return self.info.items()

    def keys(self):
        return self.info.keys()

    def values(self):
        return self.info.values()



class ColumnType(object):
    TEXT = 'text'
    TOGGLE = 'toggle'
    ICON = 'pixbuf'
    NUMBER = 'number'
    COLORSCALE = 'colorscale'


class TreeManager(GObject.GObject):
    class Data(Enum):  A, B = range(2)
    Types = [int, int]
    Columns = ColumnSpec(
        (Data.A, 'A', ColumnType.TEXT, '{}'),
        (Data.B, 'B', ColumnType.TOGGLE, '{:0.3f}'),
    )
    parent = Data.A  # The column used to group items under the same parent
    flat = False  # whether tree is flat single level or not
    single_click = False

    def __init__(self, view, colormap=None):
        super(TreeManager, self).__init__()
        self.model = Gtk.TreeStore(*self.Types)
        self.view = view
        self.colormap = colormap or colors.PERCENT_COLORMAP
        self.view.set_model(self.model)
        self.add_columns()
        self.selection = self.view.get_selection()
        self.selection.connect('changed', self.selection_changed)
        self.view.props.activate_on_single_click = self.single_click
        self.view.connect('row-activated', self.row_activated)
        self.keys = [item.name.lower() for item in self.Data]

    def add_item(self, item):
        """
        Add an item to the tree
        @param item: a dict
        @return: a tuple of Gtk.TreePath objects for (parent, child), parent path is None for flat trees
        """
        if not self.flat:
            parent_path = None
            parent_itr = self.find_parent_iter(item)
            if parent_itr:
                if not self.model.iter_has_child(parent_itr):
                    row = list(self.model[parent_itr])
                    child_itr = self.model.append(parent_itr, row=row)
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
        @param item: a dict of values for the item about to be added
        @return: a Gtk.TreeItr or None pointing to the parent row
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
        @param items: a list of dicts corresponding to the items
        @return: number of groups added
        """
        groups = set()
        for item in items:
            parent_path, child_path = self.add_item(item)
            groups.add(parent_path)
        return len(groups)

    def get_item(self, itr):
        """
        Retrieve the item pointed to by itr
        @param itr: Gtk.TreeItr
        @return:  dict representing the item
        """
        return dict(zip(self.keys, self.model[itr]))

    def get_items(self, itr):
        """
        Retrieve all items under the given parent, if itr is a child, retrieve all siblings. For flat
        Trees, the list will contain a single item.
        @param itr: Gtk.TreeItr
        @return:  a list of dicts representing the children or siblings
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

    def make_parent(self, row):
        """
        Make a parent item for a given item
        @param row: a dict for an item
        @return: a dict suitable for adding to the model as a parent
        """
        parent_row = ['']*len(self.keys)
        parent_row[self.Columns.keys()[0].value] = row[self.parent.value]
        return parent_row

    def add_columns(self):
        """
        Add Columns to the TreeView and link all signals
        """
        for data, spec in self.Columns.items():
            if spec.type == ColumnType.TOGGLE:
                renderer = Gtk.CellRendererToggle(activatable=True)
                renderer.connect('toggled', self.row_toggled, spec)
                column = Gtk.TreeViewColumn(title=spec.title, cell_renderer=renderer, active=spec.data.value)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_fixed_width(50)
                self.view.append_column(column)
            elif spec.type == ColumnType.COLORSCALE:
                renderer = Gtk.CellRendererText()
                column = Gtk.TreeViewColumn(title=spec.title, cell_renderer=renderer)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_fixed_width(50)
                self.view.append_column(column)
                column.set_cell_data_func(renderer, self.format_colorscale, spec)
            elif spec.type in [ColumnType.TEXT, ColumnType.NUMBER]:
                renderer = Gtk.CellRendererText()
                column = Gtk.TreeViewColumn(title=spec.title, cell_renderer=renderer, text=spec.data.value)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_expand(True)
                column.set_sort_column_id(spec.data.value)
                column.set_cell_data_func(renderer, self.format_cell, spec)
                if spec.type == ColumnType.NUMBER:
                    renderer.set_alignment(0.8, 0.5)
                    renderer.props.family = 'Monospace'
                self.view.append_column(column)

    def format_colorscale(self, column, renderer, model, itr,spec):
        """
        Format a colorscale color based on a percentage value
        @param column: Gtk.TreeViewColumn
        @param renderer: Gtk.CellRenderer
        @param model: Gtk.TreeModel
        @param itr: Gtk.TreeIter
        @param spec:    RowSpec
        @return:
        """
        if model.iter_has_child(itr):
            renderer.set_property('text', '')
        else:
            value = model[itr][spec.data.value]
            color = Gdk.RGBA(**self.colormap.rgba(value))
            renderer.set_property("foreground-rgba", color)
            renderer.set_property("text", u"\u25a0")

    def format_cell(self, column, renderer, model, itr, spec):
        """
        Method to format cell when values change
        @param column: Gtk.TreeViewColumn
        @param renderer: Gtk.CellRenderer
        @param model: Gtk.TreeModel
        @param itr: Gtk.TreeIter
        @param spec:    RowSpec
        @return:
        """
        if model.iter_has_child(itr):
            parent_row = self.make_parent(model[itr])
            renderer.set_property('text', parent_row[spec.data.value])
        else:
            renderer.set_property('text', spec.text.format(model[itr][spec.data.value]))

    def row_toggled(self, cell, path, spec):
        """
        Method to handle toggling of cells
        @param cell: Gtk.CellRendererToggle
        @param path: Gtk.TreePath
        @param spec: RowSpec
        @return:
        """
        self.model[path][spec.data.value] = not self.model[path][spec.data.value]

    def selection_changed(self, selection):
        """
        Handle changes to the selection
        @param selection: Gtk.TreeSelection
        @return:
        """
        pass

    def row_activated(self, view, path, column):
        """
        Handle activation of rows
        @param view: Gtk.TreeView
        @param path: Gtk.TreePath
        @param column: Gtk.TreeViewColumn
        @return:
        """
