import gtk, gobject
import sys, os, time


from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from bcm.engine.diffraction import DataCollector
from bcm.utils.decorators import async
from bcm.utils.misc import get_project_name

try:
    import json
except:
    import simplejson as json
    
from bcm.utils import misc, runlists
from bcm.utils.log import get_module_logger
from bcm.engine import auto

from mxdc.widgets.misc import ActiveLabel, ActiveProgressBar
from mxdc.widgets.runmanager import RunManager
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.widgets.dialogs import warning, error
from mxdc.widgets.rundiagnostics import DiagnosticsWidget
from mxdc.utils import config

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

(
    COLLECT_COLUMN_SAVED,
    COLLECT_COLUMN_ANGLE,
    COLLECT_COLUMN_RUN,
    COLLECT_COLUMN_NAME
) = range(4)

(
    COLLECT_STATE_IDLE,
    COLLECT_STATE_RUNNING,
    COLLECT_STATE_PAUSED
) = range(3)

(
    MOUNT_ACTION_NONE,
    MOUNT_ACTION_DISMOUNT,
    MOUNT_ACTION_MOUNT,
) = range(3)

RUN_CONFIG_FILE = 'run_config.json'

class CollectManager(gtk.Frame):
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(os.path.join(os.path.dirname(__file__), 'data/collect_widget.glade'), 
                                  'collect_widget')            
        self.run_data = []
        self.run_list = []
        
        self.collect_state = COLLECT_STATE_IDLE
        self.frame_pos = None
        self._first_launch = False
        self.skip_frames = False
        self._create_widgets()
        
        self.selected_sample = {}
        self.update_sample()
        
        
    def __getattr__(self, key):
        try:
            return super(CollectManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def _create_widgets(self):
        self.image_viewer = ImageViewer(size=640)
        self.run_manager = RunManager()
        self.collector = DataCollector()
        self.beamline = globalRegistry.lookup([], IBeamline)      
        
        self.collect_state = COLLECT_STATE_IDLE
        self.sel_mount_action = MOUNT_ACTION_NONE 
        self.sel_mounting  = False # will be sent to true when mount command has been sent and false when it is done
        self.frame_pos = None
        
        # Run List
        self.listmodel = gtk.ListStore(
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_FLOAT,
            gobject.TYPE_UINT,
            gobject.TYPE_STRING           
        )
        self.listview = gtk.TreeView(self.listmodel)
        self.listview.set_rules_hint(True)
        self._add_columns()     
        sw = self._xml.get_widget('run_list_window')
        sw.add(self.listview)

        self.collect_btn.set_label('mxdc-collect')
        self.stop_btn.set_label('mxdc-stop')
        self.stop_btn.set_sensitive(False)
        
        # Run progress
        self.progress_bar = ActiveProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.idle_text('0%')
        self.control_box.pack_start(self.progress_bar, expand=False, fill=True)
                
        # Current Position
        pos_table = self._xml.get_widget('position_table')
        if self.beamline is not None:
            pos_table.attach(ActiveLabel(self.beamline.goniometer.omega, format='%7.2f'), 1,2,0,1)
            pos_table.attach(ActiveLabel(self.beamline.diffractometer.two_theta, format='%7.2f'), 1,2,1,2)
            pos_table.attach(ActiveLabel(self.beamline.diffractometer.distance, format='%7.2f'), 1,2,2,3)
            pos_table.attach(ActiveLabel(self.beamline.monochromator.energy, format='%7.4f'), 1,2,3,4)
        
        # Image Viewer
        self.frame_book.add(self.image_viewer)
        self.setup_box.pack_end(self.run_manager, expand = True, fill = True)
        
        #automounter signals
        self.beamline.automounter.connect('mounted', lambda x,y: self.update_sample())

        
        #diagnostics
        self.diagnostics = DiagnosticsWidget()
        self.tool_book.append_page(self.diagnostics, tab_label=gtk.Label('Run Diagnostics'))
        self.tool_book.connect('realize', lambda x: self.tool_book.set_current_page(0))
        #self.diagnostics.set_sensitive(False)
        
        self.listview.connect('row-activated',self.on_row_activated)
        self.collect_btn.connect('clicked',self.on_activate)
        self.stop_btn.connect('clicked', self.on_stop_btn_clicked)
        self.mnt_action_btn.connect('clicked', self.on_mount_action)
        self.run_manager.connect('saved', self.save_runs)
        #self.run_manager.connect('del-run', self.remove_run)

        for w in [self.collect_btn, self.stop_btn]:
            w.set_property('can-focus', False)
        
        self.collector.connect('done', self.on_complete)
        self.collector.connect('error', self.on_error)
        self.collector.connect('paused',self.on_pause)
        self.collector.connect('new-image', self.on_new_image)
        self.collector.connect('stopped', self.on_complete)
        self.collector.connect('progress', self.on_progress)

        if self.beamline is not None:
            self.beamline.storage_ring.connect('beam', self._on_beam_change)
        
        self._load_config()
        self.add(self.collect_widget)
        self.run_manager.set_current_page(0)
        self.show_all()
        
    def _on_beam_change(self, obj, beam_available):
        if not beam_available and (not self.collector.stopped) and (not self.collector.paused):
            self.collector.pause()
            header = "Beam not Available. Data Collection has been paused!"
            sub_header = "Please resume data collection when beam is available again."
            warning(header, sub_header)
        return True


    def _load_config(self):        
        data = config.load_config(RUN_CONFIG_FILE)
        if data is None:
            return
        for section in data.keys():
            run = int(section)
            data[run] = data[section]
            self.add_run(data[run])

    def _save_config(self):
        save_data = {}
        for run in self.run_manager.runs:
            data = run.get_parameters()
            save_data[ data['number'] ] = data
        config.save_config(RUN_CONFIG_FILE, save_data)
        
    def update_sample(self, data=None):
        
        if data is not None:
            self.selected_sample.update(data)
            self.run_manager.update_sample(self.selected_sample)
            
        self.mnt_action_btn.set_sensitive(False)
        self.mnt_action_btn.set_label('Mount')
        self.sel_mount_action = MOUNT_ACTION_NONE
        
        if self.selected_sample.get('name') is not None:
            if self.selected_sample.get('port') is not None:
                txt = "%s(%s)" % (self.selected_sample['name'], 
                                  self.selected_sample['port'])
                self.crystal_lbl.set_text(txt)
                if self.beamline.automounter.is_mounted(self.selected_sample['port']):
                    self.mnt_action_btn.set_label('Dismount')
                    self.sel_mount_action = MOUNT_ACTION_DISMOUNT
                elif self.beamline.automounter.is_mountable(self.selected_sample['port']):
                    self.mnt_action_btn.set_label('Mount')
                    self.sel_mount_action = MOUNT_ACTION_MOUNT
                if self.sel_mounting or self.beamline.automounter.is_busy() or not self.beamline.automounter.is_active():
                    self.sel_mount_action = MOUNT_ACTION_NONE
                    self.mnt_action_btn.set_sensitive(False)
                else:
                    self.mnt_action_btn.set_sensitive(True)
                    
    @async
    def execute_mount_action(self):
        
        if self.sel_mount_action == MOUNT_ACTION_MOUNT:
            try:
                gobject.idle_add(self.progress_bar.busy_text, 
                                 'Mounting %s ...' % self.selected_sample['name'])
                self.sel_mounting = True
                gobject.idle_add(self.update_sample)
                auto.auto_mount_manual(self.beamline, self.selected_sample['port'])
                done_text = "Mount succeeded"
            except:
                _logger.error('Sample mounting failed')
                done_text = "Mount failed"
        elif self.sel_mount_action == MOUNT_ACTION_DISMOUNT:
            try:
                gobject.idle_add(self.progress_bar.busy_text, 
                                 'Dismounting %s ...' % self.selected_sample['name'])
                self.sel_mounting = True
                gobject.idle_add(self.update_sample)
                auto.auto_dismount_manual(self.beamline, self.selected_sample['port'])
                done_text = "Dismount succeeded"
            except:
                _logger.error('Sample dismounting failed')
                done_text = "Dismount failed"
        
        if self.progress_bar.get_busy():
            gobject.idle_add(self.progress_bar.idle_text,  done_text)
        self.sel_mounting = False
        gobject.idle_add(self.update_sample)
    
    
    def on_mount_action(self, obj):
        self.execute_mount_action()

    
    def config_user(self):
        username = os.environ['USER']
        userid = os.getuid()
        groupid = os.getgid()
        res = self.beamline.image_server.set_user( username, userid, groupid )
        try:
            assert(res==True)
            return True
        except:
            msg_title = 'Image Syncronization Server Error'
            msg_sub = 'MXDC could not configure the server for the current user. '
            msg_sub += 'Data collection can not proceed reliably without the server up and running.'
            warning(msg_title, msg_sub)
            return False


    def _add_item(self, item):
        iter = self.listmodel.append()        
        self.listmodel.set(iter, 
            COLLECT_COLUMN_SAVED, item['saved'], 
            COLLECT_COLUMN_ANGLE, item['start_angle'],
            COLLECT_COLUMN_RUN, item['number'],
            COLLECT_COLUMN_NAME, item['frame_name']
        )
            
    def _float_format(self, column, renderer, model, iter, format):
        value = model.get_value(iter, COLLECT_COLUMN_ANGLE)
        saved = model.get_value(iter, COLLECT_COLUMN_SAVED)
        renderer.set_property('text', format % value)
        if saved:
            renderer.set_property("foreground", '#cc0000')
        else:
            renderer.set_property("foreground", None)
        return

    def _saved_color(self,column, renderer, model, iter):
        value = model.get_value(iter, COLLECT_COLUMN_SAVED)
        if value:
            renderer.set_property("foreground", '#cc0000')
        else:
            renderer.set_property("foreground", None)
        return      
                
    def _add_columns(self):
        model = self.listview.get_model()
                                        
        # Saved Column
        renderer = gtk.CellRendererToggle()
        column = gtk.TreeViewColumn('Saved', renderer, active=COLLECT_COLUMN_SAVED)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(50)
        self.listview.append_column(column)
        
        # Name Column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Name', renderer, text=COLLECT_COLUMN_NAME)
        column.set_cell_data_func(renderer, self._saved_color)
        self.listview.append_column(column)

        # Angle Column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Angle', renderer, text=COLLECT_COLUMN_ANGLE)
        column.set_cell_data_func(renderer, self._float_format, '%5.2f')
        self.listview.append_column(column)
        
        
    def save_runs(self, obj=None):
        self.clear_runs()
        run_num = self.run_manager.get_current_page()
        dir_error = False

        try:
            for run in self.run_manager.runs:
                data = run.get_parameters()
                res = self.beamline.image_server.setup_folder(data['directory'])
                if res:
                    if run_num == 0 and data['number'] == 0:
                        data['energy'] = [self.beamline.monochromator.energy.get_position()]
                        data['energy_label'] = ['E0']
                        self.run_data = [data]
                        break
                    elif (run_num == data['number'] or run.is_enabled()) and data['number'] != 0:
                        self.run_data.append(data)
                else:
                    run.disable_run()
                    dir_error = True
        except KeyboardInterrupt:
            msg_title = 'Error Saving Run information'
            msg_sub = 'Either you have entered invalid parameters or a connection to the Image '
            msg_sub += 'Synchronisation Server could not be established. Data Collection '
            msg_sub += 'can not proceed reliably until the problem is resolved.'
            warning(msg_title, msg_sub)
        
        if dir_error:            
            msg_title = 'Invalid Directories'
            msg_sub = 'One or more runs have been disbled because directories '
            msg_sub += 'Could not be setup. Please make sure no  directories with spaces '
            msg_sub += 'or special characters are used, and try again.'
            warning(msg_title, msg_sub)
        
        self._save_config()
        self.create_runlist()
        
    def add_run(self, data):
        self.run_manager.add_new_run(data)
               
    def clear_runs(self):
        del self.run_data[:]
        self.run_data = []
            
    def create_runlist(self):

        self.run_list = runlists.generate_run_list(self.run_data)

        self.frame_pos = 0
        self.gen_sequence()
                                                                        
    def gen_sequence(self):
        self.listmodel.clear()
        for item in self.run_list:
            self._add_item(item)
    
    def check_runlist(self):
        existlist = []
        details = ""
        for i, frame in enumerate(self.run_list):
            path_to_frame = "%s/%s" % (frame['directory'],frame['file_name'])
            if os.path.exists(path_to_frame):
                existlist.append( i )
                details += frame['file_name'] + "\n"
        if len(existlist) > 0:
            header = 'Frames from this sequence already exist! Do you want to skip or replace them?'
            sub_header = '<b>Replacing them will overwrite their contents permanently!</b> Skipped frames will not be re-acquired.'
            buttons = ( ('gtk-cancel',gtk.RESPONSE_CANCEL), ('Skip', gtk.RESPONSE_YES), ('Replace', gtk.RESPONSE_NO))
            response = warning(header, sub_header, details, buttons=buttons)
            if response == gtk.RESPONSE_YES:
                self.skip_existing = True
                for index in existlist:
                    self.set_row_state(index, saved=True)
                return True
            elif response == gtk.RESPONSE_NO:
                self.skip_existing = False
                for index in existlist:
                    old_name = "%s/%s" % (self.run_list[index]['directory'], self.run_list[index]['file_name']) 
                    os.remove(old_name)
                return True
            else:
                return False
        return True
            
    def set_row_state(self, pos, saved=True):
        path = (pos,)
        iter = self.listmodel.get_iter(path)
        self.listmodel.set(iter, COLLECT_COLUMN_SAVED, saved)
        self.listview.scroll_to_cell(path,use_align=True,row_align=0.9)
        
    def on_row_activated(self, treeview, path, column):
        if self.collect_state != COLLECT_STATE_PAUSED:
            return True
        model = treeview.get_model()
        iter = model.get_iter_first()
        pos = model.get_iter(path)
        self.frame_pos = model.get_path(pos)[0]             
        while iter:
            i = model.get_path(iter)[0]
            if i < self.frame_pos:
                model.set(iter, COLLECT_COLUMN_SAVED, True)
                self.run_list[i]['saved'] = True
            else:
                model.set(iter, COLLECT_COLUMN_SAVED, False)
                self.run_list[i]['saved'] = False
            iter = model.iter_next(iter)
            
        if self.collect_state == COLLECT_STATE_PAUSED:
            self.collector.set_position( self.frame_pos )
        return True
    
    def on_row_toggled(self, treeview, path, column):
        if self.collect_state != COLLECT_STATE_PAUSED:
            return True
        model = treeview.get_model()
        iter = model.get_iter_first()
        pos = model.get_iter(path)
        i = model.get_path(pos)[0]             
        if self.run_list[i]['saved'] :
            model.set(iter, COLLECT_COLUMN_SAVED, False)
            self.run_list[i]['saved'] = False
        else:
            model.set(iter, COLLECT_COLUMN_SAVED, True)
            self.run_list[i]['saved'] = True
        return True

    def on_pause(self,widget, paused, msg=''):
        if paused:
            self.collect_btn.set_label('mxdc-resume')
            self.collect_state = COLLECT_STATE_PAUSED
            self.progress_bar.idle_text("Paused")
            self.collect_btn.set_sensitive(True)
        else:
            self.collect_btn.set_label('mxdc-pause')   
            self.collect_state = COLLECT_STATE_RUNNING
            
    def on_error(self, widget, msg):
        msg_title = msg
        msg_sub = 'Connection to detector was lost. '
        msg_sub += 'Data collection can not proceed reliably.'
        error(msg_title, msg_sub)


    def on_activate(self, widget):
        if not self.run_list:
            msg1 = 'Run list is empty!'
            msg2 = 'Please define and save a run before collecting.'
            warning(msg1, msg2)
            return
            
        if self.collect_state == COLLECT_STATE_IDLE:
            self.start_collection()
            self.progress_bar.set_fraction(0)
        elif self.collect_state == COLLECT_STATE_RUNNING:
            self.collector.pause()
            self.collect_btn.set_sensitive(False)
            self.progress_bar.busy_text("Pausing after this frame...")
        elif self.collect_state == COLLECT_STATE_PAUSED:
            self.collector.resume()
    

    def on_stop_btn_clicked(self,widget):
        self.collector.stop()
        self.stop_btn.set_sensitive(False)
        self.progress_bar.busy_text("Stopping after this frame...")
        
    
    def on_complete(self, obj=None):
        self.collect_state = COLLECT_STATE_IDLE
        self.collect_btn.set_label('mxdc-collect')
        self.stop_btn.set_sensitive(False)
        self.run_manager.set_sensitive(True)
        self.image_viewer.set_collect_mode(False)
        self.progress_bar.idle_text("Stopped")
        
        try:
            for result in obj.results:
                json_info = {
                    'id': result.get('id'),
                    'crystal_id': result.get('crystal_id'),
                    'experiment_id': result.get('experiment_id'),
                    'name': result['name'],
                    'resolution': round(result['resolution'], 5),
                    'start_angle': result['start_angle'],
                    'delta_angle': result['delta_angle'],
                    'first_frame': result['first_frame'],
                    'frame_sets': result['frame_sets'],
                    'exposure_time': result['exposure_time'],
                    'two_theta': result['two_theta'],
                    'wavelength': round(result['wavelength'], 5),
                    'detector': result['detector'],
                    'beamline_name': result['beamline_name'],
                    'detector_size': result['detector_size'],
                    'pixel_size': result['pixel_size'],
                    'beam_x': result['beam_x'],
                    'beam_y': result['beam_y'],
                    'url': result['directory'],
                    'staff_comments': result.get('comments'),
                    #'project_name': "testuser",                  
                    'project_name': get_project_name(),                  
                    }
                if result['num_frames'] < 10:
                    json_info['kind'] = 0 # screening
                else:
                    json_info['kind'] = 1 # collection
                
                if result['num_frames'] < 4:
                    return
                reply = self.beamline.lims_server.lims.add_data(
                            self.beamline.config.get('lims_api_key',''), json_info)
                if reply.get('result') is not None:
                    if reply['result'].get('data_id') is not None:
                        # save data id to file so next time we can find it
                        result['id'] = reply['result']['data_id']
                        _logger.info('Dataset uploaded to LIMS.')
                elif reply.get('error') is not None:
                    _logger.error('Dataset could not be uploaded to LIMS.')
                filename = os.path.join(result['directory'], '%s.SUMMARY' % result['name'])
                fh = open(filename,'w')
                json.dump(result, fh, indent=4)
                fh.close()
        except:
            print sys.exc_info()
            _logger.warn('Could not upload dataset to LIMS.')

    def on_new_image(self, widget, index, filename):
        self.frame_pos = index
        self.image_viewer.add_frame(filename)
        self.set_row_state(index, saved=True)
      

    def on_progress1(self, obj, fraction, position):
        if fraction > 0.0:
            total_frames = position/fraction
            if self.last_time is None:
                self.last_time = time.time()
                time_unit = 0.0
            else:
                time_unit = time.time() - self.last_time
                self.last_time = time.time()
        
            eta_time = time_unit * (total_frames - position)
            if time_unit > 0.0:
                text = "ETA %s @ %0.1fs/frame" % (time.strftime('%H:%M:%S',time.gmtime(eta_time)), time_unit)
                self.progress_bar.set_complete(fraction, text)

    def on_progress(self, obj, fraction, position):
        if position == 1:
            self.start_time = time.time()
        elapsed_time = time.time() - self.start_time
        if fraction > 0:
            time_unit = elapsed_time / fraction
        else:
            time_unit = 0.0
        
        eta_time = time_unit * (1 - fraction)
        if position > 0:
            frame_time = elapsed_time / position
            text = "ETA %s @ %0.1fs/frame" % (time.strftime('%H:%M:%S',time.gmtime(eta_time)), frame_time)
        else:
            text = "Total: %s sec" % (time.strftime('%H:%M:%S',time.gmtime(elapsed_time)))
        self.progress_bar.set_complete(fraction, text)
                
    def on_energy_changed(self, obj, val):
        run_zero = self.run_manager.runs[0]
        data = run_zero.get_parameters()
        data['energy'] = [ val ]
        run_zero.set_parameters(data)

    def update_values(self,dict):        
        for key in dict.keys():
            self.labels[key].set_text(dict[key])

    def start_collection(self):
        self.start_time = time.time()
        self.create_runlist()
        if self.config_user():
            if self.check_runlist():
                self.progress_bar.busy_text("Starting data collection...")
                self.collector.configure(self.run_data, skip_existing=self.skip_existing)
                self.collector.start()
                self.collect_state = COLLECT_STATE_RUNNING
                self.collect_btn.set_label('mxdc-pause')
                self.stop_btn.set_sensitive(True)
                self.run_manager.set_sensitive(False)
                self.image_viewer.set_collect_mode(True)
        return            

    def stop(self):
        if self.collector is not None:
            self.collector.stop()
    
                                                                                                                                                                              
