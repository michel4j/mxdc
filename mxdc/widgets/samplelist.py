import gtk, gobject
import sys, os, time

from mxdc.widgets.dialogs import *

(   
    SAMPLE_COLUMN_CONTAINER,
    SAMPLE_COLUMN_STATE,
    SAMPLE_COLUMN_SELECTED,
    SAMPLE_COLUMN_PORT,
    SAMPLE_COLUMN_CODE,
    SAMPLE_COLUMN_NAME,
    SAMPLE_COLUMN_COMMENTS,
    SAMPLE_COLUMN_EDITABLE,
    SAMPLE_COLUMN_GROUP,
    SAMPLE_COLUMN_DATA,
    SAMPLE_COLUMN_PRIORITY,
) = range(11)

COLUMN_DICT = {
    SAMPLE_COLUMN_CONTAINER: 'Container',
    SAMPLE_COLUMN_STATE: 'State', 
    SAMPLE_COLUMN_SELECTED: 'Selected',
    SAMPLE_COLUMN_PORT: 'Port',
    SAMPLE_COLUMN_GROUP: 'Group',
    SAMPLE_COLUMN_CODE: 'BarCode',
    SAMPLE_COLUMN_NAME: 'Name',
    SAMPLE_COLUMN_COMMENTS: 'Comments',  
}

MIN_COLUMN_SET = set([COLUMN_DICT[SAMPLE_COLUMN_CONTAINER].lower(), 
                      COLUMN_DICT[SAMPLE_COLUMN_PORT].lower(),
                      COLUMN_DICT[SAMPLE_COLUMN_CODE].lower(),
                      COLUMN_DICT[SAMPLE_COLUMN_NAME].lower(),
                      COLUMN_DICT[SAMPLE_COLUMN_COMMENTS].lower()])

