from mxdc.utils import gui, config
from mxdc.utils.config import load_config, save_config
from mxdc.utils.log import get_module_logger
from mxdc.utils.xlsimport import XLSLoader
from mxdc.widgets import dialogs
from mxdc.widgets.mountwidget import MountWidget
from gi.repository import GObject
from gi.repository import Gtk
import os

logger = get_module_logger(__name__)

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

class CrystalStore(Gtk.ListStore):
    (   
        NAME,
        PORT,
        GROUP,
        CONTAINER,
        STATUS,
        DATA,
    ) = range(6)
    
    def __init__(self):
        super(CrystalStore, self).__init__(
            str, str, str, int, object
        )
            
    
    def add_crystal(self, item):
        itr = self.append()
        self.set(itr, 
            self.NAME, item['name'],
            self.GROUP, item['group'],
            self.PORT, item['port'],
            self.CONTAINER, item['container_name'],
            self.STATUS, item['load_status'],
            self.DATA, item)
                    
class ContainerStore(Gtk.ListStore):
    (
        NAME,
        TYPE,
        STALL,
        LOADED,
        DATA,
        EDITABLE,
    ) = range(6)
    
    def __init__(self):
        super(ContainerStore, self).__init__(str, str, str, bool, object, bool)
            
        
    def add_container(self, item):
        itr = self.append()
        self.set(itr,
            self.NAME, item['name'],
            self.TYPE, item['type'],
            self.STALL, item['load_position'],
            self.LOADED, item['loaded'],
            self.DATA, item,
            self.EDITABLE, (item['type'] in ['Uni-Puck','Cassette']))
            
         
