#!/usr/bin/env python
import gtk, gobject
import sys, os, time
from RunManager import RunManager
from ImgViewer import ImgViewer
from DataCollector import DataCollector as DataCollector
from Beamline import beamline
from ActiveWidgets import ActiveLabel
from ConfigParser import ConfigParser
from LogServer import LogServer
from configobj import ConfigObj
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
    def __init__(self):
        gtk.HBox.__init__(self,False,6)
        self.__register_icons()
        self.run_data = {}
        self.labels = {}
        self.run_list = []
        self.image_viewer = ImgViewer()
        self.run_manager = RunManager()
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
        self.progress_bar = gtk.ProgressBar()
        self.progress_bar.set_fraction(0)
        self.progress_bar.set_text('0%')
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
            'omega':      ('Angle:', 0, 0, 'deg'),
            'detector_2th':   ('Two Theta:',0, 1, 'deg'),
            'detector_dist':    ('Distance:',0, 2, 'mm'),
            'energy':    ('Energy:',0, 3, 'keV')
        }
        
        for (key,val) in zip(items.keys(),items.values()):
            label = gtk.Label(val[0])
            label.set_alignment(1,0.5)
            pos_table.attach( label, val[1], val[1]+1, val[2], val[2]+1)
            pos_table.attach(gtk.Label(val[3]), 2, 3, val[2], val[2]+1)
            pos_label = ActiveLabel( beamline['motors'][key], format="%8.4f" )
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
        self.collector = None
        self.set_border_width(6)
        self.__load_config()
        

    def __load_config(self):
        config_file = os.environ['HOME'] + '/.mxdc/run_config.dat'
        if os.access(config_file, os.R_OK):
            data = {}
            config = ConfigObj(config_file, options={'unrepr':True})
            for section in config.keys():
                run = int(section)
                data[run] = config[section]
                self.add_run(data[run])
        self.apply_run(save=False)

    def __save_config(self):
        config = ConfigObj()
        config.unrepr = True
        config_file = os.environ['HOME'] + '/.mxdc/run_config.dat'
        config_dir = os.environ['HOME'] + '/.mxdc'
        if os.access(config_dir,os.W_OK):
            config.filename = config_file
            for key in self.run_data.keys():
                data = self.run_data[key]
                keystr = "%s" % key
                config[keystr] = data
            config.write()

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
        
        
    def apply_run(self, save=True):
        for run in self.run_manager.runs:
            data = run.get_parameters()
            if check_folder(data['directory']):
                self.run_data[ data['number'] ] = data
            else:
                return
        if save:
            self.__save_config()
        self.create_runlist()
        
    def add_run(self, data):
        self.run_manager.add_new_run(data)
            
    
    def remove_run(self, index):
        if index in self.run_data.keys():
            del self.run_data[index]
        self.create_runlist()
    
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
        else:
            run_keys = run_data.keys()
            
        self.run_list = []
        index = 0
        for pos in run_keys:
            run = run_data[pos]
            offsets = run['inverse_beam'] and [0, 180] or [0,]
            angle_range = run['end_angle'] - run['start_angle']
            wedge = ( run['wedge'] < angle_range and run['wedge'] or angle_range )
            passes = int ( round( angle_range  /  wedge ) )
            wedge_size = int( (wedge) / run['delta'])
            for i in range(passes):
                for (energy,energy_label) in zip(run['energy'],run['energy_label']):
                    for offset in offsets:
                        for j in range(wedge_size):
                            angle = run['start_angle'] + (j * run['delta']) + (i * wedge) + offset
                            frame_number =  i * wedge_size + j + int(offset/run['delta']) + 1
                            file_name = "%s/%s_%d_%s_%04d.img" % (run['directory'], run['prefix'], 
                                run['number'], energy_label, frame_number)
                            frame_name = "%s_%d_%s_%04d" % (run['prefix'], run['number'], energy_label, frame_number)
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
                                'prefix': run['prefix']
                            }
                            self.run_list.append(list_item)
                            index += 1
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
            if os.path.exists(frame['file_name']):
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
                    old_name = self.run_list[index]['file_name']
                    new_name = old_name + '.bk'
                    LogServer.log("Renaming existing file '%s' to '%s'" % (old_name, new_name)) 
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
        else:
            self.collect_btn.set_label('cm-pause')    
            self.collect_state = COLLECT_STATE_RUNNING

    def on_activate(self, widget):
        if self.collect_state == COLLECT_STATE_IDLE:
            self.start_collection()
        elif self.collect_state == COLLECT_STATE_RUNNING:
            self.collector.pause()  
        elif self.collect_state == COLLECT_STATE_PAUSED:
            self.collector.resume()
    

    def on_stop_btn_clicked(self,widget):
        self.collector.stop()
        
    def on_stop(self, widget=None):
        self.collect_state = COLLECT_STATE_IDLE
        self.collect_btn.set_label('cm-collect')
        self.stop_btn.set_sensitive(False)
        self.run_manager.set_sensitive(True)
        self.image_viewer.set_collect_mode(False)
    
    def on_new_image(self, widget, index, filename):
        self.pos = index
        self.set_row_state(index, saved=True)
        self.image_viewer.show_detector_image(filename)
      

    def on_progress(self, widget, fraction):
        elapsed_time = time.time() - self.start_time
        time_unit = elapsed_time / fraction
        eta_time = time_unit * (1 - fraction)
        percent = fraction * 100
        text = "%4.1f%s  ETA: %s" % (percent,'%',time.strftime('%H:%M:%S',time.gmtime(eta_time)))
        self.progress_bar.set_fraction(fraction)
        self.progress_bar.set_text(text)
                
    def update_values(self,dict):        
        for key in dict.keys():
            self.labels[key].set_text(dict[key])

    def start_collection(self):
        self.start_time = time.time()
        self.create_runlist()
        if self.check_runlist():
            self.collector = DataCollector(self.run_list, skip_collected=True)
            self.collector.connect('done', self.on_stop)
            self.collector.connect('paused',self.on_pause)
            self.collector.connect('new-image', self.on_new_image)
            self.collector.connect('stopped', self.on_stop)
            self.collector.connect('progress', self.on_progress)
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
        