class SampleList(gtk.ScrolledWindow):

    SAMPLE_STATE_GOOD, SAMPLE_STATE_EMPTY, SAMPLE_STATE_JAM, SAMPLE_STATE_MOUNTED, SAMPLE_STATE_UNKNOWN = range(5)  
    STATUS_COLORS = {
        SAMPLE_STATE_GOOD: '#004400',
        SAMPLE_STATE_EMPTY: '#777777',
        SAMPLE_STATE_JAM: '#990000',
        SAMPLE_STATE_MOUNTED: '#990099',
        SAMPLE_STATE_UNKNOWN: None,
    }
    def __init__(self):
        gtk.ScrolledWindow.__init__(self)
        self.listmodel = gtk.ListStore(
            gobject.TYPE_STRING,
            gobject.TYPE_INT,
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_STRING,
            gobject.TYPE_PYOBJECT,
        )
                        
        self.listview = gtk.TreeView(self.listmodel)
        self.listview.set_rules_hint(True)
        self.listview.set_reorderable(True)
        self.listview.set_enable_search(True)
        self.__add_columns()
        self.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        self.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.add(self.listview)
        self.listview.connect('row-activated',self.on_row_activated)


    def load_data(self, data):
        self.clear()
        for item in data:
            iter = self.listmodel.append()        
            self.listmodel.set(iter,
                SAMPLE_COLUMN_CONTAINER, item['container_name'],
                SAMPLE_COLUMN_STATE, item.get('state', self.SAMPLE_STATE_UNKNOWN), 
                SAMPLE_COLUMN_SELECTED, False,
                SAMPLE_COLUMN_PORT, item['port'],
                SAMPLE_COLUMN_CODE, item['barcode'],
                SAMPLE_COLUMN_NAME, item['name'],
                SAMPLE_COLUMN_COMMENTS, item['comments'],
                SAMPLE_COLUMN_EDITABLE, False,
                SAMPLE_COLUMN_GROUP, item['group'],
                SAMPLE_COLUMN_DATA, item,
            )
            

    def __add_item(self, item):
        iter = self.listmodel.append()        
        self.listmodel.set(iter,
            SAMPLE_COLUMN_CONTAINER, item.get('container_name',''),
            SAMPLE_COLUMN_STATE, item[COLUMN_DICT[SAMPLE_COLUMN_STATE].lower()], 
            SAMPLE_COLUMN_SELECTED, item[COLUMN_DICT[SAMPLE_COLUMN_SELECTED].lower()],
            SAMPLE_COLUMN_PORT, item.get(COLUMN_DICT[SAMPLE_COLUMN_PORT].lower(),''),
            SAMPLE_COLUMN_CODE, item.get(COLUMN_DICT[SAMPLE_COLUMN_CODE].lower(),''),
            SAMPLE_COLUMN_NAME, item.get(COLUMN_DICT[SAMPLE_COLUMN_NAME].lower(),'unknown'),
            SAMPLE_COLUMN_COMMENTS, item.get(COLUMN_DICT[SAMPLE_COLUMN_COMMENTS].lower(),''),
            SAMPLE_COLUMN_EDITABLE, False,
            SAMPLE_COLUMN_GROUP, item['group'],
            SAMPLE_COLUMN_DATA, item,
        )
    
    def __set_color(self,column, renderer, model, iter):
        value = model.get_value(iter, SAMPLE_COLUMN_STATE)
        renderer.set_property("foreground", self.STATUS_COLORS[value])
        return

    def __sort_func(self, model, iter1, iter2, data):
        c1v1 = model.get_value(iter1, SAMPLE_COLUMN_GROUP)
        c1v2 = model.get_value(iter2, SAMPLE_COLUMN_GROUP)
        c2v1 = model.get_value(iter1, SAMPLE_COLUMN_NAME)
        c2v2 = model.get_value(iter2, SAMPLE_COLUMN_NAME)
        if c1v1 is None: c1v1 = ''
        if c1v2 is None: c1v2 = ''
        
        if c1v1 > c1v2:
            return -1
        elif c1v1 < c1v2:
            return 1
        else:
            if c2v1 < c2v2:
                return 1
            elif c2v1 > c2v2:
                return -1
            else:
                return 0
        
                
    def __add_columns(self):
        model = self.listview.get_model()
                                               
        # Selected Column
        renderer = gtk.CellRendererToggle()
        renderer.connect('toggled', self.on_row_toggled, model)
        column = gtk.TreeViewColumn(COLUMN_DICT[SAMPLE_COLUMN_SELECTED], renderer, active=SAMPLE_COLUMN_SELECTED)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(50)
        self.listview.append_column(column)
        
        for key in [SAMPLE_COLUMN_NAME, SAMPLE_COLUMN_GROUP, SAMPLE_COLUMN_CONTAINER, SAMPLE_COLUMN_PORT, SAMPLE_COLUMN_CODE, SAMPLE_COLUMN_COMMENTS]:
            renderer = gtk.CellRendererText()
            renderer.connect("edited", self._on_cell_edited, model, key)
            column = gtk.TreeViewColumn(COLUMN_DICT[key], renderer, text=key, editable=SAMPLE_COLUMN_EDITABLE)
            column.set_cell_data_func(renderer, self.__set_color)
            #column.set_sort_column_id(key)        
            self.listview.append_column(column)
        self.listview.set_search_column(SAMPLE_COLUMN_NAME)
        model.set_sort_func(SAMPLE_COLUMN_PRIORITY, self.__sort_func, None)
        model.set_sort_column_id(SAMPLE_COLUMN_PRIORITY, gtk.SORT_DESCENDING)

    def _on_cell_edited(self, cell, path_string, new_text, model, column):
        iter = model.get_iter_from_string(path_string)
        model.set(iter, column, new_text)
        
    def set_row_selected(self, pos, selected=True):
        path = (pos,)
        iter = self.listmodel.get_iter(path)
        self.listmodel.set(iter, SAMPLE_COLUMN_SELECTED, selected)
        self.listview.scroll_to_cell(path, use_align=True, row_align=0.9)

    def set_row_state(self, pos, state):
        path = (pos,)
        try:
            iter = self.listmodel.get_iter(path)
            self.listmodel.set(iter, SAMPLE_COLUMN_STATE, state)
        except ValueError:
            pass
        
    def on_row_activated(self, treeview, path, column):
        model = treeview.get_model()
        iter = model.get_iter(path)
        value = model.get_value(iter, SAMPLE_COLUMN_SELECTED)                 
        model.set(iter, SAMPLE_COLUMN_SELECTED, (not value) )            
        return True
    
    def on_row_toggled(self, cell, path, model):
        iter = model.get_iter(path)
        value = model.get_value(iter, SAMPLE_COLUMN_SELECTED)                 
        model.set(iter, SAMPLE_COLUMN_SELECTED, (not value) )            
        return True
    
    def on_edit_toggled(self, obj):
        state = obj.get_active()
        model = self.listview.get_model()
        iter = model.get_iter_first()
        while iter:
            model.set_value(iter, SAMPLE_COLUMN_EDITABLE, state)
            iter = model.iter_next(iter)
        return True
        
    
    def get_selected(self):
        model = self.listview.get_model()
        iter = model.get_iter_first()
        items = []
        while iter:
            item = {}
            sel = model.get_value(iter, SAMPLE_COLUMN_SELECTED)
            if sel:
                item = model.get_value(iter, SAMPLE_COLUMN_DATA)
                items.append(item)
            iter = model.iter_next(iter)
        return items

    def select_all(self, option=True):
        model = self.listview.get_model()
        iter = model.get_iter_first()
        items = []
        while iter:
            model.set_value(iter, SAMPLE_COLUMN_SELECTED, option)
            iter = model.iter_next(iter)
        return

    def clear(self):
        model = self.listview.get_model()
        model.clear()
             
        
if __name__ == "__main__":
   
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_default_size(600,400)
    win.set_border_width(2)
    win.set_title("Sample Widget Demo")

    example = SampleList()
    example.load_data(TEST_DATA)

    win.add(example)
    win.show_all()

    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()
        
