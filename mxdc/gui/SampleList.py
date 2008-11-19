import gtk, gobject
import sys, os, time
from bcm.tools.configobj import ConfigObj
from bcm import utils

from Dialogs import *

(
    SAMPLE_COLUMN_STATE,
    SAMPLE_COLUMN_SELECTED,
    SAMPLE_COLUMN_PORT,
    SAMPLE_COLUMN_CODE,
    SAMPLE_COLUMN_NAME,
    SAMPLE_COLUMN_COMMENTS,
) = range(6)

COLUMN_DICT = {
    SAMPLE_COLUMN_STATE: 'State', 
    SAMPLE_COLUMN_SELECTED: 'Selected',
    SAMPLE_COLUMN_PORT: 'Port',
    SAMPLE_COLUMN_CODE: 'Code',
    SAMPLE_COLUMN_NAME: 'Name',
    SAMPLE_COLUMN_COMMENTS: 'Comments',  
}

(
    SAMPLE_STATE_NONE,
    SAMPLE_STATE_NEXT,
    SAMPLE_STATE_RUNNING,
    SAMPLE_STATE_PAUSED,
    SAMPLE_STATE_PROCESSED,
) = range(5)

STATE_DICT = {
    SAMPLE_STATE_NONE : None,
    SAMPLE_STATE_RUNNING : '#cc0099',
    SAMPLE_STATE_PAUSED : '#660033',
    SAMPLE_STATE_PROCESSED: '#cc0000',
    SAMPLE_STATE_NEXT: '#33cc33',
}

test_data = \
[(0, False, 'LA1',  '60482','Normal', 'scrollable notebooks and hidden tabs'),
 (0, False, 'LA2', '60620', 'Critical','gdk_window_clear_area(gdkwindow-win32.c)'),
 (0, False, 'LA3', '50214', 'Major', 'Xft support does not clean up correctly'),
 (0, True, 'LA4',  '52877', 'Major', 'GtkFileSelection needs a refresh method. '),
 (0, False, 'LA5', '56070', 'Normal', "Can't click button after setting in sensitive"),
 (0, True, 'LA6',  '56355', 'Normal', 'GtkLabel - Not all changes propagate correctly'),
 (0, False, 'LA7', '50055', 'Normal', 'Rework width/height computations for TreeView'),
 (0, False, 'LA8', '58278', 'Normal', "gtk_dialog_set_response_sensitive() doesn't work"),
 (0, False, 'LA9', '55767', 'Normal', 'Getters for all setters'),
 (0, False, 'LA10', '56925', 'Normal', 'Gtkcalender size'),
 (0, False, 'LA11', '56221', 'Normal', 'Selectable label needs right-click copy menu'),
 (0, True, 'LA12',  '50939', 'Normal', 'Add shift clicking to GtkTextView'),
 (0, False, 'LA13', '6112',  'Enhancement', 'netscape-like collapsable toolbars'),
 (0, False, 'LA14', '00001',    'Normal', 'First bug :=)')]


class SampleList(gtk.ScrolledWindow):
    def __init__(self):
        gtk.ScrolledWindow.__init__(self)
        self.listmodel = gtk.ListStore(
            gobject.TYPE_INT,
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,           
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
        for item in data:
            iter = self.listmodel.append()        
            self.listmodel.set(iter, 
                SAMPLE_COLUMN_STATE, item[SAMPLE_COLUMN_STATE], 
                SAMPLE_COLUMN_SELECTED, item[SAMPLE_COLUMN_SELECTED],
                SAMPLE_COLUMN_PORT, item[SAMPLE_COLUMN_PORT],
                SAMPLE_COLUMN_CODE, item[SAMPLE_COLUMN_CODE],
                SAMPLE_COLUMN_NAME, item[SAMPLE_COLUMN_NAME],
                SAMPLE_COLUMN_COMMENTS, item[SAMPLE_COLUMN_COMMENTS],
            )
            

    def __add_item(self, item):
        iter = self.listmodel.append()        
        self.listmodel.set(iter, 
            SAMPLE_COLUMN_STATE, item['state'], 
            SAMPLE_COLUMN_SELECTED, item['selected'],
            SAMPLE_COLUMN_PORT, item['port'],
            SAMPLE_COLUMN_CODE, item['code'],
            SAMPLE_COLUMN_NAME, item['name'],
            SAMPLE_COLUMN_COMMENTS, item['comments'],
        )
    
    def __set_color(self,column, renderer, model, iter):
        value = model.get_value(iter, SAMPLE_COLUMN_STATE)
        renderer.set_property("foreground", STATE_DICT[value])
        return
        
                
    def __add_columns(self):
        model = self.listview.get_model()
                                               
        # Selected Column
        renderer = gtk.CellRendererToggle()
        renderer.connect('toggled', self.on_row_toggled, model)
        column = gtk.TreeViewColumn(COLUMN_DICT[SAMPLE_COLUMN_SELECTED], renderer, active=SAMPLE_COLUMN_SELECTED)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(50)
        self.listview.append_column(column)
        
        for key in [SAMPLE_COLUMN_PORT, SAMPLE_COLUMN_CODE, SAMPLE_COLUMN_NAME,SAMPLE_COLUMN_COMMENTS]:
            renderer = gtk.CellRendererText()
            column = gtk.TreeViewColumn(COLUMN_DICT[key], renderer, text=key)
            column.set_cell_data_func(renderer, self.__set_color)
            #column.set_sort_column_id(key)        
            self.listview.append_column(column)
        self.listview.set_search_column(SAMPLE_COLUMN_NAME)
        
    def set_row_selected(self, pos, selected=True):
        path = (pos,)
        iter = self.listmodel.get_iter(path)
        self.listmodel.set(iter, SAMPLE_COLUMN_SELECTED, selected)
        self.listview.scroll_to_cell(path, use_align=True, row_align=0.9)

    def set_row_state(self, pos, state=SAMPLE_STATE_NONE):
        path = (pos,)
        iter = self.listmodel.get_iter(path)
        self.listmodel.set(iter, SAMPLE_COLUMN_SELECTED, selected)
        self.listview.scroll_to_cell(path, use_align=True, row_align=0.9)
        
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
    

                                                                                                                                                                                    
if __name__ == "__main__":
   
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_default_size(600,400)
    win.set_border_width(2)
    win.set_title("Sample Widget Demo")

    example = SampleList()
    example.load_data(test_data)

    win.add(example)
    win.show_all()

    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()
        
