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

#Dewar Columns
(
    STALL_NAME_COLUMN,
    AVAILABLE_COLUMN,
    COMPATIBLE_COLUMN,
    CONTAINER_COLUMN,
    CONTAINER_DATA,
) = range(5)

#Container Columns
(
    ID_COLUMN,
    TYPE_COLUMN,
    COMMENTS_COLUMN,
) = range(3)
    

# Container test data
TEST_DATA = [
    {'name':'CLS0001', 'type':'UNI-PUCK', 'comments':'First container'},
    {'name':'CLS0002', 'type':'UNI-PUCK', 'comments':'Second container'},
    {'name':'CLS0034', 'type':'CASSETTE', 'comments':'A special cassette..'},
    {'name':'CLS0035', 'type':'CASSETTE', 'comments':'A special cassette..'},
    {'name':'CLS0036', 'type':'CASSETTE', 'comments':'A special cassette..'},
    {'name':'CLS0037', 'type':'UNI-PUCK', 'comments':'A special puck..'},
    {'name':'CLS0038', 'type':'UNI-PUCK', 'comments':'A special puck..'},
    {'name':'CLS0039', 'type':'CASSETTE', 'comments':'A special cassette..'},
    {'name':'CLS0012', 'type':'CASSETTE', 'comments':'A special cassette..'},
    {'name':'CLS0013', 'type':'UNI-PUCK', 'comments':'A special puck..'},
]

#drag targets,
(
    DEWAR_DRAG_LOC,
    INVENTORY_DRAG_LOC,    
) = range(2)

SAMPLES_DB_CONFIG = 'samples_db.json'
CONTAINERS_INV_CONFIG = 'containers_inv.json'
CONTAINERS_DEW_CONFIG = 'containers_dew.json'


class DewarStore(gtk.TreeStore):
    (
        STALL_NAME,
        AVAILABLE,
        COMPATIBLE,
        CONTAINER,
        DATA,
    ) = range(5)
    
    def __init__(self):
        gtk.TreeStore.__init__(self, 
            gobject.TYPE_STRING,
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_STRING,
            gobject.TYPE_PYOBJECT)
        self.__init_stalls()
        

    def __init_stalls(self):

        self.clear()        
        
        # add data to the tree store
        for name in ['L','M','R']:
            iter = self.append(None)
            self.set(iter,
                self.STALL_NAME, name,
                self.COMPATIBLE, True,
                self.AVAILABLE, True,
                self.CONTAINER, None,
                self.DATA, {},)
            path = self.get_path(iter)
            self.__init_children(path)

    def __init_children(self, stall_path):
        # add children
        iter = self.get_iter(stall_path)
        stall = self.get_value(iter, self.STALL_NAME)
        if iter is not None and len(stall_path) == 1:
            for slot in ['A','B','C','D']:
                child_iter = self.append(iter);
                self.set(child_iter,
                    self.STALL_NAME, '%s%s' % (stall, slot),
                    self.COMPATIBLE, True,
                    self.AVAILABLE, True,
                    self.CONTAINER, None,
                    self.DATA, {},)

    def __clear_children(self, stall_path):
        # remove children
        iter = self.get_iter(stall_path)
        if iter is not None and len(stall_path) == 1:
            it = self.iter_children(iter)
            while it is not None:
                old_it = it
                it = self.iter_next(it)
                self.remove(old_it)
              
    def load_saved_config(self):
        containers = load_config(CONTAINERS_DEW_CONFIG)
        if not isinstance(containers,dict):
            return
        for cnt in containers.values():
            data = {'name': cnt['name'],
                    'type': cnt['type'],
                    'comments': cnt['comments'],}
            self.load(tuple(cnt['path']), data)
            
    def stall_is_empty(self, path):
        iter = self.get_iter(path)
        if iter is None:
            return False
        else:
            return self.get_value(iter, self.AVAILABLE)


    def stall_is_compatible(self, path, container_type):
        if (len(path), container_type.upper()) in [(1,'CASSETTE'), (2, 'UNI-PUCK')]:
            return True
        else:
            return False
    
    def child_is_occupied(self, iter):
        occ = False
        parent_path = self.get_path(iter)
        if iter is not None and len(parent_path) == 1:
            it = self.iter_children(iter)
            while it is not None:
                if self.get_value(iter, self.AVAILABLE):
                    occ = True
                    break
                it = self.iter_next(it)
        return occ
        
    def load(self, path, data):
        iter = self.get_iter(path)
        if iter is not  None:            
            if self.stall_is_compatible(path, data['type']) and self.stall_is_empty(path):
                self.set_value(iter, self.CONTAINER, data['name'])
                self.set_value(iter, self.DATA, data)
                self.set_value(iter, self.AVAILABLE, False)
                parent = self.iter_parent(iter)
                if parent is not None:
                    self.set_value(parent, self.AVAILABLE, False)
                elif self.iter_has_child(iter):
                    self.__clear_children(path)
                return True
        return False
                    
    def unload(self, path):
        if not self.stall_is_empty(path):
            iter = self.get_iter(path)
            self.set_value(iter, self.CONTAINER, None)
            self.set_value(iter, self.DATA, {})
            self.set_value(iter, self.AVAILABLE, True)
            if len(path) == 2:
                parent = self.iter_parent(iter)            
                if not self.child_is_occupied(parent):
                    self.set_value(parent, self.AVAILABLE, True)
            elif len(path) == 1:
                if not self.child_is_occupied(iter):
                    self.__init_children(path)

    def get_containers(self):
        containers = {}
        def get_cnt(model, path, iter, containers):
            if iter is not None and model.get_value(iter, model.CONTAINER) is not None:
                cnt = {'stall': model.get_value(iter, model.STALL_NAME), 'path': model.get_path(iter)}                
                cnt.update(model.get_value(iter, model.DATA))
                containers[cnt['name']] = cnt
        self.foreach(get_cnt, containers)
        save_config(CONTAINERS_DEW_CONFIG, containers)
        return containers
        
