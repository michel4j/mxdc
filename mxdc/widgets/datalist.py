import gtk
import gobject


(
    DATA_COLUMN_SELECT,
    DATA_COLUMN_NAME,
    DATA_COLUMN_CRYSTAL,
    DATA_COLUMN_GROUP,
    DATA_COLUMN_ANGLE,
    DATA_COLUMN_WAVELENGTH,
    DATA_COLUMN_FRAMES,
    DATA_COLUMN_DATA,
) = range(8)

DATA_TYPES = (
    gobject.TYPE_BOOLEAN,
    gobject.TYPE_STRING,
    gobject.TYPE_PYOBJECT,
    gobject.TYPE_STRING,
    gobject.TYPE_FLOAT,
    gobject.TYPE_FLOAT,
    gobject.TYPE_STRING,
    gobject.TYPE_PYOBJECT,
)

DATA_COLUMN_DICT = {
    DATA_COLUMN_SELECT: 'Select',               
    DATA_COLUMN_NAME: 'Name',
    DATA_COLUMN_GROUP: 'Group',    
    DATA_COLUMN_ANGLE: 'Delta',
    DATA_COLUMN_WAVELENGTH: 'Wavelength',
    DATA_COLUMN_FRAMES: 'Frames',
}

class DataList(gtk.ScrolledWindow):
    def __init__(self):
        gtk.ScrolledWindow.__init__(self)
        self.listmodel = gtk.ListStore(*DATA_TYPES) 
                                
        self.listview = gtk.TreeView(self.listmodel)
        self.listview.set_rules_hint(True)
        self.listview.get_selection().set_mode(gtk.SELECTION_MULTIPLE)
        self.__add_columns()
        self.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        self.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.add(self.listview)
        self._first = True

    def load_data(self, data):
        self.clear()
        for item in data:
            self.add_item(item)
            

    def add_item(self, item):
        
        # check if item exists and replace that one if it does otherwise
        # add a new one (Names should be unique)
        iter = self.listmodel.get_iter_first()
        matches = False
        while iter and not matches:
            name = self.listmodel.get_value(iter, DATA_COLUMN_NAME)
            matches = (name == item['name'])
            if not matches: #prevent incrementing iter if there is a match
                iter = self.listmodel.iter_next(iter)
        
        if not matches:
            iter = self.listmodel.append() #None found, insert new one            
            
        crystal = item.get('crystal')
        if crystal is None:
            crystal = {}
        self.listmodel.set(iter,
                DATA_COLUMN_SELECT, False,
                DATA_COLUMN_NAME, item['name'],
                DATA_COLUMN_CRYSTAL, crystal,
                DATA_COLUMN_GROUP, crystal.get('group_name', '-'),
                DATA_COLUMN_ANGLE, item.get('delta_angle'),
                DATA_COLUMN_WAVELENGTH, item.get('wavelength'),
                DATA_COLUMN_FRAMES, item.get('frame_sets'),
                DATA_COLUMN_DATA, item
                )
    
    def __format_float_cell(self, column, renderer, model, iter):
        column_index = renderer.get_data('column')
        value = model.get_value(iter, column_index)
        # Hide negative values
        if value < 0:
            renderer.set_property('text', '-')
        else:
            if column_index == DATA_COLUMN_WAVELENGTH:
                renderer.set_property('text', '%0.4f' % value)
            else:
                renderer.set_property('text', '%0.2f' % value)
        return
    
                        
    def __add_columns(self):        
        for key in [DATA_COLUMN_NAME, DATA_COLUMN_GROUP, DATA_COLUMN_ANGLE, DATA_COLUMN_WAVELENGTH, DATA_COLUMN_FRAMES]:
            renderer = gtk.CellRendererText()
            renderer.set_data('column', key)
            column = gtk.TreeViewColumn(DATA_COLUMN_DICT[key], renderer, text=key)
            if key in [DATA_COLUMN_ANGLE,DATA_COLUMN_WAVELENGTH]:
                column.set_cell_data_func(renderer, self.__format_float_cell)
            column.set_resizable(True)
            self.listview.append_column(column)
        self.listview.set_search_column(DATA_COLUMN_NAME)

    def get_selected(self):
        selection = self.listview.get_selection()
        model, paths = selection.get_selected_rows()
        datasets = []
        for path in paths:
            iter = model.get_iter(path)
            datasets.append(model.get_value(iter, DATA_COLUMN_DATA))
        return datasets
       
    def on_row_toggled(self, cell, path, model):
        iter = model.get_iter(path)
        value = model.get_value(iter, DATA_COLUMN_SELECT)                 
        model.set(iter, DATA_COLUMN_SELECT, (not value) )            
        return True

    def set_row_selected(self, pos, selected=True):
        path = (pos,)
        iter = self.listmodel.get_iter(path)
        self.listmodel.set(iter, DATA_COLUMN_SELECT, selected)
        self.listview.scroll_to_cell(path, use_align=True, row_align=0.9)        
    

    def clear(self):
        self.listmodel.clear()