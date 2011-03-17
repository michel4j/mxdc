'''
Created on May 14, 2010

@author: michel
'''

import os
import gobject
import gtk
import gtk.glade
import time
from mxdc.widgets import dialogs
from mxdc.utils.xlsimport import XLSLoader
from mxdc.utils.config import load_config, save_config

try:
    import json
except:
    import simplejson as json

SAMPLES_DB_CONFIG = 'samples_db.json'
XTALS_DB_CONFIG = 'crystals_db.json'
CNT_DB_CONFIG = 'containers_db.json'

( STATUS_NOT_LOADED,
  STATUS_LOADED,
) = range(2)

STATUS_COLORS = {
    STATUS_NOT_LOADED: '#999999',
    STATUS_LOADED: '#000000',
}

class CrystalStore(gtk.ListStore):
    (   
        NAME,
        PORT,
        GROUP,
        CONTAINER,
        STATUS,
        DATA,
    ) = range(6)
    
    def __init__(self):
        gtk.ListStore.__init__(self,                
            gobject.TYPE_STRING, 
            gobject.TYPE_STRING, 
            gobject.TYPE_STRING,
            gobject.TYPE_STRING,
            gobject.TYPE_INT,
            gobject.TYPE_PYOBJECT,
            )
            
    
    def add_crystal(self, item):
        iter = self.append()
        self.set(iter, 
            self.NAME, item['name'],
            self.GROUP, item['group'],
            self.PORT, item['port'],
            self.CONTAINER, item['container_name'],
            self.STATUS, item['load_status'],
            self.DATA, item)
                    
class ContainerStore(gtk.ListStore):
    (
        NAME,
        TYPE,
        STALL,
        LOADED,
        DATA,
        EDITABLE,
    ) = range(6)
    
    def __init__(self):
        gtk.ListStore.__init__(self,
            gobject.TYPE_STRING, 
            gobject.TYPE_STRING, 
            gobject.TYPE_STRING,
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_PYOBJECT,
            gobject.TYPE_BOOLEAN,
            )
            
        
    def add_container(self, item):
        iter = self.append()
        self.set(iter,
            self.NAME, item['name'],
            self.TYPE, item['type'],
            self.STALL, item['load_position'],
            self.LOADED, item['loaded'],
            self.DATA, item,
            self.EDITABLE, (item['type'] in ['Uni-Puck','Cassette']))
            
         
