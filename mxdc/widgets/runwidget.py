import gtk
import gtk.glade
import gobject
import sys, os
from twisted.python.components import globalRegistry
from bcm.beamline.mx import IBeamline
from mxdc.widgets.predictor import Predictor
from mxdc.widgets.dialogs import warning, check_folder, DirectoryButton


(
  COLUMN_LABEL,
  COLUMN_ENERGY,
  COLUMN_EDITABLE,
  COLUMN_CHANGED
) = range(4)

DEFAULT_PARAMETERS = {
    'prefix': 'test',
    'directory': os.environ['HOME'],
    'distance': 250.0,
    'delta': 1.0,
    'time': 1.0,
    'start_angle': 0,
    'total_angle': 1.0,
    'start_frame': 1,
    'total_frames': 1,
    'inverse_beam': False,
    'wedge': 360.0,
    'energy': [ 12.658 ],
    'energy_label': ['E0'],
    'number': 1,
    'two_theta': 0.0,
}


class RunWidget(gtk.Frame):
    def __init__(self, num=0):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(os.path.join(os.path.dirname(__file__), 'data/run_widget.glade'), 
                                  'run_widget')
        
        self.title = self._xml.get_widget('run_title')
        self.vbox = self._xml.get_widget('run_widget')
        self.add(self.vbox)

        self.save_btn = self._xml.get_widget('save_btn')
        self.reset_btn = self._xml.get_widget('reset_btn')
        self.enable_btn = self._xml.get_widget('activate_btn')
        self.delete_btn = self._xml.get_widget('delete_btn')
        self.layout_table = self._xml.get_widget('layout_table')
        self.reset_btn.connect('clicked', self.on_reset_parameters)
        self.entry = {}
                
        # Data for entries (name: (col, row, length, [unit]))
        entries = ['prefix', 'distance','delta','time','start_frame', 
                   'start_angle','total_frames','total_angle','wedge',
                   'two_theta','inverse_beam']
        for e in entries:
            self.entry[e] = self._xml.get_widget(e)
            if isinstance(self.entry[e], gtk.Entry) and e not in ['prefix',]:
                self.entry[e].set_alignment(1)
        
        
        # Set directory field non-editable, must use directory selector
        self.entry['directory'] = DirectoryButton()
        self.layout_table.attach(self.entry['directory'], 1,4,1,2, xoptions=gtk.EXPAND|gtk.FILL)

        # entry signals
        self.entry['prefix'].connect('focus-out-event', self.on_prefix_changed)
        self.entry['directory'].connect('focus-out-event', self.on_directory_changed)
        self.entry['start_angle'].connect('focus-out-event', self.on_start_angle_changed)
        self.entry['delta'].connect('focus-out-event', self.on_delta_changed)
        self.entry['total_angle'].connect('focus-out-event', self.on_total_angle_changed)
        self.entry['total_frames'].connect('focus-out-event', self.on_total_frames_changed)
        self.entry['start_frame'].connect('focus-out-event', self.on_start_frame_changed)
        self.entry['distance'].connect('focus-out-event', self.on_distance_changed)
        self.entry['time'].connect('focus-out-event', self.on_time_changed)
        self.entry['wedge'].connect('focus-out-event', self.on_wedge_changed)
        self.entry['two_theta'].connect('focus-out-event', self.on_two_theta_changed)
        
        self.entry['prefix'].connect('activate', self.on_prefix_changed)
        self.entry['start_angle'].connect('activate', self.on_start_angle_changed)
        self.entry['delta'].connect('activate', self.on_delta_changed)
        self.entry['total_angle'].connect('activate', self.on_total_angle_changed)
        self.entry['total_frames'].connect('activate', self.on_total_frames_changed)
        self.entry['start_frame'].connect('activate', self.on_start_frame_changed)
        self.entry['distance'].connect('activate', self.on_distance_changed)
        self.entry['time'].connect('activate', self.on_time_changed)
        self.entry['wedge'].connect('activate', self.on_wedge_changed)
        self.entry['two_theta'].connect('activate', self.on_two_theta_changed)
               
        # Energy
        self.sw = self._xml.get_widget('energy_view')
        self.energy_store = gtk.ListStore(
            gobject.TYPE_STRING,
            gobject.TYPE_FLOAT,
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_BOOLEAN
        )
        self.energy_list = gtk.TreeView(model=self.energy_store)
        self.energy_list.connect('focus-out-event', lambda x, y: self.check_changes())
        self.energy_list.set_rules_hint(True)
        self.sw.add(self.energy_list)
        
        
        #Label column
        renderer = gtk.CellRendererText()
        renderer.set_data('column',COLUMN_LABEL)
        renderer.connect("edited", self.on_energy_edited, self.energy_store)
        column1 = gtk.TreeViewColumn('Label', renderer, text=COLUMN_LABEL, editable=COLUMN_EDITABLE)
        column1.set_cell_data_func(renderer, self._cell_format, COLUMN_LABEL)
        column1.set_fixed_width(5)

        #Energy column
        renderer = gtk.CellRendererText()
        renderer.set_data('column',COLUMN_ENERGY)
        renderer.connect("edited", self.on_energy_edited, self.energy_store)
        column2 = gtk.TreeViewColumn('Energy', renderer, text=COLUMN_ENERGY, editable=COLUMN_EDITABLE)
        column2.set_cell_data_func(renderer, self._cell_format, COLUMN_ENERGY)
        column2.set_fixed_width(10)
        
        self.energy_list.append_column(column1)
        self.energy_list.append_column(column2)
        
        # buttons for adding and removing energy
        self.energy_btn_box = gtk.VBox(True,0)
        self.add_e_btn = gtk.ToolButton('gtk-add')
        self.add_e_btn.connect("clicked", self.on_add_energy_clicked)
        self.energy_btn_box.pack_start(self.add_e_btn, expand=False, fill=False)

        self.del_e_btn = gtk.ToolButton('gtk-remove')
        self.del_e_btn.connect("clicked", self.on_remove_energy_clicked)
        self.energy_btn_box.pack_start(self.del_e_btn, expand=False, fill=False)
        self.layout_table.attach(self.energy_btn_box, 3, 4, 11,12)
        self.predictor = None

        # connect signals
        self.save_btn.connect('clicked', self.on_save)
        self.show_all()
        self.set_no_show_all(True)
        
        #initialize parameters
        self.parameters = DEFAULT_PARAMETERS
        self.set_number(num)
        self.set_parameters(self.parameters)
        self.parameters = self.get_parameters()

        self._changes_pending = False
                
    def __add_energy(self, item=None): 
        model = self.energy_store
        iter = model.get_iter_first()
        _e_names = []
        if item==None:
            while iter:
                _e_names.append(model.get_value(iter, COLUMN_LABEL))
                iter = model.iter_next(iter)
            index = len(_e_names)
            name = "E%d" % (index)
            while name in _e_names:
                index += 1
                name = "E%d" % (index)
            #try to get value from beamline if one is registered
            try:
                beamline = globalRegistry.lookup([], IBeamline)
                _e_value = beamline.monochromator.energy.get_position()
            except:
                _e_value = 12.6580

            item = [name, _e_value, True, True]
            
        iter = self.energy_store.append()
        self.energy_store.set(iter, 
            COLUMN_LABEL, item[COLUMN_LABEL], 
            COLUMN_ENERGY, item[COLUMN_ENERGY],
            COLUMN_EDITABLE, item[COLUMN_EDITABLE],
            COLUMN_CHANGED, item[COLUMN_CHANGED]
        )
        
    def _cell_format(self, cell, renderer, model, iter, column):
        if column == COLUMN_ENERGY:
            value = model.get_value(iter, column)
            renderer.set_property('text', '%0.4f' % value)
        value2 = model.get_value(iter, COLUMN_CHANGED)
        if value2:
            renderer.set_property("foreground", '#cc0000')
        else:
            renderer.set_property("foreground", None)
        return
        
    
    def _set_energy_changed(self, state=False):
        model = self.energy_list.get_model()
        iter = model.get_iter_first()
        while iter:
            model.set(iter, COLUMN_CHANGED, state)
            iter = model.iter_next(iter)
            
    def on_energy_edited(self, cell, path_string, new_text, model):
        iter = model.get_iter_from_string(path_string)
        path = model.get_path(iter)[0]
        column = cell.get_data("column")

        if column == COLUMN_ENERGY:
            model.set(iter, column, float(new_text))
        elif column == COLUMN_LABEL:
            model.set(iter, column, new_text)
            
    def __reset_e_btn_states(self):
        size = len(self.energy_store)
        if size > 1:
            self.del_e_btn.set_sensitive(True)
            if size > 4:
                self.add_e_btn.set_sensitive(False)
            else:
                self.add_e_btn.set_sensitive(True)
        else:
            self.del_e_btn.set_sensitive(False)
            self.add_e_btn.set_sensitive(True)
                       

    def on_add_energy_clicked(self, button):
        if len(self.energy_list.get_model()) < 5:
            self.__add_energy()
        self.__reset_e_btn_states()

    def on_remove_energy_clicked(self, button):
        if len(self.energy_list.get_model()) > 1:
            selection = self.energy_list.get_selection()
            model, iter = selection.get_selected()
            if iter:
                path = model.get_path(iter)[0]
                model.remove(iter)
        self.__reset_e_btn_states()
            
    def set_parameters(self, dict):
        for key in  ['distance','delta','start_angle','total_angle','wedge','time', 'two_theta']:
            if dict.has_key(key):
                self.entry[key].set_text("%0.2f" % dict[key])
            else:
                self.entry[key].set_text("%0.2f" % DEFAULT_PARAMETERS[key])
        for key in ['start_frame', 'total_frames']:
            if dict.has_key(key):
                self.entry[key].set_text("%d" % dict[key])
            else:
                self.entry[key].set_text("%d" % DEFAULT_PARAMETERS[key])
        self.entry['prefix'].set_text("%s" % dict['prefix'])
        if dict['directory'] is not None and os.path.exists(dict['directory']):
            self.entry['directory'].set_filename("%s" % dict['directory'])
        else:
            self.entry['directory'].set_filename(os.environ['HOME'])
    
        self.set_number(dict['number'])
        self.entry['inverse_beam'].set_active(dict['inverse_beam'])
        self.energy_store.clear()
        
        for i in range(len(dict['energy'])):
            self.__add_energy([dict['energy_label'][i], dict['energy'][i], True, False] )
        self.__reset_e_btn_states()
        self.check_changes()
        
    def get_parameters(self):
        run_data = {}
        run_data['prefix']      = self.entry['prefix'].get_text().strip()
        run_data['directory']   = self.entry['directory'].get_filename()
        energy = []
        energy_label = []
        model = self.energy_list.get_model()
        iter = model.get_iter_first()
        while iter:
            energy.append(model.get_value(iter, COLUMN_ENERGY))
            energy_label.append(model.get_value(iter, COLUMN_LABEL))
            iter = model.iter_next(iter)
        
        run_data['energy']  =    energy
        run_data['energy_label'] = energy_label
        run_data['inverse_beam'] = self.entry['inverse_beam'].get_active()
        run_data['number'] = self.number

        for key in ['distance','delta','start_angle','total_angle','wedge','time', 'two_theta']:
            run_data[key] = float(self.entry[key].get_text())

        for key in ['start_frame','total_frames']:
            run_data[key] = int(self.entry[key].get_text())
        return run_data
                
    def is_enabled(self):
        return self.enable_btn.get_active()
    
    def disable_run(self):
        self.enable_btn.set_active(False)
    
    def enable_run(self):
        self.enable_btn.set_active(True)       

    def set_number(self, num=0):
        self.number = num
        self.parameters['number'] = num
        self.title.set_text('<big><b>Run %d</b></big>' % self.number)
        self.title.set_use_markup(True)
        # Hide controls for Run 0
        if num == 0:
            for key in ['total_angle','total_frames','wedge','inverse_beam']:
                self.entry[key].set_sensitive(False)
            self.energy_btn_box.hide()
            self.energy_list.set_sensitive(False)
            self.sw.hide()    
            self.delete_btn.set_sensitive(False)
            if self.predictor is None:    
                #add Predictor
                self.predictor = Predictor()
                self.predictor.set_size_request(200,200)
                self.vbox.pack_end( self.predictor, expand=False, fill=False)
    
        
    def check_changes(self):
        new_values = self.get_parameters()
        if self.predictor is not None and self.number == 0:
            self.predictor.configure(distance=new_values['distance'], 
                                     energy=new_values['energy'][0],
                                     two_theta=new_values['two_theta'])
        
        keys = new_values.keys()
        keys.remove('energy_label')
        for key in keys:
            if key == 'energy':
                widget = None
                _energy_changed = False
                if len(new_values['energy']) != len(self.parameters['energy']):
                    _energy_changed = True
                else:
                    for i in range(len(new_values['energy'])):
                        if ((abs(new_values['energy'][i] - self.parameters['energy'][i]) > 0.0001) or
                            (new_values['energy_label'][i] != self.parameters['energy_label'][i])):
                            _energy_changed = True
                self._changes_pending = True
                self._set_energy_changed(_energy_changed)
                self.energy_list.get_selection().unselect_all()                                  
            elif key == 'number':
                widget = self.title
            elif key == 'directory':
                widget = self.entry['directory']
            else:
                widget = self.entry[key]
            
            if widget is None:
                continue
            if new_values[key] != self.parameters[key]:
                widget.modify_text(gtk.STATE_NORMAL, gtk.gdk.color_parse("red"))
                widget.modify_fg(gtk.STATE_NORMAL, gtk.gdk.color_parse("red"))
                self._changes_pending = True
            else:
                widget.modify_text(gtk.STATE_NORMAL, None)
                widget.modify_fg(gtk.STATE_NORMAL, None)
                self._changes_pending = False
        

    def on_prefix_changed(self, widget, event=None):
        prefix = self.entry['prefix'].get_text()
        for c in [' ','*','#','@','&','[','[']:   
            prefix = prefix.replace(c,'')
        self.entry['prefix'].set_text(prefix)
        self.check_changes()
        return False
    

    def on_start_angle_changed(self,widget,event=None):
        try:
            start_angle = float(self.entry['start_angle'].get_text())
        except:
            start_angle = 0
        
        start_angle = min(360.0, max(-360.0, start_angle))    
        self.entry['start_angle'].set_text('%0.2f' % start_angle)            
        self.check_changes()
        return False
    
    def on_total_angle_changed(self,widget,event=None):
        start_angle = float(self.entry['start_angle'].get_text())    
        start_frame = int(self.entry['start_frame'].get_text())
        delta = float(self.entry['delta'].get_text())
        try:
            total_angle = float(self.entry['total_angle'].get_text())
            total_frames = int(total_angle / delta)
        except:
            total_frames = int(self.entry['total_frames'].get_text())
            total_angle = total_frames * delta 

        self.entry['total_angle'].set_text('%0.2f' % total_angle)                       
        self.entry['total_frames'].set_text('%d' % total_frames)
        self.check_changes()
        return False

    def on_delta_changed(self,widget,event=None):
        try:
            delta = float(self.entry['delta'].get_text())
        except:
            delta = 1.0
        delta = min(10.0, max(delta, 0.1))

        self.entry['delta'].set_text('%0.2f' % delta)
        total_angle = float(self.entry['total_angle'].get_text())
        total_frames = int(self.entry['total_frames'].get_text())

        if self.number == 0:
            total_angle = delta
            self.entry['total_angle'].set_text('%0.2f' % total_angle)
        total_frames = int(total_angle/delta)
        self.entry['total_frames'].set_text('%d' % total_frames)
        self.check_changes()
        return False

    def on_time_changed(self,widget,event=None):
        try:
            delta = float(self.entry['delta'].get_text())
            time = float(self.entry['time'].get_text())
        except:
            time = 1.0
        time = max(0.5, time)
        self.entry['time'].set_text('%0.1f' % time)
        self.check_changes()
        return False

    def on_start_frame_changed(self,widget,event=None):
        start_angle = float(self.entry['start_angle'].get_text())
        try:
            start_frame = int( float(self.entry['start_frame'].get_text()) )
        except:
            start_frame = 1
        
        start_frame = max(start_frame, 1)
        self.entry['start_frame'].set_text('%d' % start_frame)
        self.check_changes()
        return False

    def on_total_frames_changed(self,widget,event=None):
        delta = float(self.entry['delta'].get_text())
        try:
            total_frames = float(self.entry['total_frames'].get_text() )
            total_angle = total_frames * delta 
        except:
            total_angle = float(self.entry['total_angle'].get_text())
            total_frames = int(total_angle / delta)
        
        self.entry['total_frames'].set_text('%d' % total_frames)    
        self.entry['total_angle'].set_text('%0.2f' % total_angle)
        self.check_changes()
        return False

    def on_wedge_changed(self,widget,event=None):
        try:
            wedge = float(self.entry['wedge'].get_text())    
        except:
            wedge = 360.0
        wedge = min(max(1, wedge), 360.0)
        self.entry['wedge'].set_text('%0.2f' % wedge) 
        self.check_changes()
        return False

    def on_two_theta_changed(self,widget,event=None):
        distance = float(self.entry['distance'].get_text())    
        try:
            two_theta = float(self.entry['two_theta'].get_text())    
        except:
            two_theta = 0.0

        if distance <= 170.0:
            tt_max = (14.0/70.0) * (distance - 100.0) + 20.0
        elif distance <= 850 :
            tt_max = (-16.0/680.0) * (distance - 170.0) + 34.0
        else:
            tt_max = 0.0

        two_theta = max(0.0, min(tt_max, two_theta))
        self.entry['two_theta'].set_text('%0.2f' % two_theta) 
        self.check_changes()
        return False

    def on_distance_changed(self,widget,event=None):
        two_theta = float(self.entry['two_theta'].get_text())    
        try:
            distance = float(self.entry['distance'].get_text())
        except:
            distance = 250.0

        if two_theta <= 20.0:
            d_min = 100.0
        elif two_theta <= 34.0:
            d_min = (70.0/14.0) * (two_theta - 20.0) + 100.0
        else:
            d_min = 100.0

        if two_theta == 0:
            d_max = 1000.0
        elif two_theta <= 18.0:
            d_max = 850.0
        elif two_theta <= 34.0:
            d_max = (680/-16.0) * (two_theta - 18.0) + 850.0
        else:
            d_max = 1000.0

        distance = max(d_min, min(distance, d_max))
          
        self.entry['distance'].set_text('%0.1f' % distance)
        self.check_changes()
        return False
        
    def on_directory_changed(self,widget=None, event=None):
        directory = self.entry['directory'].get_filename()
        self.check_changes()
        return False        

    def on_save(self, widget):
        self.enable_btn.set_active(True)
        self.parameters = self.get_parameters()
        self.check_changes()
        return True

    def on_reset_parameters(self, obj):
        try:
            beamline = globalRegistry.lookup([], IBeamline)      
            params = self.get_parameters()
            params['distance'] = beamline.diffractometer.distance.get_position()
            params['two_theta'] = beamline.diffractometer.two_theta.get_position()
            params['start_angle'] = beamline.goniometer.omega.get_position()
            params['energy'] = [ beamline.monochromator.energy.get_position() ]
            params['energy_label'] = ['E0']
            self.set_parameters(params)
            self.check_changes()
        except:
            self.reset_btn.set_sensitive(False)
        return True  
        
