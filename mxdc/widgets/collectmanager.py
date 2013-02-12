   
from bcm.beamline.interfaces import IBeamline
from bcm.engine.diffraction import DataCollector
from bcm.engine.scripting import get_scripts
from bcm.utils import runlists, lims_tools
from bcm.utils.log import get_module_logger
from mxdc.utils import config, gui
from mxdc.widgets.dialogs import warning, error, MyDialog
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.widgets.misc import ActiveLabel, ActiveProgressBar
from mxdc.widgets.mountwidget import MountWidget
from mxdc.widgets.runmanager import RunManager
from twisted.python.components import globalRegistry
import gobject
import gtk
import pango
import sys
import os
import time

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
    MOUNT_ACTION_MANUAL_DISMOUNT,
    MOUNT_ACTION_MANUAL_MOUNT
) = range(5)

RUN_CONFIG_FILE = 'run_config.json'

class CollectManager(gtk.Alignment):
    __gsignals__ = {
        'new-datasets': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
    }
    def __init__(self):
        gtk.Alignment.__init__(self, 0.5, 0.5, 1, 1)
        self._xml = gui.GUIFile(os.path.join(os.path.dirname(__file__), 'data/collect_widget'), 
                                  'collect_widget')            
        self.run_data = []
        self.run_list = []
        
        self.collect_state = COLLECT_STATE_IDLE
        self.frame_pos = None
        self._first_launch = False
        self.await_response = False
        self.skip_frames = False
        self._create_widgets()
        self.pause_time = 0
        self.auto_pause = False
        
        self.active_sample = {}
        self.selected_sample = {}
        self.active_strategy = {}
        self.connect('realize', lambda x: self.update_data())
        
        self.scripts = get_scripts()
        
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
        self.mount_widget = MountWidget()
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
        
        self.mnt_hbox.add(self.mount_widget)

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
            pos_table.attach(ActiveLabel(self.beamline.omega, fmt='%7.2f'), 1,2,0,1)
            pos_table.attach(ActiveLabel(self.beamline.diffractometer.two_theta, fmt='%7.2f'), 1,2,1,2)
            pos_table.attach(ActiveLabel(self.beamline.diffractometer.distance, fmt='%7.2f'), 1,2,2,3)
            pos_table.attach(ActiveLabel(self.beamline.monochromator.energy, fmt='%7.4f'), 1,2,3,4)
            pos_table.attach(ActiveLabel(self.beamline.attenuator, fmt='%7.2f'), 1,2,4,5)        
        # Image Viewer
        self.frame_book.add(self.image_viewer)
        self.collect_widget.pack_end(self.run_manager, expand = True, fill = True)
        
        #automounter signals
        self.beamline.automounter.connect('busy', self.on_mount_busy)
        self.beamline.automounter.connect('mounted', self.on_mount_done)
        self.beamline.manualmounter.connect('mounted', self.on_mount_done)
        
        #diagnostics
        #self.diagnostics = DiagnosticsWidget()
        #self.tool_book.append_page(self.diagnostics, tab_label=gtk.Label('Run Diagnostics'))
        #self.tool_book.connect('realize', lambda x: self.tool_book.set_current_page(0))
        #self.diagnostics.set_sensitive(False)
        
        self.listview.connect('row-activated',self.on_row_activated)
        self.collect_btn.connect('clicked',self.on_activate)
        self.stop_btn.connect('clicked', self.on_stop_btn_clicked)
        self.run_manager.connect('saved', self.save_runs)
        self.clear_strategy_btn.connect('clicked', self.on_clear_strategy)

        for w in [self.collect_btn, self.stop_btn]:
            w.set_property('can-focus', False)
        
        self.collector.connect('done', self.on_done)
        self.collector.connect('error', self.on_error)
        self.collector.connect('paused',self.on_pause)
        self.collector.connect('new-image', self.on_new_image)
        self.collector.connect('stopped', self.on_stopped)
        self.collector.connect('progress', self.on_progress)
        
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

    def update_data(self, sample=None, strategy=None):
        # pass in {} to delete the current setting or None to ignore it
        #self.mount_widget.update_data(sample)
        # handle strategy data
        if strategy is not None:
            # if number of keys in strategy is 6 or more then replace it
            # otherwise simply update it
            if strategy == {} or len(strategy.keys())> 5:
                self.active_strategy = strategy
            else:
                self.active_strategy.update(strategy)
            
            # send updated strategy parameters to runs, do not send active sample
            self.run_manager.update_active_data(strategy=self.active_strategy)
            
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
        
    def update_active_sample(self, sample=None):   
        # send updated parameters to runs
        if sample is None:
            self.active_sample = {}
        else:
            self.active_sample = sample
        self.mount_widget.update_active_sample(self.active_sample)
        self.run_manager.update_active_data(sample=self.active_sample)

    def update_selected(self, sample=None):
        self.mount_widget.update_selected(sample)

    def on_clear_strategy(self, obj):
        self.update_data(strategy={})
                       
    def on_mount_busy(self, obj, busy):
        if busy:
            self.progress_bar.busy_text(self.mount_widget.busy_text)
        else:
            self.progress_bar.idle_text('')

    def on_mount_done(self, obj, state):
        if obj.__class__.__name__ is "ManualMounter":
            if state is not None:
                done_text = "Manual Mount"
            else:
                done_text = "Manual Dismount"
        else:
            if state is not None and obj.health_state[0] == 0:
                done_text = "Mount Succeeded"
            elif obj.health_state[0] == 0:
                done_text = "Dismount Succeeded"
            else:
                done_text = obj.health_state[1]
        self.progress_bar.idle_text(done_text)
        
    def config_user(self):
        username = os.environ['USER']
        userid = os.getuid()
        groupid = os.getgid()
        try:
            assert(self.beamline.image_server.is_active()==True)
            self.beamline.image_server.set_user(username, userid, groupid)
            return True
        except:
            msg_title = 'Image Synchronization Server Error'
            msg_sub = 'MXDC could not configure the server for the current user. '
            msg_sub += 'Data collection can not proceed reliably without the server up and running.'
            warning(msg_title, msg_sub)
            return False


    def _add_item(self, item):
        itr = self.listmodel.append()
        if item['saved']:
            status = FRAME_STATE_DONE
        else:
            status = FRAME_STATE_PENDING
        self.listmodel.set(itr, 
            COLLECT_COLUMN_STATUS, status, 
            COLLECT_COLUMN_ANGLE, item['start_angle'],
            COLLECT_COLUMN_RUN, item['number'],
            COLLECT_COLUMN_NAME, item['frame_name']
        )
            

    def _saved_pixbuf(self, column, renderer, model, itr):
        value = model.get_value(itr, COLLECT_COLUMN_STATUS)
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

    def _saved_color(self,column, renderer, model, itr):
        status = model.get_value(itr, COLLECT_COLUMN_STATUS)
        _state_colors = {
            FRAME_STATE_PENDING : None,
            FRAME_STATE_RUNNING : '#990099',
            FRAME_STATE_SKIPPED : '#777777',
            FRAME_STATE_DONE : '#006600',
            }
        renderer.set_property("foreground", _state_colors.get(status))
        return      

    def _float_format(self, column, renderer, model, itr, fmt):
        value = model.get_value(itr, COLLECT_COLUMN_ANGLE)
        renderer.set_property('text', fmt % value)
        self._saved_color(column, renderer, model, itr)
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
            assert(self.beamline.image_server.is_active())            
            for run in self.run_manager.runs:
                data = run.get_parameters()                
                self.beamline.image_server.setup_folder(data['directory'])
                if run_num == 0 and data['number'] == 0:
                    data['energy'] = [self.beamline.monochromator.energy.get_position()]
                    data['energy_label'] = ['E0']
                    self.run_data = [data]
                    break
                elif (run_num == data['number'] or run.is_enabled()) and data['number'] != 0:
                    self.run_data.append(data)
        except:
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
                return True
            else:
                return False
        return True
            
    def set_row_state(self, pos, status):
        path = (pos,)
        try:
            itr = self.listmodel.get_iter(path)
            self.listmodel.set(itr, COLLECT_COLUMN_STATUS, status)
            self.listview.scroll_to_cell(path, use_align=True, row_align=0.7)
        except ValueError:
            #only change valid positions
            pass
        
    def on_row_activated(self, treeview, path, column):
        if self.collect_state != COLLECT_STATE_PAUSED:
            return True
        model = treeview.get_model()
        itr = model.get_iter_first()
        pos = model.get_iter(path)
        self.frame_pos = model.get_path(pos)[0]             
        while itr:
            i = model.get_path(itr)[0]
            if i < self.frame_pos:
                status = model.get_value(itr, COLLECT_COLUMN_STATUS)
                if status != FRAME_STATE_DONE:
                    model.set(itr, COLLECT_COLUMN_STATUS, FRAME_STATE_SKIPPED)
                self.run_list[i]['saved'] = True
            elif i == self.frame_pos:
                model.set(itr, COLLECT_COLUMN_STATUS, FRAME_STATE_RUNNING)
                self.run_list[i]['saved'] = False
            else:
                model.set(itr, COLLECT_COLUMN_STATUS, FRAME_STATE_PENDING)
                self.run_list[i]['saved'] = False
            itr = model.iter_next(itr)
            
        if self.collect_state == COLLECT_STATE_PAUSED:
            self.collector.set_position( self.frame_pos )
        return True
    
    def on_row_toggled(self, treeview, path, column):
        if self.collect_state != COLLECT_STATE_PAUSED:
            return True
        model = treeview.get_model()
        itr = model.get_iter_first()
        pos = model.get_iter(path)
        i = model.get_path(pos)[0]             
        if self.run_list[i]['saved'] :
            model.set(itr, COLLECT_COLUMN_STATUS, False)
            self.run_list[i]['saved'] = False
        else:
            model.set(itr, COLLECT_COLUMN_STATUS, True)
            self.run_list[i]['saved'] = True
        return True

    def on_pause(self, widget, paused, pause_dict):
        if paused:
            self.paused = True
            self.pause_start = time.time()
            self.collect_btn.set_label('mxdc-resume')
            self.collect_state = COLLECT_STATE_PAUSED
            self.progress_bar.idle_text("Paused")
            self.collect_btn.set_sensitive(True)
        else:
            self.paused = False
            self.pause_time = time.time() - self.pause_start
            self.collect_btn.set_label('mxdc-pause')   
            self.collect_state = COLLECT_STATE_RUNNING
  
        # Build the dialog message
        msg = ''
        if 'type' in pause_dict:
            msg = "Beam not Available. Collection has been paused and will automatically resume once the beam becomes available. Intervene to manually resume collection."
            self.auto_pause = True

        if msg:
            title = 'Attention Required'
            self.resp = MyDialog(gtk.MESSAGE_WARNING, 
                                         title, msg,
                                         buttons=( ('Intervene', gtk.RESPONSE_ACCEPT),) )
            self._intervening = False
            self.beam_connect = self.beamline.storage_ring.connect('beam', self._on_beam_change)
            try:
                self.ntot += 1
                self.collect_obj = pause_dict['collector']
                self.collector.set_position(pause_dict['position'])
            except:
                self.collect_obj = False
            response = self.resp()
            if response == gtk.RESPONSE_ACCEPT or (('type' in pause_dict) and self._beam_up):
                self._intervening = True
                self._beam_up = False
                if self.beam_connect:
                    self.beamline.storage_ring.disconnect(self.beam_connect)
                return 

    def _on_beam_change(self, obj, beam_available):
        
        def resume_screen(script, obj):
            if self.collect_obj:
                self.paused = False
            self.collector.resume()
            self.resp.dialog.destroy()
            s.disconnect(self.resume_connect)
            
        if beam_available and not self._intervening and self.paused:
            self._beam_up = True
            s = self.scripts['RestoreBeam']
            self.resume_connect = s.connect('done', resume_screen )
            s.start()
        return True  

            
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
    
    def on_done(self, obj=None):
        self.on_complete(obj)
        text = 'Completed in %s' % time.strftime('%H:%M:%S', time.gmtime(time.time() - self.init_time))
        self.progress_bar.idle_text(text)

    def on_stopped(self, obj=None):
        self.on_complete(obj)
        self.progress_bar.idle_text("Stopped")

    def on_complete(self, obj=None):
        self.collect_state = COLLECT_STATE_IDLE
        self.collect_btn.set_label('mxdc-collect')
        self.stop_btn.set_sensitive(False)
        self.run_manager.set_sensitive(True)
        self.image_viewer.set_collect_mode(False)
        
        self.emit('new-datasets', obj.results)
        try:
            lims_tools.upload_data(self.beamline, obj.results)
        except:
            print sys.exc_info()
            _logger.warn('Could not upload dataset meta-data to MxLIVE.')

    def on_new_image(self, widget, index, filename):
        self.frame_pos = index
        self.image_viewer.add_frame(filename)
      

    def on_progress(self, obj, fraction, position, state):
        self.set_row_state(position, state)
        if position == 0:
            self.skipped = 0
        self.start_time = (position == self.skipped) and time.time() or self.start_time + self.pause_time
        self.pause_time = 0
        if state == FRAME_STATE_RUNNING and position != self.skipped:
            elapsed_time = time.time() - self.start_time
            if position - 1 > self.skipped:
                self.frame_time = ( self.auto_pause and self.frame_time ) or elapsed_time / ( position -1 - self.skipped )
                if self.auto_pause: self.auto_pause = False
                eta_time = self.frame_time * ( self.ntot - position )
                eta_format = eta_time >= 3600 and '%H:%M:%S' or '%M:%S'
                text = "ETA %s @ %0.1fs/f" % (time.strftime(eta_format, time.gmtime(eta_time)), self.frame_time)
            else:
                if fraction: 
                    self.ntot = int(round(position / fraction))
                text = "Calculating ETA..."
            self.progress_bar.set_complete(fraction, text)
        elif state == FRAME_STATE_SKIPPED: # skipping this frame
            self.skipped += 1

    def on_energy_changed(self, obj, val):
        run_zero = self.run_manager.runs[0]
        data = run_zero.get_parameters()
        data['energy'] = [ val ]
        run_zero.set_parameters(data)

    def update_values(self, dct):        
        for key in dct.keys():
            self.labels[key].set_text(dct[key])

    def start_collection(self):
        self.init_time = time.time()
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
    
                                                                                                                                                                              
