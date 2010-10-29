import gtk, gobject
import sys, os, time
from bcm.utils.configobj import ConfigObj

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
) = range(8)

COLUMN_DICT = {
    SAMPLE_COLUMN_CONTAINER: 'Container',
    SAMPLE_COLUMN_STATE: 'State', 
    SAMPLE_COLUMN_SELECTED: 'Selected',
    SAMPLE_COLUMN_PORT: 'Port',
    SAMPLE_COLUMN_CODE: 'BarCode',
    SAMPLE_COLUMN_NAME: 'Name',
    SAMPLE_COLUMN_COMMENTS: 'Comments',  
}

MIN_COLUMN_SET = set([COLUMN_DICT[SAMPLE_COLUMN_CONTAINER].lower(), 
                      COLUMN_DICT[SAMPLE_COLUMN_PORT].lower(),
                      COLUMN_DICT[SAMPLE_COLUMN_CODE].lower(),
                      COLUMN_DICT[SAMPLE_COLUMN_NAME].lower(),
                      COLUMN_DICT[SAMPLE_COLUMN_COMMENTS].lower()])

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

class SampleList(gtk.ScrolledWindow):
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
                SAMPLE_COLUMN_CONTAINER, item['container'],
                SAMPLE_COLUMN_STATE, 0, 
                SAMPLE_COLUMN_SELECTED, False,
                SAMPLE_COLUMN_PORT, item['port'],
                SAMPLE_COLUMN_CODE, item['barcode'],
                SAMPLE_COLUMN_NAME, item['name'],
                SAMPLE_COLUMN_COMMENTS, item['comments'],
                SAMPLE_COLUMN_EDITABLE, False
            )
            

    def __add_item(self, item):
        iter = self.listmodel.append()        
        self.listmodel.set(iter,
            SAMPLE_COLUMN_CONTAINER, item.get(COLUMN_DICT[SAMPLE_COLUMN_CONTAINER].lower(),''),
            SAMPLE_COLUMN_STATE, item[COLUMN_DICT[SAMPLE_COLUMN_STATE].lower()], 
            SAMPLE_COLUMN_SELECTED, item[COLUMN_DICT[SAMPLE_COLUMN_SELECTED].lower()],
            SAMPLE_COLUMN_PORT, item.get(COLUMN_DICT[SAMPLE_COLUMN_PORT].lower(),''),
            SAMPLE_COLUMN_CODE, item.get(COLUMN_DICT[SAMPLE_COLUMN_CODE].lower(),''),
            SAMPLE_COLUMN_NAME, item.get(COLUMN_DICT[SAMPLE_COLUMN_NAME].lower(),'unknown'),
            SAMPLE_COLUMN_COMMENTS, item.get(COLUMN_DICT[SAMPLE_COLUMN_COMMENTS].lower(),''),
            SAMPLE_COLUMN_EDITABLE, False,
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
        
        for key in [SAMPLE_COLUMN_NAME, SAMPLE_COLUMN_CONTAINER, SAMPLE_COLUMN_PORT, SAMPLE_COLUMN_CODE, SAMPLE_COLUMN_COMMENTS]:
            renderer = gtk.CellRendererText()
            renderer.connect("edited", self._on_cell_edited, model, key)
            column = gtk.TreeViewColumn(COLUMN_DICT[key], renderer, text=key, editable=SAMPLE_COLUMN_EDITABLE)
            column.set_cell_data_func(renderer, self.__set_color)
            #column.set_sort_column_id(key)        
            self.listview.append_column(column)
        self.listview.set_search_column(SAMPLE_COLUMN_NAME)

    def _on_cell_edited(self, cell, path_string, new_text, model, column):
        iter = model.get_iter_from_string(path_string)
        model.set(iter, column, new_text)
        
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
                item[COLUMN_DICT[SAMPLE_COLUMN_CODE].lower()] = model.get_value(iter, SAMPLE_COLUMN_CODE)
                item[COLUMN_DICT[SAMPLE_COLUMN_NAME].lower()] = model.get_value(iter, SAMPLE_COLUMN_NAME)
                item[COLUMN_DICT[SAMPLE_COLUMN_PORT].lower()] = model.get_value(iter, SAMPLE_COLUMN_PORT)
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
    
    def export_xls(self, filename):
        model = self.listview.get_model()
        from pyExcelerator import Workbook
        wb = Workbook()
        wso = wb.add_sheet('0')
        columns = [COLUMN_DICT[SAMPLE_COLUMN_CONTAINER], 
                   COLUMN_DICT[SAMPLE_COLUMN_PORT],
                   COLUMN_DICT[SAMPLE_COLUMN_CODE],
                   COLUMN_DICT[SAMPLE_COLUMN_NAME],
                   COLUMN_DICT[SAMPLE_COLUMN_COMMENTS],]                  
        for i in range(len(columns)):
            wso.write(0, i, columns[i])
        col = 1
        iter = model.get_iter_first()
        while iter:      
            rowinfo = [model.get_value(iter, SAMPLE_COLUMN_CONTAINER),
                       model.get_value(iter, SAMPLE_COLUMN_PORT),
                       model.get_value(iter, SAMPLE_COLUMN_CODE),
                       model.get_value(iter, SAMPLE_COLUMN_NAME),
                       model.get_value(iter, SAMPLE_COLUMN_COMMENTS)]
            for j in range(len(rowinfo)):
                wso.write(col, j, rowinfo[j])
            col +=1
            iter = model.iter_next(iter)
        wb.save(filename)

    def export_csv(self, filename):
        model = self.listview.get_model()
        import csv
        w = csv.writer(open(filename,'w'))
        columns = [COLUMN_DICT[SAMPLE_COLUMN_CONTAINER], 
                   COLUMN_DICT[SAMPLE_COLUMN_PORT],
                   COLUMN_DICT[SAMPLE_COLUMN_CODE],
                   COLUMN_DICT[SAMPLE_COLUMN_NAME],
                   COLUMN_DICT[SAMPLE_COLUMN_COMMENTS],]                  
        w.writerow( columns)
        iter = model.get_iter_first()
        while iter:      
            rowinfo = [model.get_value(iter, SAMPLE_COLUMN_CONTAINER),
                       model.get_value(iter, SAMPLE_COLUMN_PORT),
                       model.get_value(iter, SAMPLE_COLUMN_CODE),
                       model.get_value(iter, SAMPLE_COLUMN_NAME),
                       model.get_value(iter, SAMPLE_COLUMN_COMMENTS)]
            w.writerow(rowinfo)
            iter = model.iter_next(iter)

    def import_csv(self, filename):
        import csv
        model = self.listview.get_model()
        csvfile = open(filename)
        dialect = csv.Sniffer().sniff(csvfile.read(1024))
        csvfile.seek(0)
        reader = csv.reader(csvfile, dialect)
        header = reader.next()
        hset = set([x.lower() for x in header])
        try:
            assert(hset.issuperset(MIN_COLUMN_SET))
        except:
            missing = ', '.join(MIN_COLUMN_SET.difference(hset))
            header = 'Missing Columns in "%s"' % os.path.basename(filename)
            subhead = 'The following required columns "%s" were not found' % missing
            error(header, subhead)
            csvfile.close()
            return
            
        self.clear()
        for row in reader:
            item = {COLUMN_DICT[SAMPLE_COLUMN_STATE].lower(): 0, 
                    COLUMN_DICT[SAMPLE_COLUMN_SELECTED].lower(): False}
            for i in range(len(header)):
                item[header[i].lower()] = row[i]
            self.__add_item(item)
        csvfile.close()
            

    def import_xls(self, filename):
        import pyExcelerator as xls
        sheet, values = xls.parse_xls(filename)[0]
        rid = set([k[0] for k in values.keys()])
        cid = set([k[1] for k in values.keys()])
        rows = []
        for r in rid:
            row = []
            for c in cid:
                row.append( values.get((r,c), '') )
            rows.append(row)
        header = rows[0]
        hset = set([x.lower() for x in header])
        try:
            assert(hset.issuperset(MIN_COLUMN_SET))
        except:
            missing = ', '.join(MIN_COLUMN_SET.difference(hset))
            header = 'Missing Columns in "%s"' % os.path.basename(filename)
            subhead = 'The following required columns "%s" were not found' % missing
            error(header, subhead)
            csvfile.close()
            return
        
        self.clear()
        for row in rows[1:]:
            item = {COLUMN_DICT[SAMPLE_COLUMN_STATE].lower(): 0, 
                    COLUMN_DICT[SAMPLE_COLUMN_SELECTED].lower(): False}
            for i in range(len(header)):
                item[header[i].lower()] = row[i]
            self.__add_item(item)
         
        
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
        