class ContainerStore(gtk.ListStore):
    (
        ID,
        TYPE,
        COMMENTS,
    ) = range(3)
    
    def __init__(self):
        gtk.ListStore.__init__(self,
            gobject.TYPE_STRING, 
            gobject.TYPE_STRING, 
            gobject.TYPE_STRING)
            
    def load_containers(self, data):
        if data is None:
            return
        for item in data:
            self.add_container(item)
    
    def load_saved_config(self):
        self.load_containers(load_config(CONTAINERS_INV_CONFIG))
        
    def remove_container(self, path):
        iter = self.get_iter(path)
        if iter is not None:
            self.remove(iter)
            

    def add_container(self, item):
        iter = self.append()
        self.set(iter, 
            self.ID, item['name'],
            self.TYPE, item['type'],
            self.COMMENTS, item['comments'])
    
    def save_containers(self):
        containers = []
        def get_cnt(model, path, iter, containers):
                cnt = {'name': model.get_value(iter, model.ID), 
                       'type': model.get_value(iter, model.TYPE),
                       'comments': model.get_value(iter, model.COMMENTS)}            
                containers.append(cnt)
        self.foreach(get_cnt, containers)
        save_config(CONTAINERS_INV_CONFIG, containers)
        
         
class DewarLoader(gtk.Frame):
    __gsignals__ = {
            'samples-changed': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, []),
    }
    
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(
            os.path.join(os.path.dirname(__file__), 'data', 'dewar_loader.glade'),
            'dewar_loader')

        self.add(self.dewar_loader)

        #inventory pane
        self.inventory_view = self.__create_inventory_view()
        self.inventory_sw.add(self.inventory_view)

        #dewar pane
        self.dewar_view = self.__create_dewar_view()
        self.dewar_sw.add(self.dewar_view)
        
        #inventory Signals
        self.inventory_view.connect('drag-data-received', self.on_unload)
        self.inventory_view.connect_after('drag-begin', self.on_inventory_drag_begin)
        self.inventory_view.connect('drag-data-get', self.on_inventory_data_get)
        #self.inventory_view.connect('drag-motion', self.on_inventory_drag_motion)

        #dewar Signals
        self.dewar_view.connect('drag-data-received', self.on_load)
        self.dewar_view.connect_after('drag-begin', self.on_dewar_drag_begin)
        self.dewar_view.connect('drag-data-get', self.on_dewar_data_get)
        self.dewar_view.connect('drag-motion', self.on_dewar_drag_motion)
        
        #btn commands
        self.clear_btn.connect('clicked', self.on_clear_inventory)
        self.unload_btn.connect('clicked', self.on_unload_all)

        #housekeeping
        self._drag_container_type = None
        self._puck_icon = gtk.gdk.pixbuf_new_from_file(
            os.path.join(os.path.dirname(__file__), 'data', 'icons', 'drag_puck_template.png'))
        self._cassette_icon = gtk.gdk.pixbuf_new_from_file(
            os.path.join(os.path.dirname(__file__), 'data', 'icons', 'drag_cassette_template.png'))

        #btn signals
        self.lims_btn.connect('clicked', self.on_import_lims)
        self.file_btn.connect('clicked', self.on_import_file)
        self.samples_database = None
        
        # load previously saved configuration
        #self.connect('realize', lambda x: self.load_saved_config())
        self.load_saved_config()
        
    def __getattr__(self, key):
        try:
            return gtk.Frame.__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
    
    def _notify_changes(self):
        gobject.idle_add(self.emit, 'samples-changed')
    
    def do_samples_changed(self, obj=None):
        pass
        
        
    def load_saved_config(self):
        #load samples database
        self.samples_database  = load_config(SAMPLES_DB_CONFIG)

        #load inventory and dewar
        self.inventory.load_saved_config()
        self.dewar.load_saved_config()
        self._notify_changes()
    
    def generate_icon_info(self, data):
        if data['type'].upper() == 'UNI-PUCK':
            pixmap, mask = self._puck_icon.render_pixmap_and_mask()
        else:
            pixmap, mask = self._cassette_icon.render_pixmap_and_mask()
        cr = pixmap.cairo_create()
        cr.set_font_size(13)

        txts = [
            #'ID: %s' % ('xxx'),
            '%s' % (data['name']),
            data['type'].lower()
            ]
        sx, sy = 60, 24
        for txt in txts:
            x_b, y_b, w, h = cr.text_extents(txt)[:4]
            cr.move_to(sx, sy)
            cr.show_text(txt)
            sy += 15
        pw, ph = pixmap.get_size()
        pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8,  pw, ph)
        pixbuf.get_from_drawable(pixmap, pixmap.get_colormap(), 0, 0, 0, 0, pw, ph)
        return pixbuf
         

    def add_to_inventory(self, data):
        self.inventory.load_containers(data)
        self.inventory.save_containers()

    def get_loaded_samples(self):
        samples = []
        loaded_containers = self.dewar.get_containers()
        if self.samples_database is not None:
            for cryst in self.samples_database['crystals'].values():
                if cryst['container'] in loaded_containers.keys():
                    _cnt = loaded_containers[cryst['container']]
                    _cr = {}
                    _cr.update(cryst)
                    _cr['port'] = '%s%s' % (_cnt['stall'], _cr['port'])
                    samples.append(_cr)
        return samples
        
    def __create_inventory_view(self):
        self.inventory = ContainerStore()
        model = self.inventory

        treeview = gtk.TreeView(self.inventory)
   
        treeview.set_rules_hint(True)
        treeview.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK | gtk.gdk.BUTTON3_MASK,
            [('container/inventory',0, INVENTORY_DRAG_LOC)], 
            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_MOVE)
        treeview.enable_model_drag_dest([('robot/dewar',0,DEWAR_DRAG_LOC)],
            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_MOVE)

        # column for container id
        column = gtk.TreeViewColumn('Container', gtk.CellRendererText(),
                                    text=model.ID)
        column.set_sort_column_id(model.ID)
        treeview.append_column(column)

        # columns for container type
        column = gtk.TreeViewColumn('Type', gtk.CellRendererText(),
                                    text=model.TYPE)
        column.set_sort_column_id(model.TYPE)
        treeview.append_column(column)

        # column for comments
        column = gtk.TreeViewColumn('Comments', gtk.CellRendererText(),
                                     text=model.COMMENTS)
        column.set_sort_column_id(model.COMMENTS)
        treeview.append_column(column)
        return treeview
        
        
    def __create_dewar_view(self):
        self.dewar = DewarStore()
        model = self.dewar
        treeview = gtk.TreeView(self.dewar)
        treeview.set_rules_hint(True)
        treeview.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK | gtk.gdk.BUTTON3_MASK,
            [('robot/dewar',0,DEWAR_DRAG_LOC)], 
            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_MOVE)
        treeview.enable_model_drag_dest(
            [('container/inventory',0,INVENTORY_DRAG_LOC)], 
            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_MOVE)
                    
        # column for slot names
        renderer = gtk.CellRendererText()
        renderer.set_property("xalign", 0.0)

        column = gtk.TreeViewColumn("Dewar Stall", renderer, text=model.STALL_NAME)
        column.set_clickable(True)
        treeview.append_column(column)

        # container column */
        renderer = gtk.CellRendererText()
        renderer.set_property("xalign", 0.0)
        renderer.set_data("column", model.CONTAINER)
        column = gtk.TreeViewColumn("Loaded Container", renderer, text=model.CONTAINER)
        treeview.append_column(column)
        treeview.connect('realize', lambda tv: tv.expand_all())
                        
        return treeview

    def on_load(self, treeview, ctx, x, y, selection, info, timestamp):
        drop_info = treeview.get_dest_row_at_pos(x, y)
        if drop_info:
            model = treeview.get_model()
            path, position = drop_info
            data = json.loads(selection.data)
            if self.dewar.load(path, data):   
                ctx.finish(True, True)
                self.inventory.save_containers()
                self._notify_changes()
            else:
                ctx.finish(False, False)
                
        
    def on_unload(self, treeview, ctx, x, y, selection, info, timestamp):
        data = json.loads(selection.data)
        if data:
            self.inventory.add_container(data)
            if ctx.get_source_widget() is self.dewar_view:
                treeselection = self.dewar_view.get_selection()
                model, iter = treeselection.get_selected()
                path = model.get_path(iter)
                if self.dewar.unload(path):
                    ctx.finish(True, False)
                else:
                    ctx.finish(False, False)
                self.dewar_view.expand_all()
                self.inventory.save_containers()
                self._notify_changes()
            

    def on_unload_all(self, obj):
        containers = []
        def get_cnt(model, path, iter, containers):
            if iter is not None and model.get_value(iter, model.CONTAINER) is not None:
                cnt =  model.get_value(iter, model.DATA)
                path = model.get_path(iter)
                model.unload(path)
                containers.append(cnt)
        self.dewar.foreach(get_cnt, containers)
        self.inventory.load_containers(containers)
        self.inventory.save_containers()
        self._notify_changes()

    def on_clear_inventory(self, obj):
        self.on_unload_all(None)
        self.inventory.clear()
        self.samples_database = None
        self.inventory.save_containers()
    

    def on_inventory_data_get(self, treeview, ctx, selection, info, timestamp):
        treeselection = treeview.get_selection()
        model, iter = treeselection.get_selected()
        path = model.get_path(iter)
        data = {
            'name': model.get_value(iter, model.ID),
            'type': model.get_value(iter, model.TYPE),
            'comments': model.get_value(iter, model.COMMENTS),}
        selection.set(selection.target, 8, json.dumps(data))

    def on_dewar_data_get(self, treeview, ctx, selection, info, timestamp):
        treeselection = treeview.get_selection()
        model, iter = treeselection.get_selected()
        path = model.get_path(iter)
        data = model.get_value(iter, model.DATA)
        selection.set(selection.target, 8, json.dumps(data))

    def on_dewar_drag_motion(self, treeview, ctx, x, y, timestamp):
        if ctx.get_source_widget() == self.inventory_view:
            drop_info = treeview.get_dest_row_at_pos(x, y)
            if drop_info is None:
                # do not permitted"
                return
            path, position = drop_info
            model, iter = self.inventory_view.get_selection().get_selected()
            cnt_type = model.get_value(iter, model.TYPE)
            if self.dewar.stall_is_compatible(path, cnt_type) and self.dewar.stall_is_empty(path):
                # do permitted
                pass
                
            else:
                # do not permitted
                pass
                
            
    def on_inventory_drag_begin(self, treeview, ctx):
        if treeview is self.inventory_view:
            treeselection = treeview.get_selection()
            model, iter = treeselection.get_selected()
            data = {
                'name': model.get_value(iter, model.ID),
                'type': model.get_value(iter, model.TYPE),
                'comments': model.get_value(iter, model.COMMENTS),}

            descr_icon = self.generate_icon_info(data)
            ctx.set_icon_pixbuf(descr_icon, -10, -10)
            self._dctx = ctx
            
            
    def on_dewar_drag_begin(self, treeview, ctx):
        if treeview is self.dewar_view:
            treeselection = treeview.get_selection()
            model, iter = treeselection.get_selected()
            path = model.get_path(iter)
            cnt = model.get_value(iter, model.CONTAINER)
            if cnt is not None:
                ctx.set_icon_stock('gtk-undo', -10, -10)
            
    def on_import_lims(self, obj):
        #FIXME
        current_user = os.getlogin()
        cred_user = 'testuser'
        cred_pass = '08id-1'
        lims_url = 'https://cmcf.lightsource.ca/json/'
        
        try:
            from jsonrpc.proxy import ServiceProxy
            server = ServiceProxy(lims_url)
            lims_loader =   server.lims.get_user_samples(cred_user, cred_pass, {'user': current_user})  
        except:
            header = 'Error Connecting to LIMS'
            subhead = 'Containers and Samples could not be imported.'
            dialogs.error(header, subhead)
            return
        
        self.samples_database = lims_loader['result']
            
        if lims_loader['error']:
            header = 'Error Importing from LIMS'
            subhead = 'Containers and Samples could not be imported.\n\nSee detailed errors below.'
            details = lims_loader['error']
            dialogs.error(header, subhead, details=details)
        elif len(self.samples_database['containers'].keys()) > 0:
            header = 'Import Successful'
            subhead = 'Loaded %d containers, with a total of %d samples.' % (
                                len(self.samples_database['containers']),
                                len(self.samples_database['crystals']))
            self.inventory.load_containers(self.samples_database['containers'].values())
            dialogs.info(header, subhead)
            self.inventory.save_containers()
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
        if self.samples_database is None:
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
            if len(xls_loader.warnings) > 0:
                header = 'Imported with warnings.'
                subhead += '\n\nSee detailed warnings below.'
                details = '\n'.join(xls_loader.warnings)
                self.inventory.load_containers(loaded_db['containers'].values())
                dialogs.warning(header, subhead, details=details)
            else:
                self.inventory.load_containers(loaded_db['containers'].values())
                dialogs.info(header, subhead)
            self.inventory.save_containers()
        
        # make sure sample list is stored to file for restore
        save_config(SAMPLES_DB_CONFIG, self.samples_database)
        
def main():
    w = gtk.Window()
    w.set_default_size(640, 400)
    w.connect('destroy', lambda *w: gtk.main_quit())
    rd = DewarLoader()
    rd.add_to_inventory(TEST_DATA)
    w.add(rd)
    w.show_all()
    gtk.main()
          

if __name__ == '__main__':
    main()
