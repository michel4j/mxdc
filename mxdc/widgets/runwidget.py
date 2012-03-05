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
    'name': 'test',
    'directory': os.environ['HOME'],
    'distance': 250.0,
    'delta_angle': 1.0,
    'exposure_time': 1.0,
    'start_angle': 0,
    'total_angle': 180.0,
    'first_frame': 1,
    'num_frames': 180,
    'inverse_beam': False,
    'wedge': 360.0,
    'energy': [ 12.658 ],
    'energy_label': ['E0'],
    'attenuation': 0.0,
    'number': 1,
    'two_theta': 0.0,
    'skip': '',
    'crystal_id': None,
    'experiment_id': None,
    'comments': '',
    'scattering_factors': None,
}


class RunWidget(gtk.Frame):
    def __init__(self, num=0):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(os.path.join(os.path.dirname(__file__), 'data/run_widget.glade'), 
                                  'run_widget')
        
        self.add(self.run_widget)
        self.update_btn.connect('clicked', self.on_update_parameters)
        self.reset_btn.connect('clicked', self.on_reset_parameters)
        self.entry = {}
                
        # Data for entries (name: (col, row, length, [unit]))
        entries = ['name', 'distance','delta_angle','exposure_time','first_frame', 
                   'start_angle','num_frames','total_angle','wedge',
                   'attenuation','inverse_beam','skip']
        for e in entries:
            self.entry[e] = self._xml.get_widget(e)
            if isinstance(self.entry[e], gtk.Entry) and e not in ['name',]:
                self.entry[e].set_alignment(1)
        
        
        # Set directory field non-editable, must use directory selector
        self.entry['directory'] = self.directory_btn 
        
        #self.entry['directory'] = DirectoryButton()
        #self.layout_table.attach(self.entry['directory'], 1,4,1,2, xoptions=gtk.EXPAND|gtk.FILL)

        # entry signals
        self.entry['name'].connect('focus-out-event', self.on_prefix_changed)
        self.entry['directory'].connect('focus-out-event', self.on_directory_changed)
        self.entry['start_angle'].connect('focus-out-event', self.on_start_angle_changed)
        self.entry['delta_angle'].connect('focus-out-event', self.on_delta_changed)
        self.entry['total_angle'].connect('focus-out-event', self.on_total_angle_changed)
        self.entry['num_frames'].connect('focus-out-event', self.on_total_frames_changed)
        self.entry['first_frame'].connect('focus-out-event', self.on_start_frame_changed)
        self.entry['distance'].connect('focus-out-event', self.on_distance_changed)
        self.entry['exposure_time'].connect('focus-out-event', self.on_time_changed)
        self.entry['wedge'].connect('focus-out-event', self.on_wedge_changed)
        self.entry['attenuation'].connect('focus-out-event', self.on_attenuation_changed)
        self.entry['skip'].connect('focus-out-event', self.on_skip_changed)
        
        self.entry['name'].connect('activate', self.on_prefix_changed)
        self.entry['start_angle'].connect('activate', self.on_start_angle_changed)
        self.entry['delta_angle'].connect('activate', self.on_delta_changed)
        self.entry['total_angle'].connect('activate', self.on_total_angle_changed)
        self.entry['num_frames'].connect('activate', self.on_total_frames_changed)
        self.entry['first_frame'].connect('activate', self.on_start_frame_changed)
        self.entry['distance'].connect('activate', self.on_distance_changed)
        self.entry['exposure_time'].connect('activate', self.on_time_changed)
        self.entry['wedge'].connect('activate', self.on_wedge_changed)
        self.entry['attenuation'].connect('activate', self.on_attenuation_changed)
        self.entry['skip'].connect('activate', self.on_skip_changed)
               
        # Energy
        self.energy_store = gtk.ListStore(
            gobject.TYPE_STRING,
            gobject.TYPE_FLOAT,
            gobject.TYPE_BOOLEAN,
            gobject.TYPE_BOOLEAN
        )
        self.energy_list = gtk.TreeView(model=self.energy_store)
        self.energy_list.connect('focus-out-event', lambda x, y: self.check_changes())
        self.energy_list.set_rules_hint(True)
        self.energy_view.add(self.energy_list)
        
        
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
        self.add_e_btn.connect("clicked", self.on_add_energy_clicked)
        self.del_e_btn.connect("clicked", self.on_remove_energy_clicked)
        self.predictor = None

        # connect signals
        self.save_btn.connect('clicked', self.on_save)
        self.show_all()
        self.set_no_show_all(True)
        
        #initialize parameters
        self.parameters = {}
        self.parameters.update(DEFAULT_PARAMETERS)
        self.set_number(num)
        self.set_parameters(self.parameters)
        
        # active database
        self.active_sample = {}
        self.active_strategy = {}

        self._changes_pending = False
                
    def __getattr__(self, key):
        try:
            return super(RunWidget).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

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
            renderer.set_property("foreground", '#cc00cc')
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
                model.remove(iter)
        self.__reset_e_btn_states()
            
    def set_parameters(self, dict):
        for key in  ['distance','delta_angle','start_angle','total_angle','wedge','exposure_time', 'attenuation']:
            if key in dict:
                self.entry[key].set_text("%0.2f" % dict[key])
            else:
                self.entry[key].set_text("%0.2f" % DEFAULT_PARAMETERS[key])
        for key in ['first_frame', 'num_frames']:
            if key in dict:
                self.entry[key].set_text("%d" % dict[key])
            else:
                self.entry[key].set_text("%d" % DEFAULT_PARAMETERS[key])
        if 'total_angle' in dict:
            self.entry['num_frames'].set_text('%d' % int(dict['total_angle']/dict['delta_angle']))
            
        if 'name' in dict:
            self.entry['name'].set_text("%s" % dict['name'])
        if dict.get('directory') is not None and os.path.exists(dict['directory']):
            self.entry['directory'].set_current_folder("%s" % dict['directory'])
        else:
            #self.entry['directory'].set_current_folder(os.environ['HOME'])
            dict['directory'] = os.environ['HOME']
        
        # always display up to date active crystal
        if self.active_sample:
            txt = '%s [ID:%s]' %(self.active_sample['name'], self.active_sample['id'])
            self.crystal_entry.set_text(txt)
        elif  dict.get('crystal_id'):                                                                          
            txt = '[ID:%s]' % (dict['crystal_id'])
            self.crystal_entry.set_text(txt)
        else:
            self.crystal_entry.set_text('[ Unknown ]')
            
        self.set_number(dict['number'])
        self.entry['inverse_beam'].set_active(dict['inverse_beam'])
        self.energy_store.clear()
        
        for i in range(len(dict['energy'])):
            self.__add_energy([dict['energy_label'][i], dict['energy'][i], True, False] )
        self.__reset_e_btn_states()
        self.entry['skip'].set_text(dict.get('skip',''))
      
        _cmt_buf =  self.comments_entry.get_buffer()
        _cmt_buf.set_text(dict.get('comments', ''))
        
        self.parameters.update(dict)
        self.check_changes()
        
    def get_parameters(self):
        run_data = self.parameters.copy()
                
        run_data['name']      = self.entry['name'].get_text().strip()
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
            
        for key in ['distance','delta_angle','start_angle','total_angle', 'wedge', 'exposure_time', 'attenuation', 'num_frames']:
            run_data[key] = float(self.entry[key].get_text())

        for key in ['first_frame','num_frames']:
            run_data[key] = int(self.entry[key].get_text())
        
        for key in ['skip']:
            run_data[key] = self.entry[key].get_text()
        _cmt_buf =  self.comments_entry.get_buffer()           
        run_data['comments'] = _cmt_buf.get_text(_cmt_buf.get_start_iter(), _cmt_buf.get_end_iter())
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
        self.run_title.set_text('<big><b>Run %d</b></big>' % self.number)
        self.run_title.set_use_markup(True)
        # Hide controls for Run 0
        if num == 0:
