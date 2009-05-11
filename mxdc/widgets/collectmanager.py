import gtk, gobject
import sys, os, time

from twisted.python.components import globalRegistry
from bcm.beamline.mx import IBeamline
from bcm.engine.diffraction import DataCollector
from bcm.utils.configobj import ConfigObj
from bcm.utils import misc

from mxdc.widgets.misc import ActiveLabel, ActiveProgressBar
from mxdc.widgets.runmanager import RunManager
from mxdc.widgets.imageviewer import ImageViewer
from mxdc.widgets.dialogs import *

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

class CollectManager(gtk.Frame):
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self.run_data = {}
        self.run_list = []
        self.collect_state = COLLECT_STATE_IDLE
        self.frame_pos = None
        self._first_launch = False
        self._create_widgets()
        
    def _create_widgets(self):
        self._xml = gtk.glade.XML(os.path.join(os.path.dirname(__file__), 'data/collect_widget.glade'), 
                                  'collect_widget')            
        self.image_viewer = ImageViewer(size=560)
        self.run_manager = RunManager()
        self.collector = DataCollector()
        self.beamline = globalRegistry.lookup([], IBeamline)      
        
        self.collect_state = COLLECT_STATE_IDLE
        self.frame_pos = None
        self.control_box = self._xml.get_widget('control_box')
        self.collect_widget = self._xml.get_widget('collect_widget')
        
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

        self.collect_btn = self._xml.get_widget('collect_btn')
        self.stop_btn = self._xml.get_widget('stop_btn')
        self.collect_btn.set_label('mxdc-collect')
        self.stop_btn.set_label('mxdc-stop')
        self.stop_btn.set_sensitive(False)
        
        # Run progress
        self.progress_bar = ActiveProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.idle_text('0%')
        self.control_box.pack_start(self.progress_bar, expand=False, fill=True)
        
        # Dose Control
        dose_frame = self._xml.get_widget('dose_frame')
        dose_frame.set_sensitive(False)
        self.dose_enable_btn = self._xml.get_widget('dose_enable_btn')
        self.dose_factor_label = self._xml.get_widget('dose_factor_label')
        self.dose_norm_btn = self._xml.get_widget('dose_norm_label')
        
        # Current Position
        pos_table = self._xml.get_widget('position_table')
        if self.beamline is not None:
            pos_table.attach(ActiveLabel(self.beamline.goniometer.omega, format='%7.2f'), 1,2,0,1)
            pos_table.attach(ActiveLabel(self.beamline.diffractometer.two_theta, format='%7.2f'), 1,2,1,2)
            pos_table.attach(ActiveLabel(self.beamline.diffractometer.distance, format='%7.2f'), 1,2,2,3)
            pos_table.attach(ActiveLabel(self.beamline.monochromator.energy, format='%7.4f'), 1,2,3,4)
        
        # Image Viewer
        img_frame = self._xml.get_widget('image_frame')
        img_frame.add(self.image_viewer)
        self.collect_widget.pack_end(self.run_manager, expand = False, fill = True)
        
        self.listview.connect('row-activated',self.on_row_activated)
        self.collect_btn.connect('clicked',self.on_activate)
        self.stop_btn.connect('clicked', self.on_stop_btn_clicked)
        self.run_manager.connect('saved', self.save_runs)
        self.run_manager.connect('del-run', self.remove_run)

        for w in [self.collect_btn, self.stop_btn]:
            w.set_property('can-focus', False)
        
        self.collector.connect('done', self.on_complete)
        self.collector.connect('error', self.on_error)
        self.collector.connect('paused',self.on_pause)
        self.collector.connect('new-image', self.on_new_image)
        self.collector.connect('stopped', self.on_stop)
        self.collector.connect('progress', self.on_progress)

        if self.beamline is not None:
            self.beamline.registry['ring_status'].connect('changed', self._on_inject)
            self.beamline.registry['ring_current'].connect('changed', self._on_dump)
            self.beamline.registry['ring_mode'].connect('changed', self._on_dump)
        
        self._load_config()
        self.add(self.collect_widget)
        self.run_manager.set_current_page(0)
        self.show_all()
        
    def _on_inject(self, obj, value):
        if value == 1 and (not self.collector.stopped) and (not self.collector.paused):
            self.collector.pause()
            header = "Data Collection has been paused while the storage ring is re-filled!"
            sub_header = "Please resume data collection when the beamline is ready for data collection."
            response = warning(header, sub_header)
        return True

    def _on_dump(self, obj, value):
        if self._first_launch:
            self._last_current = value
        else:
            self._last_current = 0
            self._first_launch = False  
            
        if (self._last_current - self.beamline.registry['ring_current'].get() > 10):
            if  (self.collector.stopped) or (self.collector.paused):
                return True
            self.collector.pause()
            header = "Data Collection has been paused due to beam dump!"
            sub_header = "Please resume data collection when the beamline is ready for data collection."
            response = warning(header, sub_header)
        self._last_current = self.beamline.registry['ring_current'].get()
        return True

    def _load_config(self):

        config_file = os.environ['HOME'] + '/.mxdc/run_config2.dat'
        if os.access(config_file, os.R_OK):
            data = {}
            config = ConfigObj(config_file, options={'unrepr':True})
            for section in config.keys():
                run = int(section)
                data[run] = config[section]
                self.add_run(data[run])

    def _save_config(self):
        config_dir = os.environ['HOME'] + '/.mxdc'
        # create configuration directory if none exists
        if not os.access( config_dir , os.R_OK):
            if os.access( os.environ['HOME'], os.W_OK):
                os.mkdir( config_dir )
                
        config = ConfigObj()
        config.unrepr = True
        config_file = os.path.join(config_dir,'run_config2.dat')
        save_data = {}
        for run in self.run_manager.runs:
            data = run.get_parameters()
            save_data[ data['number'] ] = data
        if os.access(config_dir, os.W_OK):
            config.filename = config_file
            for key in save_data.keys():
                data = save_data[key]
                keystr = "%s" % key
                config[keystr] = data
            config.write()
        else:
            msg_title = 'Directory Error'
            msg_sub = 'MXDC could not setup directories for data collection. '
            msg_sub += 'Data collection will not proceed reliably.'
            warning(msg_title, msg_sub)
            

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
            COLLECT_COLUMN_RUN, item['run_number'],
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
        for run in self.run_manager.runs:
            if run.is_enabled():
                data = run.get_parameters()
                res = self.beamline.image_server.setup_folder(data['directory'])
                try:
                    assert(res == True)
                    self.run_data[ data['number'] ] = data
                except:
                    run.disable_run()
                    msg_title = 'Invalid Directory: "%s"' % data['directory']
                    msg_sub = 'Could not setup directory for run <b>%d</b>.  ' % data['number']
                    msg_sub += 'The run has been disabled.  To execute the run, '
                    msg_sub += 'please select a valid directory and re-activate the run '
                    msg_sub += 'manually before proceeding.'
                    warning(msg_title, msg_sub)

        self._save_config()
        self.create_runlist()
        
    def add_run(self, data):
        self.run_manager.add_new_run(data)
        self.create_runlist()
            
    
    def remove_run(self, obj, index):
        run_data = {}
        for key in self.run_data.keys():
            if key < index:
                run_data[key] = self.run_data[key]
                run_data[key]['number'] = key
            elif key > index:
                run_data[key-1] = self.run_data[key]
                run_data[key-1]['number'] = key-1
        self.run_data = run_data
    
    def clear_runs(self):
        self.run_data.clear()
            
    def create_runlist(self):
        run_num = self.run_manager.get_current_page()
        run_data = self.run_data.copy()

        if run_num != 0 and 0 in run_data.keys():
            del run_data[0]
        elif 0 in run_data.keys():
            run_data = {0: run_data[0],}
            if self.beamline is not None:
                run_data[0]['energy'] = [self.beamline.monochromator.energy.get_position()]
            run_data[0]['energy_label'] = ['E0']
        self.run_list = []
        if len( run_data.keys() ) > 1:
            show_number = True
        else:
            show_number = False
        for run in run_data.values():
            self.run_list += misc.generate_run_list(run, show_number)

        self.frame_pos = 0
        self.gen_sequence()
                                                                        
    def gen_sequence(self):
        self.listmodel.clear()
        for item in self.run_list:
            self._add_item(item)
    
    def check_runlist(self):
        existlist = []
        details = ""
        for frame in self.run_list:
            path_to_frame = "%s/%s" % (frame['directory'],frame['file_name'])
            if os.path.exists(path_to_frame):
                existlist.append( frame['index'] )
                details += frame['file_name'] + "\n"
        if len(existlist) > 0:
            header = 'Frames from this sequence already exist! Do you want to skip or replace them?'
            sub_header = 'Replacing them will overwrite their contents. Skipped frames will not be re-acquired.'
            buttons = ( ('gtk-cancel',gtk.RESPONSE_CANCEL), ('Skip', gtk.RESPONSE_YES), ('Replace', gtk.RESPONSE_NO))
            response = warning(header, sub_header, details, buttons=buttons)
            if response == gtk.RESPONSE_YES:
                for index in existlist:
                    self.run_list[index]['saved'] = True
                    self.set_row_state(index, saved=True)
                return True
            elif response == gtk.RESPONSE_NO:
                for index in existlist:
                    old_name = "%s/%s" % (self.run_list[index]['directory'], self.run_list[index]['file_name']) 
                    new_name = old_name + '.bk'
                    os.rename(old_name, new_name)
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

    def on_pause(self,widget, paused):
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
        
    def on_stop(self, widget=None):
        self.collect_state = COLLECT_STATE_IDLE
        self.collect_btn.set_label('mxdc-collect')
        self.stop_btn.set_sensitive(False)
        self.run_manager.set_sensitive(True)
        self.image_viewer.set_collect_mode(False)
        self.progress_bar.idle_text("Stopped")
    
    def on_complete(self, widget=None):
        self.collect_state = COLLECT_STATE_IDLE
        self.collect_btn.set_label('mxdc-collect')
        self.stop_btn.set_sensitive(False)
        self.run_manager.set_sensitive(True)
        self.image_viewer.set_collect_mode(False)
        self.progress_bar.idle_text("Stopped")

    def on_new_image(self, widget, index, filename):
        self.frame_pos = index
        self.set_row_state(index, saved=True)
        self.image_viewer.add_frame(filename)
      

    def on_progress(self, obj, fraction, position):
        if position == 1:
            self.start_time = time.time()
        elapsed_time = time.time() - self.start_time
        if fraction > 0:
            time_unit = elapsed_time / fraction
        else:
            time_unit = 0.0
        
        eta_time = time_unit * (1 - fraction)
        percent = fraction * 100
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
                self.collector.configure(run_list=self.run_list, skip_collected=True)
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
    
                                                                                                                                                                              