import gtk, gobject
import sys, os, time
from bcm.tools.DataCollector import DataCollector
from ActiveWidgets import PositionerLabel, ActiveProgressBar
from RunManager import RunManager
from ImgViewer import ImgViewer
from bcm.tools.configobj import ConfigObj
from Dialogs import *
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

class CollectManager(gtk.HBox):
    def __init__(self, beamline=None):
        gtk.HBox.__init__(self,False,6)
        self.__register_icons()
        self.run_data = {}
        self.labels = {}
        self.run_list = []
        self.beamline = beamline
        self.image_viewer = ImgViewer()
        self.run_manager = RunManager()
        self.collector = DataCollector(beamline)
        self.collect_state = COLLECT_STATE_IDLE
        self.pos = None
        self.listmodel = gtk.ListStore(
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_FLOAT,
            gobject.TYPE_UINT,
            gobject.TYPE_STRING
            
        )
        controlbox = gtk.VBox(False,6)
                
        self.listview = gtk.TreeView(self.listmodel)
        self.listview.set_rules_hint(True)
        self.__add_columns()
        listbox = gtk.ScrolledWindow()
        listbox.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        listbox.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        listbox.add(self.listview)
        controlbox.pack_end(listbox, expand=True, fill=True)

        bbox = gtk.HBox(True, 3)
        self.collect_btn = gtk.Button(stock='cm-collect')
        self.stop_btn = gtk.Button(stock='cm-stop')
        self.stop_btn.set_sensitive(False)
        bbox.pack_start(self.collect_btn, expand=True, fill=True)
        bbox.pack_start(self.stop_btn, expand=True, fill=True)
        controlbox.pack_start(bbox, expand=False, fill=True)
        self.progress_bar = ActiveProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.idle_text('0%')
        controlbox.pack_end(self.progress_bar, expand=False, fill=True)
        dose_frame = gtk.Frame(label='Dose Control')
        dose_frame.set_sensitive(False)
        dosevbox = gtk.VBox(False, 3)
        self.dose_mode = gtk.CheckButton('Dose Mode')
        dosevbox.pack_start(self.dose_mode)
        dosehbox = gtk.HBox(True, 3)
        self.labels['dose_factor'] =gtk.Label('Dose Factor:')
        dosehbox.pack_start(self.labels['dose_factor'], expand=False, fill=False)
        self.dose_normalize_btn = gtk.Button('Normalize')
        self.dose_factor = gtk.Label('1.0')
        dosehbox.pack_start(self.dose_factor)
        dosehbox.pack_end(self.dose_normalize_btn)
        dosevbox.pack_start(dosehbox)
        dosevbox.set_border_width(6)
        dose_frame.add(dosevbox)
        
        # Data for labels (label: (col, row))
        pos_frame = gtk.Frame(label='Current Position')
        pos_table = gtk.Table(3,3,True)
        items = {
            'omega':      ('Omega angle:', 0, 0, 'deg'),
            'det_2th':   ('Two Theta:',0, 1, 'deg'),
            'det_d':    ('Distance:',0, 2, 'mm'),
            'energy':    ('Energy:',0, 3, 'keV')
        }
        for (key,val) in zip(items.keys(),items.values()):
            label = gtk.Label(val[0])
            label.set_alignment(1,0.5)
            pos_table.attach( label, val[1], val[1]+1, val[2], val[2]+1)
            pos_table.attach(gtk.Label(val[3]), 2, 3, val[2], val[2]+1)
            if self.beamline is not None:
                pos_label = PositionerLabel( self.beamline.devices[key], format="%8.4f" )
                pos_label.set_alignment(1,0.5)
                pos_table.attach(pos_label,1, 2, val[2], val[2]+1)
        pos_table.set_border_width(3)
        pos_frame.add(pos_table)
        
        controlbox.pack_start(pos_frame, expand=False, fill=False)
        controlbox.pack_start(dose_frame, expand=False, fill=False)
        self.pack_start(self.image_viewer,expand = False, fill = False)
        self.pack_start(controlbox)
        self.pack_start(self.run_manager)
        self.show_all()
        
        self.listview.connect('row-activated',self.on_row_activated)
        self.collect_btn.connect('clicked',self.on_activate)
        self.stop_btn.connect('clicked', self.on_stop_btn_clicked)
        self.run_manager.connect('saved', self.save_runs)

        for w in [self.collect_btn, self.stop_btn]:
            w.set_property('can-focus', False)
        
        self.collector.connect('done', self.on_complete)
        self.collector.connect('error', self.on_error)
        self.collector.connect('paused',self.on_pause)
        self.collector.connect('new-image', self.on_new_image)
        self.collector.connect('stopped', self.on_stop)
        self.collector.connect('progress', self.on_progress)

        if self.beamline is not None:
            self.beamline.status.connect('changed', self._on_inject)
       
        
        self.set_border_width(6)
        self.__load_config()
        
    def _on_inject(self, obj, value):
        if value != 0 and  not self.collection.stopped:
            self.collector.pause()
            header = "Data Collection has been paused while the storage ring is re-filled!"
            sub_header = "Please resume data collection when the beamline is ready for data collection."
            response = warning(header, sub_header)
        return False

    def __load_config(self):

        config_file = os.environ['HOME'] + '/.mxdc/run_config2.dat'
        if os.access(config_file, os.R_OK):
            data = {}
            config = ConfigObj(config_file, options={'unrepr':True})
            for section in config.keys():
                run = int(section)
                data[run] = config[section]
                self.add_run(data[run])
        self.beamline.energy.connect('changed', self.on_energy_changed)
        data = self.run_manager.runs[0].get_parameters()
        data['energy'] = [ self.beamline.energy.get_position() ]
        self.run_manager.runs[0].set_parameters(data)

    def __save_config(self):
        config_dir = os.environ['HOME'] + '/.mxdc'
        # create configuration directory if none exists
        if not os.access( config_dir , os.R_OK):
            if os.access( os.environ['HOME'], os.W_OK):
                os.mkdir( config_dir )
                
        config = ConfigObj()
        config.unrepr = True
        config_file = os.environ['HOME'] + '/.mxdc/run_config2.dat'

        if os.access(config_dir,os.W_OK):
            config.filename = config_file
            for key in self.run_data.keys():
                data = self.run_data[key]
                keystr = "%s" % key
                config[keystr] = data
                res = self.beamline.image_server.create_folder(data['directory'])
                try:
                    assert(res == True)
                except:
                    msg_title = 'Image Syncronization Server Error'
                    msg_sub = 'MXDC could not successfully connect to the Image Synchronization Server. '
                    msg_sub += 'Data collection can not proceed reliably without the server up and running.'
                    warning(msg_title, msg_sub)
            config.write()

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
            msg_sub = 'MXDC could not successfully connect to the Image Synchronization Server. '
            msg_sub += 'Data collection can not proceed reliably without the server up and running.'
            warning(msg_title, msg_sub)
            return False


    def __add_item(self, item):
        iter = self.listmodel.append()        
        self.listmodel.set(iter, 
            COLLECT_COLUMN_SAVED, item['saved'], 
            COLLECT_COLUMN_ANGLE, item['start_angle'],
            COLLECT_COLUMN_RUN, item['run_number'],
            COLLECT_COLUMN_NAME, item['frame_name']
        )
    
    def __register_icons(self):
        items = [('cm-collect', '_Collect', 0, 0, None),
            ('cm-resume', '_Resume', 0, 0, None),
            ('cm-pause', '_Pause', 0, 0, None),
            ('cm-stop', '_Stop', 0, 0, None)]

        # We're too lazy to make our own icons, so we use regular stock icons.
        aliases = [('cm-collect', gtk.STOCK_EXECUTE),
            ('cm-resume', gtk.STOCK_EXECUTE),
            ('cm-pause', gtk.STOCK_EXECUTE),
            ('cm-stop', gtk.STOCK_STOP) ]

        gtk.stock_add(items)
        factory = gtk.IconFactory()
        factory.add_default()
        for new_stock, alias in aliases:
            icon_set = gtk.icon_factory_lookup_default(alias)
            factory.add(new_stock, icon_set)
        
    def __float_format(self, column, renderer, model, iter, format):
        value = model.get_value(iter, COLLECT_COLUMN_ANGLE)
        saved = model.get_value(iter, COLLECT_COLUMN_SAVED)
        renderer.set_property('text', format % value)
        if saved:
            renderer.set_property("foreground", '#cc0000')
        else:
            renderer.set_property("foreground", None)
        return

    def __saved_color(self,column, renderer, model, iter):
        value = model.get_value(iter, COLLECT_COLUMN_SAVED)
        if value:
            renderer.set_property("foreground", '#cc0000')
        else:
            renderer.set_property("foreground", None)
        return
        
                
    def __add_columns(self):
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
        column.set_cell_data_func(renderer, self.__saved_color)
        self.listview.append_column(column)

        # Angle Column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Angle', renderer, text=COLLECT_COLUMN_ANGLE)
        column.set_cell_data_func(renderer, self.__float_format, '%5.2f')
        self.listview.append_column(column)
        
        
    def save_runs(self, obj=None):
        self.clear_runs()
        for run in self.run_manager.runs:
            data = run.get_parameters()
            if check_folder(data['directory']) and run.is_enabled():
                self.run_data[ data['number'] ] = data
            else:
                return
        self.__save_config()
        self.create_runlist()
        
    def add_run(self, data):
        self.run_manager.add_new_run(data)
        self.create_runlist()
            
    
    def remove_run(self, index):
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
            run_keys = run_data.keys()
        elif 0 in run_data.keys():
            run_keys = [0,]
            if self.beamline is not None:
                run_data[0]['energy'] = [self.beamline.energy.get_position()]
            run_data[0]['energy_label'] = ['E0']
            
        else:
            run_keys = run_data.keys()
            
        self.run_list = []
        index = 0
        
        for pos in run_keys:
            run = run_data[pos]
            offsets = run['inverse_beam'] and [0, 180] or [0,]
            
            angle_range = run['angle_range']
            wedge = run['wedge'] < angle_range and run['wedge'] or angle_range
            wedge_size = int( (wedge) / run['delta'])
            total_size = run['num_frames']
            passes = int ( round( 0.5 + (angle_range-run['delta']) / wedge) ) # take the roof (round_up) of the number
            remaining_frames = total_size
            current_slice = wedge_size
            for i in range(passes):
                if current_slice > remaining_frames:
                    current_slice = remaining_frames
                for (energy,energy_label) in zip(run['energy'],run['energy_label']):
                    if len(run['energy']) > 1:
                        energy_tag = "_%s" % energy_label
                    else:
                        energy_tag = ""
                    for offset in offsets:                        
                        for j in range(current_slice):
                            angle = run['start_angle'] + (j * run['delta']) + (i * wedge) + offset
                            frame_number =  i * wedge_size + j + int(offset/run['delta']) + run['start_frame']
                            if len(run_keys) > 1:
                                frame_name = "%s_%d%s_%03d" % (run['prefix'], run['number'], energy_tag, frame_number)
                            else:
                                frame_name = "%s%s_%03d" % (run['prefix'], energy_tag, frame_number)
                            file_name = "%s.img" % (frame_name)
                            list_item = {
                                'index': index,
                                'saved': False, 
                                'frame_number': frame_number,
                                'run_number': run['number'], 
                                'frame_name': frame_name, 
                                'file_name': file_name,
                                'start_angle': angle,
                                'delta': run['delta'],
                                'time': run['time'],
                                'energy': energy,
                                'distance': run['distance'],
                                'prefix': run['prefix'],
                                'two_theta': run['two_theta'],
                                'directory': run['directory']
                            }
                            self.run_list.append(list_item)
                            index += 1
                remaining_frames -= current_slice
        self.pos = 0
        self.gen_sequence()
                                                                        
    def gen_sequence(self):
        self.listmodel.clear()
        for item in self.run_list:
            self.__add_item(item)
    
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
        self.pos = model.get_path(pos)[0]             
        while iter:
            i = model.get_path(iter)[0]
            if i < self.pos:
                model.set(iter, COLLECT_COLUMN_SAVED, True)
                self.run_list[i]['saved'] = True
            else:
                model.set(iter, COLLECT_COLUMN_SAVED, False)
                self.run_list[i]['saved'] = False
            iter = model.iter_next(iter)
            
        if self.collect_state == COLLECT_STATE_PAUSED:
            print 'Resetting position to', self.pos + 1
            self.collector.set_position( self.pos )
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
            self.collect_btn.set_label('cm-resume')
            self.collect_state = COLLECT_STATE_PAUSED
            self.progress_bar.idle_text("Paused")
            self.collect_btn.set_sensitive(True)
        else:
            self.collect_btn.set_label('cm-pause')   
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
        self.collect_btn.set_label('cm-collect')
        self.stop_btn.set_sensitive(False)
        self.run_manager.set_sensitive(True)
        self.image_viewer.set_collect_mode(False)
        self.progress_bar.idle_text("Stopped")
    
    def on_complete(self, widget=None):
        self.collect_state = COLLECT_STATE_IDLE
        self.collect_btn.set_label('cm-collect')
        self.stop_btn.set_sensitive(False)
        self.run_manager.set_sensitive(True)
        self.image_viewer.set_collect_mode(False)
        self.progress_bar.idle_text("Stopped")
        try:
            os.spawnvpe(os.P_NOWAIT, "festival", "festival", ['--tts','/users/cmcfadmin/tts/data_done'], os.environ)
        except:
            pass

    def on_new_image(self, widget, index, filename):
        self.pos = index
        self.set_row_state(index, saved=True)
        self.image_viewer.show_detector_image(filename)
      

    def on_progress(self, obj, fraction, position):
        if position == 1:
            self.start_time = time.time()
        elapsed_time = time.time() - self.start_time
        time_unit = elapsed_time / fraction
        eta_time = time_unit * (1 - fraction)
        percent = fraction * 100
        if position > 0:
            frame_time = elapsed_time / position
            text = "ETA %s [%0.1f s/frame]" % (time.strftime('%H:%M:%S',time.gmtime(eta_time)), frame_time)
        else:
            text = "Total Time: %s " % (time.strftime('%H:%M:%S',time.gmtime(elapsed_time)))
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
                self.collector.setup(self.run_list, skip_collected=True)
                self.collector.start()
                self.collect_state = COLLECT_STATE_RUNNING
                self.collect_btn.set_label('cm-pause')
                self.stop_btn.set_sensitive(True)
                self.run_manager.set_sensitive(False)
                self.image_viewer.set_collect_mode(True)
        return            

    def stop(self):
        if self.collector is not None:
            self.collector.stop()
    

                                                                                                                                                                                    
if __name__ == "__main__":
   
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_default_size(300,400)
    win.set_border_width(2)
    win.set_title("CollectManager Widget Demo")

    example = CollectManager()

    win.add(example)
    win.show_all()

    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()
        