#            for key in ['total_angle','num_frames','wedge','inverse_beam', 'skip']:
#                self.entry[key].set_sensitive(False)
            self.energy_btn_box.hide()
            self.energy_list.set_sensitive(False)
            self.comments_frame.hide()
            self.energy_view.hide()    
            self.delete_btn.set_sensitive(False)
            if self.predictor is None:    
                #add Predictor
                try:
                    beamline = globalRegistry.lookup([], IBeamline)      
                    self.predictor = Predictor(beamline.detector.resolution, 
                                   beamline.detector.size)
                except:
                    self.predictor = Predictor()
                self.predictor.set_size_request(200,200)
                self.predictor.set_border_width(12)
                self.run_widget.pack_end( self.predictor, expand=True, fill=True)
    
    def update_active_data(self, sample=None, strategy=None):
        if sample is not None:
            self.active_sample = sample
            params = self.get_parameters()
            params['crystal_id'] = self.active_sample.get('id', None)
            params['experiment_id'] = self.active_sample.get('experiment_id', None)
            if self.active_sample.get('comments') is not None:
                params['comments'] = self.active_sample['comments']
            else:
                params['comments'] = ''
            self.set_parameters(params)
            self.check_changes()
            
        if strategy is not None:
            self.active_strategy = strategy
        
    def check_changes(self):
        new_values = self.get_parameters()
        if self.predictor is not None and self.number == 0:
            beamline = globalRegistry.lookup([], IBeamline)
            self.predictor.configure(distance=new_values['distance'], 
                                     energy=beamline.energy.get_position(),
                                     two_theta=new_values['two_theta'])

        for key in self.parameters.keys():
            # skip some keys 
            if key in ['energy_label', 'crystal_id', 'experiment_id', 'comments', 'two_theta', 'scattering_factors']:
                continue
            
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
                #self.energy_list.get_selection().unselect_all()                                  
            elif key == 'number':
                widget = self.run_title
            elif key == 'directory':
                widget = self.entry['directory']
            else:
                widget = self.entry[key]
            
            if widget is None:
                continue
            if new_values[key] != self.parameters.get(key):
                widget.modify_text(gtk.STATE_NORMAL, gtk.gdk.color_parse("magenta"))
                widget.modify_fg(gtk.STATE_NORMAL, gtk.gdk.color_parse("magenta"))
                self._changes_pending = True
            else:
                widget.modify_text(gtk.STATE_NORMAL, None)
                widget.modify_fg(gtk.STATE_NORMAL, None)
                self._changes_pending = False
        

    def on_prefix_changed(self, widget, event=None):
        prefix = self.entry['name'].get_text()
        for c in [' ','*','#','@','&','[','[']:   
            prefix = prefix.replace(c,'')
        self.entry['name'].set_text(prefix)
        self.check_changes()
        return False
    

    def on_start_angle_changed(self,widget,event=None):
        try:
            start_angle = float(self.entry['start_angle'].get_text())
        except:
            start_angle = 0
        
        start_angle = min(360.0, max(-360.0, start_angle))
        if start_angle < 0:
            start_angle += 360.0  
        self.entry['start_angle'].set_text('%0.2f' % start_angle)            
        self.check_changes()
        return False

    def on_skip_changed(self,widget,event=None):
        try:
            skip = self.entry['skip'].get_text()
        except:
            skip = ''
        skip_list = []
        for w in skip.split(','):
            try:
                wi = map(int, w.split('-'))
                if len(wi) == 1:
                    skip_list.append('%d' % wi[0])
                elif len(wi) == 2:
                    skip_list.append('%d-%d' % (wi[0], wi[1]))
            except:
                pass
        
        skip = ','.join(skip_list)
        self.entry['skip'].set_text(skip)            
        self.check_changes()
        return False
    
    def on_total_angle_changed(self,widget,event=None):
        delta = float(self.entry['delta_angle'].get_text())
        try:
            total_angle = float(self.entry['total_angle'].get_text())
            total_frames = int(total_angle / delta)
        except:
            total_frames = int(self.entry['num_frames'].get_text())
            total_angle = total_frames * delta 

        self.entry['total_angle'].set_text('%0.2f' % total_angle)                       
        self.entry['num_frames'].set_text('%d' % total_frames)
        self.check_changes()
        return False

    def on_delta_changed(self,widget,event=None):
        beamline = globalRegistry.lookup([], IBeamline)

        max_dps = beamline.config.get('max_omega_velocity', 20.0)
        try:
            delta = float(self.entry['delta_angle'].get_text())
            time = float(self.entry['exposure_time'].get_text())
        except:
            delta = 1.0
        delta = min(180.0, max(delta, 0.1))
        self.entry['delta_angle'].set_text('%0.2f' % delta)
        total_angle = float(self.entry['total_angle'].get_text())
        total_frames = max(1, int(total_angle/delta))
        self.entry['total_angle'].set_text('%0.2f' % (total_frames * delta))
        self.entry['num_frames'].set_text('%d' % total_frames)
        new_time = round(delta / min(max_dps, delta/time), 1)
        if new_time != time:
            self.entry['exposure_time'].set_text('%0.1f' % new_time)
        self.check_changes()
        return False

    def on_time_changed(self,widget,event=None):
        """Check the validity of the exposure time and adjust both 
           time and delta to be compatible with the beamline maximum 
           omega velocity"""
        
        beamline = globalRegistry.lookup([], IBeamline)
        max_dps = beamline.config.get('max_omega_velocity', 20.0)
        try:
            time = float(self.entry['exposure_time'].get_text())
            delta = float(self.entry['delta_angle'].get_text())
        except:
            time = 1.0
        time = max(0.1, time)
        self.entry['exposure_time'].set_text('%0.1f' % time)
        new_delta = round(time * min(max_dps, delta/time), 2)
        if new_delta != delta:
            self.entry['delta_angle'].set_text('%0.2f' % new_delta)
        self.check_changes()
        return False

    def on_start_frame_changed(self,widget,event=None):
        try:
            start_frame = int( float(self.entry['first_frame'].get_text()) )
        except:
            start_frame = 1
        
        start_frame = max(start_frame, 1)
        self.entry['first_frame'].set_text('%d' % start_frame)
        self.check_changes()
        return False

    def on_total_frames_changed(self,widget,event=None):
        delta = float(self.entry['delta_angle'].get_text())
        try:
            total_frames = float(self.entry['num_frames'].get_text() )
            total_angle = total_frames * delta 
        except:
            total_angle = float(self.entry['total_angle'].get_text())
            total_frames = int(total_angle / delta)
        
        self.entry['num_frames'].set_text('%d' % total_frames)    
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

    def on_attenuation_changed(self,widget,event=None):
        try:
            attenuation = float(self.entry['attenuation'].get_text())    
        except:
            attenuation = 0.0
        attenuation = max(0.0, min(100, attenuation))
        self.entry['attenuation'].set_text('%0.0f' % attenuation) 
        self.check_changes()
        return False

    def on_distance_changed(self,widget,event=None):
        two_theta = self.parameters.get('two_theta', 0)    
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
        self.check_changes()
        return False        

    def on_save(self, widget):
        self.enable_btn.set_active(True)
        self.parameters = self.get_parameters()
        self.check_changes()
        return True
        
    def on_reset_parameters(self, obj):
        params = self.get_parameters()
        beamline = globalRegistry.lookup([], IBeamline)
        for k in ['attenuation', 'distance', 'two_theta', 'energy', 'energy_label',
                  'start_angle', 'delta_angle', 'total_angle', 'first_frame', 'skip', 'wedge', 'inverse_beam']:
            params[k] = DEFAULT_PARAMETERS[k]
        params['exposure_time'] = beamline.config['default_exposure']
        params['crystal_id'] = self.active_sample.get('id', None)
        
        self.set_parameters(params)
        self.check_changes()
        return True  
        
    def on_update_parameters(self, obj):
        params = self.get_parameters()
        beamline = globalRegistry.lookup([], IBeamline)
        if self.active_sample:
            params['name'] = self.active_sample.get('name', params['name']) 
        params['distance'] = self.active_strategy.get('distance', beamline.distance.get_position())
        params['attenuation'] = self.active_strategy.get('attenuation', beamline.attenuator.get())
        params['two_theta'] =  beamline.two_theta.get_position()
        params['energy'] = self.active_strategy.get('energy', [beamline.energy.get_position()])
        params['energy_label'] = self.active_strategy.get('energy_label', ['E0'])
        params['start_angle'] = self.active_strategy.get('start_angle', beamline.omega.get_position())
        params['delta_angle'] = self.active_strategy.get('delta_angle', 1.0)
        params['exposure_time'] = self.active_strategy.get('exposure_time', beamline.config['default_exposure'])
        params['total_angle'] = self.active_strategy.get('total_angle', 180.0)
        params['first_frame'] = 1
        params['skip'] = ""
        params['wedge'] = 360.0
        params['inverse_beam'] = False
        params['scattering_factors'] = self.active_strategy.get('scattering_factors', None)
        self.set_parameters(params)
        self.check_changes()
        return True  
