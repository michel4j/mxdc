import gtk, gobject
import sys, os, time
import random

(
    SAMPLE_SELECTED,
    SAMPLE_ADDRESS,
    SAMPLE_CODE,
    SAMPLE_DESCR,
    SAMPLE_DONE,
) = range(5)

dummy_data = []
for port in ['L','R','M']:
    for puck in ['A','B','C','D']:
        for pin in range(1,17):
            item = {
                'selected': False,
                'address': "%c%c%02d" % (port,puck,pin), 
                'code': "%010d" % random.randrange(0, 4294967296),
                'description': 'No description yet',
                'done': False,
                }
            dummy_data.append(item)

class SampleManager(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self, False,6)
        self.model = gtk.ListStore(
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_BOOLEAN, )
        
        self.view = gtk.TreeView(self.model)
        self.view.set_rules_hint(True)
        self.view.set_property('rubber-banding', True)
        self.view.get_selection().set_mode(gtk.SELECTION_MULTIPLE)
        self.view.set_property('headers-clickable', True)
        
        sw = gtk.ScrolledWindow()
        sw.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add(self.view)
        
        bbox = gtk.HButtonBox()
        bbox.set_layout(gtk.BUTTONBOX_START)
        bbox.set_spacing(6)
        self.select_btn = gtk.Button('Select')
        self.select_btn.connect('clicked', self.on_select_clicked, True)
        self.deselect_btn = gtk.Button('De-select')
        self.deselect_btn.connect('clicked', self.on_select_clicked, False)
        bbox.pack_start(self.select_btn)
        bbox.pack_start(self.deselect_btn)
        self.pack_start(bbox, expand=False, fill=False)
        self.pack_start(sw, expand=True, fill=True)
       
        self.__add_columns()
        
    
    def add_item(self, item):
        iter = self.model.append()        
        self.model.set(iter, 
            SAMPLE_SELECTED, item['selected'], 
            SAMPLE_ADDRESS, item['address'],
            SAMPLE_CODE, item['code'],
            SAMPLE_DESCR, item['description'],
            SAMPLE_DONE, item['done'],
        )
        
    def __add_columns(self):
        # Selected Column
        renderer = gtk.CellRendererToggle()
        renderer.connect('toggled', self.on_item_toggled)
        column = gtk.TreeViewColumn('Select', renderer, active=SAMPLE_SELECTED)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(50)
        self.view.append_column(column)
        
        # Port Column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Address', renderer, text=SAMPLE_ADDRESS)
        column.set_cell_data_func(renderer, self.__done_color)
        self.view.append_column(column)

        # Code Column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Code', renderer, text=SAMPLE_CODE)
        column.set_cell_data_func(renderer, self.__done_color)
        self.view.append_column(column)

        # Description Column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Description', renderer, text=SAMPLE_DESCR)
        column.set_cell_data_func(renderer, self.__done_color)
        self.view.append_column(column)

    def __done_color(self, column, renderer, model, iter):
        value = model.get_value(iter, SAMPLE_DONE)
        if value:
            renderer.set_property("foreground", '#0000cc')
        else:
            renderer.set_property("foreground", None)
        return

    def on_item_toggled(self, cell, path):
        iter = self.model.get_iter(path)
        selected = self.model.get_value(iter, SAMPLE_SELECTED)
        self.model.set_value(iter, SAMPLE_SELECTED, not selected)
    
    def on_select_clicked(self, obj, val):
        model, rows = self.view.get_selection().get_selected_rows()
        for path in rows:
            iter = self.model.get_iter(path)
            selected = self.model.get_value(iter, SAMPLE_SELECTED)
            self.model.set_value(iter, SAMPLE_SELECTED, val)
        
if __name__ == "__main__":
   
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_default_size(300,400)
    win.set_border_width(2)
    win.set_title("Sample Manager Widget Demo")

    example = SampleManager()
    
    for item in dummy_data:
        example.add_item(item)
        
    win.add(example)
    win.show_all()

    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()
