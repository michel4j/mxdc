import gtk
import gobject
import pango
import sys, os, time


from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from bcm.engine.diffraction import DataCollector
from bcm.utils.decorators import async
from bcm.utils import lims_tools


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
    COLLECT_COLUMN_STATUS,
    COLLECT_COLUMN_ANGLE,
    COLLECT_COLUMN_RUN,
    COLLECT_COLUMN_NAME
) = range(4)

(
    COLLECT_STATE_IDLE,
    COLLECT_STATE_RUNNING,
    COLLECT_STATE_PAUSED
) = range(3)


FRAME_STATE_PENDING = DataCollector.STATE_PENDING
FRAME_STATE_RUNNING = DataCollector.STATE_RUNNING
FRAME_STATE_DONE = DataCollector.STATE_DONE
FRAME_STATE_SKIPPED = DataCollector.STATE_SKIPPED

(
    MOUNT_ACTION_NONE,
    MOUNT_ACTION_DISMOUNT,
    MOUNT_ACTION_MOUNT,
) = range(3)

RUN_CONFIG_FILE = 'run_config.json'

class CollectManager(gtk.Frame):
    __gsignals__ = {
        'new-datasets': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
    }
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
        
        self.active_sample = {}
        self.active_strategy = {}
        self.update_active_data()
        
        
    def __getattr__(self, key):
        try:
            return super(CollectManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def do_new_datasets(self, dataset):
        pass
    
    def _create_widgets(self):
        self.image_viewer = ImageViewer(size=640)
        self.run_manager = RunManager()
        self.collector = DataCollector()
        self.beamline = globalRegistry.lookup([], IBeamline)      
        
        self.collect_state = COLLECT_STATE_IDLE
        self.sel_mount_action = MOUNT_ACTION_NONE 
        self.sel_mounting  = False # will be sent to true when mount command has been sent and false when it is done
        self.frame_pos = None
        
        
        pango_font = pango.FontDescription("monospace 8")
        self.strategy_view.modify_font(pango_font)

        
        # Run List
        self.listmodel = gtk.ListStore(
            gobject.TYPE_UINT,
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
            pos_table.attach(ActiveLabel(self.beamline.attenuator, format='%7.2f'), 1,2,4,5)        
        # Image Viewer
        self.frame_book.add(self.image_viewer)
        self.setup_box.pack_end(self.run_manager, expand = True, fill = True)
        
        #automounter signals
        self.beamline.automounter.connect('mounted', lambda x,y: self.update_active_data())

        
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
        self.clear_strategy_btn.connect('clicked', self.on_clear_strategy)

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
        
        #prepare pixbufs for status icons
        self._wait_img = gtk.gdk.pixbuf_new_from_file(os.path.join(os.path.dirname(__file__),
                                                               'data/tiny-wait.png'))
        self._ready_img = gtk.gdk.pixbuf_new_from_file(os.path.join(os.path.dirname(__file__),
                                                               'data/tiny-ready.png'))
        self._error_img = gtk.gdk.pixbuf_new_from_file(os.path.join(os.path.dirname(__file__),
                                                               'data/tiny-error.png'))
        self._skip_img = gtk.gdk.pixbuf_new_from_file(os.path.join(os.path.dirname(__file__),
                                                               'data/tiny-skip.png'))

        
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
        
    def update_active_data(self, sample=None, strategy=None):

        if sample is not None:
            self.active_sample = sample
        # pass in {} to delete the current strategy or None to ignore it
        # if number of keys in strategy is 6 or more then replace it
        # otherwise simply update it
        if strategy is not None:
            if strategy == {} or len(strategy.keys())> 5:
                self.active_strategy = strategy
            else:
                self.active_strategy.update(strategy)
            
        # send updated parameters to runs
        self.run_manager.update_active_data(sample=self.active_sample, strategy=self.active_strategy)
           
        self.mnt_action_btn.set_sensitive(False)
        self.mnt_action_btn.set_label('Mount')
        self.sel_mount_action = MOUNT_ACTION_NONE
        
        if self.active_sample.get('name') is not None:
            if self.active_sample.get('port') is not None:
                txt = "%s(%s)" % (self.active_sample['name'], 
                                  self.active_sample['port'])
                self.crystal_lbl.set_text(txt)
                if self.beamline.automounter.is_mounted(self.active_sample['port']):
                    self.mnt_action_btn.set_label('Dismount')
                    self.sel_mount_action = MOUNT_ACTION_DISMOUNT
                elif self.beamline.automounter.is_mountable(self.active_sample['port']):
                    self.mnt_action_btn.set_label('Mount')
                    self.sel_mount_action = MOUNT_ACTION_MOUNT
                if self.sel_mounting or self.beamline.automounter.is_busy() or not self.beamline.automounter.is_active():
                    self.sel_mount_action = MOUNT_ACTION_NONE
                    self.mnt_action_btn.set_sensitive(False)
                else:
                    self.mnt_action_btn.set_sensitive(True)
        
        if self.active_strategy != {}:
            # display text in strategy_view
            txt = ""
            for key in ['start_angle', 'delta_angle', 'exposure_time', 'attenuation', 'distance', 'total_angle']:
                if key in self.active_strategy:
                    txt += '%15s: %7.2f\n' % (key, self.active_strategy[key])
            if 'energy' in self.active_strategy:
                scat_fac = self.active_strategy.get('scattering_factors')
                if scat_fac is None:
                    txt += "%15s:\n" % ('energies')
                    for val, lbl, sf in zip(self.active_strategy['energy'], self.active_strategy['energy_label']):
                        txt += "%15s = %7.4f\n" % (lbl, val)
                else:
                    txt += "%15s:\n" % ('energies')
                    txt += "%6s %7s %6s %6s\n" % ('name', 'energy', 'f\'', 'f"')
                    txt += "  --------------------------\n"
                    for val, lbl, sf in zip(self.active_strategy['energy'], self.active_strategy['energy_label'], scat_fac):
                        txt += "%6s %7.4f %6.2f %6.2f\n" % (lbl, val, sf['fp'], sf['fpp'])
            buf = self.strategy_view.get_buffer()
            buf.set_text(txt)
            #self.active_strategy_box.set_visible(True)
            self.active_strategy_box.show()
        else:
            #self.active_strategy_box.set_visible(False)
            self.active_strategy_box.hide()

    def on_clear_strategy(self, obj):
        self.update_active_data(strategy={})
                       
    @async
    def execute_mount_action(self):
        
        if self.sel_mount_action == MOUNT_ACTION_MOUNT:
            try:
                gobject.idle_add(self.progress_bar.busy_text, 
                                 'Mounting %s ...' % self.active_sample['name'])
                self.sel_mounting = True
                gobject.idle_add(self.update_active_data)
                auto.auto_mount_manual(self.beamline, self.active_sample['port'])
                done_text = "Mount succeeded"
            except:
                _logger.error('Sample mounting failed')
                done_text = "Mount failed"
        elif self.sel_mount_action == MOUNT_ACTION_DISMOUNT:
            try:
                gobject.idle_add(self.progress_bar.busy_text, 
                                 'Dismounting %s ...' % self.active_sample['name'])
                self.sel_mounting = True
                gobject.idle_add(self.update_active_data)
                auto.auto_dismount_manual(self.beamline, self.active_sample['port'])
                done_text = "Dismount succeeded"
            except:
                _logger.error('Sample dismounting failed')
                done_text = "Dismount failed"
        
        if self.progress_bar.get_busy():
            gobject.idle_add(self.progress_bar.idle_text,  done_text)
        self.sel_mounting = False
        gobject.idle_add(self.update_active_data)
    
    
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
        if item['saved']:
            status = FRAME_STATE_DONE
        else:
            status = FRAME_STATE_PENDING
        self.listmodel.set(iter, 
            COLLECT_COLUMN_STATUS, status, 
            COLLECT_COLUMN_ANGLE, item['start_angle'],
            COLLECT_COLUMN_RUN, item['number'],
            COLLECT_COLUMN_NAME, item['frame_name']
        )
            

    def _saved_pixbuf(self, column, renderer, model, iter):
        value = model.get_value(iter, COLLECT_COLUMN_STATUS)
        if value == FRAME_STATE_PENDING:
            renderer.set_property('pixbuf', None)
        elif value == FRAME_STATE_RUNNING:
            renderer.set_property('pixbuf', self._wait_img)
        elif value == FRAME_STATE_DONE:
            renderer.set_property('pixbuf', self._ready_img)
        elif value == FRAME_STATE_SKIPPED:
            renderer.set_property('pixbuf', self._skip_img)
        else:
            renderer.set_property('pixbuf', None)

    def _saved_color(self,column, renderer, model, iter):
        status = model.get_value(iter, COLLECT_COLUMN_STATUS)
        _state_colors = {
            FRAME_STATE_PENDING : None,
            FRAME_STATE_RUNNING : '#990099',
            FRAME_STATE_SKIPPED : '#777777',
            FRAME_STATE_DONE : '#006600',
            }
        renderer.set_property("foreground", _state_colors.get(status))
        return      

    def _float_format(self, column, renderer, model, iter, format):
        value = model.get_value(iter, COLLECT_COLUMN_ANGLE)
        renderer.set_property('text', format % value)
        self._saved_color(column, renderer, model, iter)
        return
                
    def _add_columns(self):
        # Saved Column
        renderer = gtk.CellRendererPixbuf()
        column = gtk.TreeViewColumn('', renderer)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(24)
        column.set_cell_data_func(renderer, self._saved_pixbuf)
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
                    self.set_row_state(index, FRAME_STATE_SKIPPED)
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
            
    def set_row_state(self, pos, status):
        path = (pos,)
        try:
            iter = self.listmodel.get_iter(path)
            self.listmodel.set(iter, COLLECT_COLUMN_STATUS, status)
            self.listview.scroll_to_cell(path, use_align=True, row_align=0.7)
        except ValueError:
            #only change valid positions
            pass
        
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
                status = model.get_value(iter, COLLECT_COLUMN_STATUS)
                if status != FRAME_STATE_DONE:
                    model.set(iter, COLLECT_COLUMN_STATUS, FRAME_STATE_SKIPPED)
                self.run_list[i]['saved'] = True
            elif i == self.frame_pos:
                model.set(iter, COLLECT_COLUMN_STATUS, FRAME_STATE_RUNNING)
                self.run_list[i]['saved'] = False
            else:
                model.set(iter, COLLECT_COLUMN_STATUS, FRAME_STATE_PENDING)
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
            model.set(iter, COLLECT_COLUMN_STATUS, False)
            self.run_list[i]['saved'] = False
        else:
            model.set(iter, COLLECT_COLUMN_STATUS, True)
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
        
        self.emit('new-datasets', obj.results)
        try:
            lims_tools.upload_data(self.beamline, obj.results)
        except:
            print sys.exc_info()
            _logger.warn('Could not upload dataset to LIMS.')

    def on_new_image(self, widget, index, filename):
        self.frame_pos = index
        self.image_viewer.add_frame(filename)
      

    def on_progress(self, obj, fraction, position, state):
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
        self.set_row_state(position, state)

                
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
    
                                                                                                                                                                              