class DewarLoader(Gtk.Box):
    __gsignals__ = {
            'samples-changed': (GObject.SignalFlags.RUN_FIRST, None, []),
            'sample-selected': (GObject.SignalFlags.RUN_FIRST, None, [object,]),
    }
    
    def __init__(self):
        super(DewarLoader, self).__init__()
        self._xml = gui.GUIFile(
            os.path.join(os.path.dirname(__file__), 'data', 'sample_loader'),
            'sample_loader')

        self.pack_start(self.sample_loader, True, True, 0)
        self.selected_crystal = None

        #containers pane
        self.containers_view = self.__create_containers_view()
        self.inventory_sw.add(self.containers_view)

        #crystals pane
        self.crystals_view = self.__create_crystals_view()
        self.crystals_view.connect('row-activated',self.on_crystal_activated)

        self.expand_separator.set_expand(True)

        self.crystals_sw.add(self.crystals_view)
        self.mount_widget = MountWidget()
        self.mnt_hbox.add(self.mount_widget)
                
        #btn commands
        self.clear_btn.connect('clicked', lambda x: self.clear_inventory())

        #btn signals
        self.file_btn.connect('clicked', self.on_import_file)
        
    def __getattr__(self, key):
        try:
            return super(DewarLoader, self).__getattr__(key)
        except AttributeError:
            return self._xml.get_widget(key)
    
    def __create_containers_view(self):
        self.containers = ContainerStore()
        model = self.containers

        treeview = Gtk.TreeView(self.containers)
   
        treeview.set_rules_hint(True)

        # column for container name
        column = Gtk.TreeViewColumn('Container', Gtk.CellRendererText(),
                                    text=model.NAME)
        column.set_sort_column_id(model.NAME)
        treeview.append_column(column)

        # columns for container type
        column = Gtk.TreeViewColumn('Type', Gtk.CellRendererText(),
                                    text=model.TYPE)
        column.set_sort_column_id(model.TYPE)
        treeview.append_column(column)

        # column for Stall
        renderer = Gtk.CellRendererText()
        renderer.connect("edited", self.on_stall_edited)
        column = Gtk.TreeViewColumn('Position', renderer,
                                     text=model.STALL, editable=model.EDITABLE)
        column.set_sort_column_id(model.STALL)
        treeview.append_column(column)
        return treeview
               
    def __create_crystals_view(self):
        self.crystals = CrystalStore()
        model = self.crystals
        treeview = Gtk.TreeView(self.crystals)
        treeview.set_rules_hint(True)

        # column for name
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Name", renderer, text=model.NAME)
        column.set_cell_data_func(renderer, self._row_color)
        column.set_sort_column_id(model.NAME)
        treeview.append_column(column)

        # column for port
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Port", renderer, text=model.PORT)
        column.set_cell_data_func(renderer, self._row_color)
        column.set_sort_column_id(model.PORT)
        treeview.append_column(column)

        # column for group
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Group", renderer, text=model.GROUP)
        column.set_cell_data_func(renderer, self._row_color)
        column.set_sort_column_id(model.GROUP)
        treeview.append_column(column)                        

        # column for group
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Container", renderer, text=model.CONTAINER)
        column.set_sort_column_id(model.CONTAINER)
        column.set_cell_data_func(renderer, self._row_color)
        treeview.append_column(column)                        
        return treeview

    def _row_color(self, column, renderer, model, itr):
        value = model.get_value(itr, model.STATUS)
        color = STATUS_COLORS.get(value)
        renderer.set_property("foreground", color)

    def _notify_changes(self):
        GObject.idle_add(self.emit, 'samples-changed')
        #txt = "The list of crystals in the Screening tab has been updated."
        if self.selected_crystal is not None:
            itr = self.crystals.get_iter(self.selected_crystal)
            crystal_data = self.crystals.get_value(itr, self.crystals.DATA)        
            GObject.idle_add(self.emit, 'sample-selected', crystal_data)
            #txt = "Crystal information has been updated in the Screening & Collection tabs"
        #self.selected_lbl.set_markup(txt)
    
    def do_samples_changed(self):
        pass

    def do_sample_selected(self, data):
        pass

    def on_stall_edited(self, cell, path_string, new_text):
        itr = self.containers.get_iter_from_string(path_string)
        new_stall = new_text.strip().upper()
        old_stall = self.containers.get_value(itr, self.containers.STALL)
        cnt_detail = self.containers.get_value(itr, self.containers.DATA)
        
        if new_stall == old_stall.strip().upper():
            return 
        
        container_type = self.containers.get_value(itr, self.containers.TYPE)
        VALID_STALLS = {
            'Uni-Puck': ['RA', 'RB', 'RC', 'RD','MA', 'MB', 'MC', 'MD', 'LA', 'LB', 'LC', 'LD', ''],
            'Cassette': ['R','M', 'L',''],
        }
        
        data = {'stall': new_stall, 'exists': False, 'used': set()}
        def validate(model, path, itr, data):
            if itr is not None:
                pos = model.get_value(itr, model.STALL).strip().upper()
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
                self.containers.set_value(itr, self.containers.STALL, new_stall)
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
        itr = model.get_iter(path)
        crystal_data = model.get_value(itr, model.DATA)        
        GObject.idle_add(self.emit, 'sample-selected', crystal_data)
        #txt = "The selected crystal in the Collection tab has been updated."
        #self.selected_lbl.set_markup(txt)

       
    def save_database(self):
        save_config(SAMPLES_DB_CONFIG, self.samples_database)
    
    def find_crystal(self, port=None, barcode=None):
        found = None
        
        if port is None and barcode is None:
            pass
        elif self.samples_database:
            if port is None:
                for xtl in self.samples_database.get('crystals',{}).values():
                    if xtl['barcode'] == barcode:
                        found = xtl
                        break
            elif barcode is None:
                for xtl in self.samples_database.get('crystals',{}).values():
                    if xtl['port'] == port:
                        found = xtl
                        break
            else:
                for xtl in self.samples_database.get('crystals',{}).values():
                    if (xtl['port'], xtl['barcode']) == (port,barcode):
                        found = xtl
                        break
        return found
                      
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
        if not config.SESSION_INFO.get('new', False):
            try:
                self.samples_database  = load_config(SAMPLES_DB_CONFIG)
                self.load_database(self.samples_database)
                self.selected_crystal = None
            except:
                self.samples_database = {}
        else:
            self.samples_database = {}


    
    def get_loaded_samples(self):
        if self.samples_database is None or self.samples_database == {}:
            return []
        loaded_samples = []
        
        itr = self.crystals.get_iter_first()
        while itr:
            _cr_loaded = self.crystals.get_value(itr, self.crystals.STATUS)
            if _cr_loaded >= STATUS_LOADED:
                _cr = self.crystals.get_value(itr, self.crystals.DATA)
                loaded_samples.append(_cr)
            itr = self.crystals.iter_next(itr)          
        return loaded_samples
                
    def clear_inventory(self):
        self.containers.clear()
        self.crystals.clear()
        self.samples_database = {}
        self.save_database()
        self.selected_crystal = None
        self._notify_changes()

    def import_lims(self, data):
        self.selected_crystal = None
        if data and len(data.get('containers', {}).keys()) > 0:
            self.samples_database = data
            self.load_database(self.samples_database)
            self.save_database()
            msg = 'Successfully imported %d containers, with a total of %d samples from MxLIVE.' % (
                len(self.samples_database['containers']),
                len(self.samples_database['crystals']))
            logger.info(msg)
        else:
            dialogs.warning("No Samples in MxLIVE", "Could not find any valid containers to import from MxLIVE.")
            logger.warning('No valid containers to import from MxLIVE.')

    def on_import_file(self, obj):
        #FIXME
        _ALL = 'All Files'
        _XLS = 'Excel 97-2003'
        filters = [
            (_XLS, ['*.xls']),
            (_ALL, ['*']),
        ]
        filename = dialogs.select_open_file('Import Spreadsheet', filters=filters)[0]
        if filename is None:
            return
        
        try:
            xls_loader = XLSLoader(filename)
            loaded_db = xls_loader.get_database()
        except:
            header = 'Error Importing Spreadsheet'
            subhead = 'The file "%s" could not be opened.' % filename
            dialogs.error(header, subhead)           
        else:   
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
        