class DewarLoader(gtk.Frame):
    __gsignals__ = {
            'samples-changed': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, []),
            'sample-selected': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
    }
    
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(
            os.path.join(os.path.dirname(__file__), 'data', 'sample_loader.glade'),
            'sample_loader')

        self.add(self.sample_loader)
        self.selected_crystal = None

        #containers pane
        self.containers_view = self.__create_containers_view()
        self.inventory_sw.add(self.containers_view)

        #crystals pane
        self.crystals_view = self.__create_crystals_view()
        self.crystals_view.connect('row-activated',self.on_crystal_activated)

        self.crystals_sw.add(self.crystals_view)
                
        #btn commands
        self.clear_btn.connect('clicked', lambda x: self.clear_inventory())

        #btn signals
        self.file_btn.connect('clicked', self.on_import_file)
        self.load_saved_database()
        
    def __getattr__(self, key):
        try:
            return super(DewarLoader).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
    
    def __create_containers_view(self):
        self.containers = ContainerStore()
        model = self.containers

        treeview = gtk.TreeView(self.containers)
   
        treeview.set_rules_hint(True)

        # column for container name
        column = gtk.TreeViewColumn('Container', gtk.CellRendererText(),
                                    text=model.NAME)
        column.set_sort_column_id(model.NAME)
        treeview.append_column(column)

        # columns for container type
        column = gtk.TreeViewColumn('Type', gtk.CellRendererText(),
                                    text=model.TYPE)
        column.set_sort_column_id(model.TYPE)
        treeview.append_column(column)

        # column for Stall
        renderer = gtk.CellRendererText()
        renderer.connect("edited", self.on_stall_edited)
        column = gtk.TreeViewColumn('Position', renderer,
                                     text=model.STALL, editable=model.EDITABLE)
        column.set_sort_column_id(model.STALL)
        treeview.append_column(column)
        return treeview
               
    def __create_crystals_view(self):
        self.crystals = CrystalStore()
        model = self.crystals
        treeview = gtk.TreeView(self.crystals)
        treeview.set_rules_hint(True)

        # column for name
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Name", renderer, text=model.NAME)
        column.set_cell_data_func(renderer, self._row_color)
        column.set_sort_column_id(model.NAME)
        treeview.append_column(column)

        # column for port
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Port", renderer, text=model.PORT)
        column.set_cell_data_func(renderer, self._row_color)
        column.set_sort_column_id(model.PORT)
        treeview.append_column(column)

        # column for group
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Group", renderer, text=model.GROUP)
        column.set_cell_data_func(renderer, self._row_color)
        column.set_sort_column_id(model.GROUP)
        treeview.append_column(column)                        

        # column for group
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Container", renderer, text=model.CONTAINER)
        column.set_sort_column_id(model.CONTAINER)
        column.set_cell_data_func(renderer, self._row_color)
        treeview.append_column(column)                        
        return treeview

    def _row_color(self, column, renderer, model, iter):
        value = model.get_value(iter, model.STATUS)
        color = STATUS_COLORS.get(value)
        renderer.set_property("foreground", color)

    def _notify_changes(self):
        gobject.idle_add(self.emit, 'samples-changed')
        if self.selected_crystal is not None:
            iter = self.crystals.get_iter(self.selected_crystal)
            crystal_data = self.crystals.get_value(iter, self.crystals.DATA)        
            gobject.idle_add(self.emit, 'sample-selected', crystal_data)
    
    def do_samples_changed(self, obj=None):
        pass

    def do_sample_selected(self, obj=None):
        pass

    def on_stall_edited(self, cell, path_string, new_text):
        iter = self.containers.get_iter_from_string(path_string)
        new_stall = new_text.strip().upper()
        old_stall = self.containers.get_value(iter, self.containers.STALL)
        cnt_detail = self.containers.get_value(iter, self.containers.DATA)
        
        if new_stall == old_stall.strip().upper():
            return 
        
        container_type = self.containers.get_value(iter, self.containers.TYPE)
        VALID_STALLS = {
            'Uni-Puck': ['RA', 'RB', 'RC', 'RD','MA', 'MB', 'MC', 'MD', 'LA', 'LB', 'LC', 'LD', ''],
            'Cassette': ['R','M', 'L',''],
        }
        
        data = {'stall': new_stall, 'exists': False, 'used': set()}
        def validate(model, path, iter, data):
            if iter is not None:
                pos = model.get_value(iter, model.STALL).strip().upper()
                # check if position is occupied. Take care of cassettes and uni-pucks
                if pos == data['stall'] and pos != "":
                    data['exists'] = True
                    data['used'].add(data['stall'])
                elif len(pos) == 1 and pos == data['stall'][0]:
                    data['exists'] = True
                    data['used'].add(data['stall'])
                elif len(data['stall']) == 1:
                    if len(pos) > 0:
                        if pos[0] == data['stall']:
                            data['exists'] = True    
                            data['used'].add(data['stall'])               
                            
        if new_stall in VALID_STALLS.get(container_type,[]):
            self.containers.foreach(validate, data)
            if not data['exists']:
                self.containers.set_value(iter, self.containers.STALL, new_stall)
                cnt_detail['load_position'] = new_stall
                if cnt_detail.get('id') is not None:
                    self.samples_database['containers'][str(cnt_detail['id'])]['load_position'] = new_stall
                else:
                    # for samples loaded from spreadsheet, use name instead of id as the database
                    # uses name-keys rather than id-keys
                    self.samples_database['containers'][str(cnt_detail['name'])]['load_position'] = new_stall
                self.load_database(self.samples_database)
                self.save_database()

            else:
                unused = set(VALID_STALLS.get(container_type,[])).difference(data['used'])
                
                header = 'Position already occupied.'
                subhead = 'Unoccupied positions for %s containers are:\n "%s"' % (
                            container_type, ', '.join(unused))
                dialogs.error(header, subhead)          
        else:            
            header = 'Invalid Load Position'
            subhead = 'Valid choices for %s containers are: \n"%s"' % (
                            container_type, ', '.join(VALID_STALLS.get(container_type,[])))
            dialogs.error(header, subhead)

    def on_crystal_activated(self, treeview, path, column):
        model = treeview.get_model()
        self.selected_crystal = path
        iter = model.get_iter(path)
        crystal_data = model.get_value(iter, model.DATA)        
        gobject.idle_add(self.emit, 'sample-selected', crystal_data)
       
    def save_database(self):
        save_config(SAMPLES_DB_CONFIG, self.samples_database)

    def load_database(self, samples_database):
        self.containers.clear()
        self.crystals.clear()
        if samples_database is None or samples_database == {}:
            return
        
        for cnt in samples_database['containers'].values():
            cnt['loaded'] = (cnt.get('load_position') not in ['', None])
            self.containers.add_container(cnt)
            for xtl_id in cnt.get('crystals', []):
                xtl = samples_database['crystals'].get(str(xtl_id))
                xtl['port'] = '%s%s' % (cnt.get('load_position',''), xtl['container_location'])
                if cnt['loaded']:
                    xtl['load_status'] = STATUS_LOADED
                else:
                    xtl['load_status'] = STATUS_NOT_LOADED
                
                xtl['container_name'] = cnt['name']
                k = str(xtl.get('experiment_id', ''))
                if k in samples_database['experiments']:
                    xtl['group'] = samples_database['experiments'][k]['name']
                else:
                    xtl['group'] = None
                self.crystals.add_crystal(xtl)
        self._notify_changes()

    def load_saved_database(self):
        #load samples database
        try:
            self.samples_database  = load_config(SAMPLES_DB_CONFIG)
            self.load_database(self.samples_database)
            self.selected_crystal = None
        except:
            pass
        self._notify_changes()
    
    def get_loaded_samples(self):
        if self.samples_database is None or self.samples_database == {}:
            return []
        loaded_samples = []
        
        iter = self.crystals.get_iter_first()
        while iter:
            _cr_loaded = self.crystals.get_value(iter, self.crystals.STATUS)
            if _cr_loaded >= STATUS_LOADED:
                _cr = self.crystals.get_value(iter, self.crystals.DATA)
                loaded_samples.append(_cr)
            iter = self.crystals.iter_next(iter)          
        return loaded_samples
                
    def clear_inventory(self):
        self.containers.clear()
        self.crystals.clear()
        self.samples_database = {}
        self.save_database()
        self.selected_crystal = None
        self._notify_changes()
                              
    def import_lims(self, lims_loader):
        self.selected_crystal = None
        self.samples_database = lims_loader.get('result')
            
        if lims_loader.get('error'):
            header = 'Error Importing from LIMS'
            subhead = 'Containers and Samples could not be imported.\n\nSee detailed errors below.'
            details = lims_loader['error']
            dialogs.error(header, subhead, details=details)
        elif len(self.samples_database.get('containers', {}).keys()) > 0:
            header = 'Import Successful'
            subhead = 'Loaded %d containers, with a total of %d samples.' % (
                                len(self.samples_database['containers']),
                                len(self.samples_database['crystals']))
            self.load_database(self.samples_database)
            self.save_database()
            dialogs.info(header, subhead)
        else:
            header = 'No Containers Available'
            subhead = 'Could not find any valid containers to import.'
            dialogs.warning(header, subhead)
            

    def on_import_file(self, obj):
        #FIXME
        _ALL = 'All Files'
        _XLS = 'Excel 97-2003'
        filters = [
            (_XLS, ['*.xls']),
            (_ALL, ['*']),
        ]
        import_selector = dialogs.FileSelector('Import Spreadsheet',
                                       gtk.FILE_CHOOSER_ACTION_OPEN,
                                       filters=filters)
        filename = import_selector.run()
        filter = import_selector.get_filter()
        if filename is None:
            return
        xls_loader = XLSLoader(filename)
        loaded_db = xls_loader.get_database()
        
        self.selected_crystal = None
        if self.samples_database is None or self.samples_database == {}:
            self.samples_database = loaded_db
        else:
            self.samples_database['containers'].update(loaded_db.get('containers'))
            self.samples_database['crystals'].update(loaded_db.get('crystals'))
            self.samples_database['experiments'].update(loaded_db.get('experiments'))
        
        if len(xls_loader.errors) > 0:
            header = 'Error Importing Spreadsheet'
            subhead = 'The file "%s" could not be opened.\n\nSee detailed errors below.' % filename
            details = '\n'.join(xls_loader.errors)
            dialogs.error(header, subhead, details=details)
        else:
            header = 'Import Successful'
            subhead = 'Loaded %d containers, with a total of %d samples.' % (
                                len(loaded_db['containers']),
                                len(loaded_db['crystals']))

            self.load_database(self.samples_database)
            self.save_database()            
            if len(xls_loader.warnings) > 0:
                header = 'Imported with warnings.'
                subhead += '\n\nSee detailed warnings below.'
                details = '\n'.join(xls_loader.warnings)
                dialogs.warning(header, subhead, details=details)
            else:
                dialogs.info(header, subhead)
        
def main():
    w = gtk.Window()
    w.set_default_size(640, 400)
    w.connect('destroy', lambda *w: gtk.main_quit())
    rd = DewarLoader()
    w.add(rd)
    w.show_all()
    from jsonrpc.proxy import ServiceProxy
    server = ServiceProxy('http://localhost:8000/json/')
    params = {'project_name':'testuser', 'beamline_name': '08ID-1'}
    reply = server.lims.get_onsite_samples('8CABA1A7-3FD9-494F-8D14-62A6876B2BC7', params)
    #reply = server.lims.get_active_runlist('8CABA1A7-3FD9-494F-8D14-62A6876B2BC7')
    import pprint
    pprint.pprint(reply, indent=2, depth=5)
    rd.import_lims(reply)
    #rd.load_saved_database()
    gtk.main()
          

if __name__ == '__main__':
    main()
