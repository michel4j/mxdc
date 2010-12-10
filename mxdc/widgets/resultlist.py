import gtk, gobject
import sys, os, time
from bcm.utils.configobj import ConfigObj
from mxdc.widgets.dialogs import *

(
    RESULT_COLUMN_STATE,
    RESULT_COLUMN_NAME,
    RESULT_COLUMN_BARCODE,
    RESULT_COLUMN_GROUP,
    RESULT_COLUMN_SCORE,
    RESULT_COLUMN_SG,
    RESULT_COLUMN_CELL,
    RESULT_COLUMN_DETAIL,
    RESULT_SORT_COLUMN,
) = range(9)

RESULT_TYPES = (
    gobject.TYPE_INT,
    gobject.TYPE_STRING,
    gobject.TYPE_STRING,
    gobject.TYPE_STRING,
    gobject.TYPE_FLOAT,
    gobject.TYPE_STRING,
    gobject.TYPE_STRING,
    gobject.TYPE_PYOBJECT,
)

(
    RESULT_STATE_WAITING,
    RESULT_STATE_READY,
    RESULT_STATE_ERROR,) = range(3)

STATE_DICT = {
    RESULT_STATE_WAITING : '#CCCCCC',
    RESULT_STATE_READY: '#006600',
    RESULT_STATE_ERROR: '#CC0000',
}

COLUMN_DICT = {
    RESULT_COLUMN_NAME: 'State',               
    RESULT_COLUMN_NAME: 'Crystal',
    RESULT_COLUMN_BARCODE: 'BarCode',
    RESULT_COLUMN_GROUP: 'Group',
    RESULT_COLUMN_SCORE: 'Score',
    RESULT_COLUMN_SG: 'Spacegroup',
    RESULT_COLUMN_CELL: 'Unit Cell',
}

class ResultList(gtk.ScrolledWindow):
    def __init__(self):
        gtk.ScrolledWindow.__init__(self)
        self.listmodel = gtk.ListStore(*RESULT_TYPES) 
                                
        self.listview = gtk.TreeView(self.listmodel)
        self.listview.set_rules_hint(True)
        self.listview.set_reorderable(True)
        self.listview.set_enable_search(True)
        self.__add_columns()
        self.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        self.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.add(self.listview)

        self._wait_img = gtk.gdk.pixbuf_new_from_file(os.path.join(os.path.dirname(__file__),
                                                               'data/tiny-wait.png'))
        self._ready_img = gtk.gdk.pixbuf_new_from_file(os.path.join(os.path.dirname(__file__),
                                                               'data/tiny-ready.png'))
        self._error_img = gtk.gdk.pixbuf_new_from_file(os.path.join(os.path.dirname(__file__),
                                                               'data/tiny-error.png'))
        self._first = True


    def add_row_activate_handler(self, func):
        return self.listview.connect('row-activated',self.on_row_activated)
    
    def del_row_activate_handler(self, id):
        self.listview.disconnect(id)

    def load_data(self, data):
        self.clear()
        for item in data:
            self.add_item(item)
            

    def add_item(self, item):
        iter = self.listmodel.append()
        self.listmodel.set(iter,
                RESULT_COLUMN_STATE, item.get('state', RESULT_STATE_WAITING),
                RESULT_COLUMN_NAME, item['name'],
                RESULT_COLUMN_BARCODE, item.get('barcode','-'),
                RESULT_COLUMN_GROUP, item.get('group', '-'),
                RESULT_COLUMN_SCORE, item.get('score', -1),
                RESULT_COLUMN_SG, item.get('space_group', '-'),
                RESULT_COLUMN_CELL, item.get('unit_cell', '-'),
                RESULT_COLUMN_DETAIL, item.get('detail', {}),
        )
        return iter

    def update_item(self, iter, data):
        self.listmodel.set(iter,
                RESULT_COLUMN_STATE, data.get('state', RESULT_STATE_ERROR),
                RESULT_COLUMN_SCORE, data.get('score', -1),
                RESULT_COLUMN_SG, data.get('space_group', '-'),
                RESULT_COLUMN_CELL, data.get('unit_cell', '-'),
                RESULT_COLUMN_DETAIL, data.get('detail', {}),
        )
    
    def __format_cell(self, column, renderer, model, iter):
        value = model.get_value(iter, RESULT_COLUMN_STATE)
        renderer.set_property("foreground", STATE_DICT[value])
        return

    def __format_float_cell(self, column, renderer, model, iter):
        value = model.get_value(iter, RESULT_COLUMN_STATE)
        renderer.set_property("foreground", STATE_DICT[value])
        value = model.get_value(iter, RESULT_COLUMN_SCORE)
        # Hide negative values
        if value < 0:
            renderer.set_property('text', '-')
        else:
            renderer.set_property('text', '%8.2f' % value)
        return
    
    def __format_pixbuf(self, column, renderer, model, iter):
        value = model.get_value(iter, RESULT_COLUMN_STATE)
        if value == 0:
            renderer.set_property('pixbuf', self._wait_img)
        elif value == 1:
            renderer.set_property('pixbuf', self._ready_img)
        else:
            renderer.set_property('pixbuf', self._error_img)
        return
    
    
    def __sort_func(self, model, iter1, iter2, data):
        c1v1 = model.get_value(iter1, RESULT_COLUMN_GROUP)
        c1v2 = model.get_value(iter2, RESULT_COLUMN_GROUP)
        c2v1 = model.get_value(iter1, RESULT_COLUMN_SCORE)
        c2v2 = model.get_value(iter2, RESULT_COLUMN_SCORE)
        if c1v1 is None: c1v1 = ''
        if c1v2 is None: c1v2 = ''
        
        if c1v1 > c1v2:
            return -1
        elif c1v1 < c1v2:
            return 1
        else:
            if c2v1 > c2v2:
                return 1
            elif c2v1 < c2v2:
                return -1
            else:
                return 0
                        
    def __add_columns(self):
        # Pending Column
        renderer = gtk.CellRendererPixbuf()
        column = gtk.TreeViewColumn('', renderer)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(24)
        column.set_cell_data_func(renderer, self.__format_pixbuf)
        self.listview.append_column(column)
        
        for key in [RESULT_COLUMN_NAME, RESULT_COLUMN_BARCODE, RESULT_COLUMN_GROUP, RESULT_COLUMN_SCORE, RESULT_COLUMN_SG, RESULT_COLUMN_CELL]:
            renderer = gtk.CellRendererText()
            column = gtk.TreeViewColumn(COLUMN_DICT[key], renderer, text=key)
            if key == RESULT_COLUMN_SCORE:
                column.set_cell_data_func(renderer, self.__format_float_cell)
            else:
                column.set_cell_data_func(renderer, self.__format_cell)
            column.set_resizable(True)
            self.listview.append_column(column)
        self.listview.set_search_column(RESULT_COLUMN_NAME)
        self.listmodel.set_sort_func(RESULT_SORT_COLUMN, self.__sort_func, None)
        self.listmodel.set_sort_column_id(RESULT_SORT_COLUMN, gtk.SORT_DESCENDING)

    def set_row_state(self, pos, state=True):
        path = (pos,)
        iter = self.listmodel.get_iter(path)
        self.listmodel.set(iter, RESULT_COLUMN_STATE, state)
        self.listview.scroll_to_cell(path, use_align=True, row_align=0.9)
        
    

    def clear(self):
        self.listmodel.clear()
