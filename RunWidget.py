#!/usr/bin/env python

import gtk, gobject
import sys, os
from Predictor import Predictor
from Beamline import beamline
from Dialogs import select_folder, check_folder
from Utils import *
(
  COLUMN_LABEL,
  COLUMN_ENERGY,
  COLUMN_EDITABLE
) = range(3)


class RunWidget(gtk.VBox):
    def __init__(self, num=0):
        gtk.VBox.__init__(self,spacing=6)
        
        self.set_border_width(6)
        self.title = gtk.Label("")
        
        bbox = gtk.HBox(True, 6)
        self.apply_btn = gtk.Button(stock=gtk.STOCK_SAVE)
        self.undo_btn = gtk.Button(stock=gtk.STOCK_UNDO)
        self.undo_btn.set_sensitive(False) # initially disabled since stack is empty
        self.delete_btn = gtk.Button(stock=gtk.STOCK_DELETE)
        self.pack_start(self.title, padding=6, expand=False, fill=False)
        
        hseparator = gtk.HSeparator()
        hseparator.set_size_request(-1,3)
        self.pack_start(hseparator, expand=False, fill=False, padding=6)
        
        bbox.pack_start(self.apply_btn)
        bbox.pack_start(self.undo_btn)
        bbox.pack_start(self.delete_btn)
        self.pack_start(bbox, expand=False, fill=False)
        
        hseparator = gtk.HSeparator()
        hseparator.set_size_request(-1,3)
        self.pack_start(hseparator, expand=False, fill=False, padding=6)
        
        self.layout_table = gtk.Table(12,4, False)
        self.layout_table.set_row_spacings(3)
        self.layout_table.set_col_spacings(3)
        
        self.entry = {}
        self.units = {}
        self.labels = {}
        
        # Data for labels (label: (col, row))
        labels = {
            'Prefix:':      (0, 0),
            'Directory:':   (0, 1),
            'Distance:':    (0, 2),
            'Delta:':       (0, 3),
            'Time:':        (0, 4),
            'Frame':        (1, 5),
            'Angle':        (2, 5),
            'Start:':       (0, 6),
            'End:':         (0, 7),
            'Wedge:':       (0, 8)
        }
        # Data for entries (name: (col, row, length, [unit]))
        entries = {
            'prefix':       (1, 0, 3),
            'directory':    (1, 1, 3),
            'distance':     (1, 2, 2, 'mm'),
            'delta':        (1, 3, 2, 'deg'),
            'time':         (1, 4, 2, 'sec'),
            'start_frame':  (1, 6, 1),
            'start_angle':  (2, 6, 1, 'deg'),
            'end_frame':    (1, 7, 1),
            'end_angle':    (2, 7, 1, 'deg'),
            'wedge':        (1, 8, 2, 'deg')
        }
        
        # Create labels from data
        for (key,val) in zip(labels.keys(),labels.values()):
            self.labels[key] = gtk.Label(key)
            self.labels[key].set_alignment(1,0.5)
            self.layout_table.attach( self.labels[key], val[0], val[0]+1, val[1], val[1]+1)
        
        # Create entries from data    
        for (key,val) in zip(entries.keys(),entries.values()):
            self.entry[key] = gtk.Entry()
            
            # center justify prefix and directory, right justify all others
            if val[2] == 3:
                self.entry[key].set_alignment(0.5)
            else:
                self.entry[key].set_alignment(1)               
            self.entry[key].set_width_chars(val[2]*6)
            self.layout_table.attach( self.entry[key], val[0], val[0]+val[2], val[1], val[1]+1, xoptions=gtk.FILL)
            
            # Add unit label if present
            if len(val)>3:
                self.units[key] = gtk.Label(val[3])
                self.layout_table.attach(self.units[key], val[0]+val[2], val[0]+val[2]+1, val[1], val[1]+1, xoptions=gtk.EXPAND)
            
        # entry signals
        self.entry['prefix'].connect('focus-out-event', self.on_prefix_changed)
        self.entry['directory'].connect('focus-out-event', self.on_directory_changed)
        self.entry['start_angle'].connect('focus-out-event', self.on_start_angle_changed)
        self.entry['delta'].connect('focus-out-event', self.on_delta_changed)
        self.entry['end_angle'].connect('focus-out-event', self.on_end_angle_changed)
        self.entry['end_frame'].connect('focus-out-event', self.on_end_frame_changed)
        self.entry['start_frame'].connect('focus-out-event', self.on_start_frame_changed)
        self.entry['distance'].connect('focus-out-event', self.on_distance_changed)
        self.entry['time'].connect('focus-out-event', self.on_time_changed)
        self.entry['wedge'].connect('focus-out-event', self.on_wedge_changed)
        
        self.entry['prefix'].connect('activate', self.on_prefix_changed)
        self.entry['directory'].connect('activate', self.on_directory_changed)
        self.entry['start_angle'].connect('activate', self.on_start_angle_changed)
        self.entry['delta'].connect('activate', self.on_delta_changed)
        self.entry['end_angle'].connect('activate', self.on_end_angle_changed)
        self.entry['end_frame'].connect('activate', self.on_end_frame_changed)
        self.entry['start_frame'].connect('activate', self.on_start_frame_changed)
        self.entry['distance'].connect('activate', self.on_distance_changed)
        self.entry['time'].connect('activate', self.on_time_changed)
        self.entry['wedge'].connect('activate', self.on_wedge_changed)
       
        # Inverse Beam
        self.inverse_beam = gtk.CheckButton(label='Inverse beam')
        self.layout_table.attach(self.inverse_beam, 1, 3, 10, 11, xoptions=gtk.FILL)
        
        # Select Directory Button
        self.dir_btn = gtk.ToolButton('gtk-open')
        self.dir_btn.connect('clicked', self.on_select_dir)
        self.layout_table.attach(self.dir_btn, 4, 5, 1, 2,xoptions=gtk.EXPAND)

        # Energy
        self.energy_store = gtk.ListStore(
            gobject.TYPE_STRING,
            gobject.TYPE_FLOAT,
            gobject.TYPE_BOOLEAN
        )
        self.energy_list = gtk.TreeView(model=self.energy_store)
        self.energy_list.set_rules_hint(True)
        self.sw = gtk.ScrolledWindow()
        self.sw.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        self.sw.set_policy(gtk.POLICY_NEVER, gtk.POLICY_NEVER)
        self.sw.add(self.energy_list)
        
        
        #Label column
        renderer = gtk.CellRendererText()
        renderer.set_data('column',COLUMN_LABEL)
        renderer.connect("edited", self.on_energy_edited, self.energy_store)
        column1 = gtk.TreeViewColumn('Label', renderer, text=COLUMN_LABEL, editable=COLUMN_EDITABLE)
        column1.set_fixed_width(20)
        #Energy column
        renderer = gtk.CellRendererText()
        renderer.set_data('column',COLUMN_ENERGY)
        renderer.connect("edited", self.on_energy_edited, self.energy_store)
        column2 = gtk.TreeViewColumn('Energy (keV)', renderer, text=COLUMN_ENERGY, editable=COLUMN_EDITABLE)
        column2.set_cell_data_func(renderer, self.__float_format, ('%8.4f', COLUMN_ENERGY))
        column2.set_fixed_width(20)
        
        self.energy_list.append_column(column1)
        self.energy_list.append_column(column2)
        self.layout_table.attach(self.sw, 1, 4, 11,12, xoptions=gtk.FILL)
        self.pack_start(self.layout_table, expand=False, fill=False)
            
        self.energy_btn_box = gtk.VBox(False,6)
        self.add_e_btn = gtk.ToolButton('gtk-add')
        self.add_e_btn.connect("clicked", self.on_add_energy_clicked)
        self.energy_btn_box.pack_start(self.add_e_btn, expand=False, fill=False)

        self.del_e_btn = gtk.ToolButton('gtk-remove')
        self.del_e_btn.connect("clicked", self.on_remove_energy_clicked)
        self.energy_btn_box.pack_start(self.del_e_btn, expand=False, fill=False)
        self.layout_table.attach(self.energy_btn_box, 4, 5, 11,12)
        self.predictor = None

        # connect signals
        self.apply_btn.connect('clicked', self.on_apply)
        self.undo_btn.connect('clicked',self.on_undo)
        self.show_all()
        self.set_no_show_all(True)
        
        #initialize parameters
        run_data = self.default_parameters()
        self.set_number(num)
        run_data['number'] = self.number
        self.undo_stack = []
        self.set_parameters(run_data)
                
    def __add_energy(self, item=None): 
        iter = self.energy_store.append()        
        if item==None:
            index = len(self.energy)
            name = "E%d" % (index)
            while name in self.energy_label:
                index += 1
                name = "E%d" % (index)
            item = [name, 12.6580, True]
        
        self.energy.append(item[1])
        self.energy_label.append(item[0])    
        self.energy_store.set(iter, 
            COLUMN_LABEL, item[COLUMN_LABEL], 
            COLUMN_ENERGY, item[COLUMN_ENERGY],
            COLUMN_EDITABLE, item[COLUMN_EDITABLE]
        )
        
    def __float_format(self, cell, renderer, model, iter, data):
        format, column = data
        value = model.get_value(iter, column)
        renderer.set_property('text', format % value)
        return
        
    def on_energy_edited(self, cell, path_string, new_text, model):
        iter = model.get_iter_from_string(path_string)
        path = model.get_path(iter)[0]
        column = cell.get_data("column")

        if column == COLUMN_ENERGY:
            self.energy[path] = float(new_text)
            model.set(iter, column, float(new_text))
        elif column == COLUMN_LABEL:
            self.energy_label[path] = new_text
            model.set(iter, column, new_text)
            
    def __reset_e_btn_states(self):
        size = len(self.energy)
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
        if len(self.energy) < 5:
            self.__add_energy()
        self.__reset_e_btn_states()

    def on_remove_energy_clicked(self, button):
        if len(self.energy) > 1:
            selection = self.energy_list.get_selection()
            model, iter = selection.get_selected()
            if iter:
                path = model.get_path(iter)[0]
                del self.energy[path]
                del self.energy_label[path]
                model.remove(iter)
        self.__reset_e_btn_states()
            
    def set_parameters(self, dict):
        self.parameters = dict
        keys = ['distance','delta','start_angle','end_angle','wedge','time'] # Floats
        for key in keys:
            self.entry[key].set_text("%0.2f" % dict[key])
        keys = ['start_frame', 'end_frame']  # ints
        for key in keys:
            self.entry[key].set_text("%d" % dict[key])
        self.entry['prefix'].set_text("%s" % dict['prefix'])
        self.entry['directory'].set_text("%s" % dict['directory'])
        self.set_number(dict['number'])
        self.inverse_beam.set_active(dict['inverse_beam'])
        self.energy_store.clear()
        self.energy = []
        self.energy_label = []
        # set energy to current value for run 0
        if self.number ==0:
            dict['energy'] = [ beamline['motors']['energy'].get_position() ]
            dict['energy_label'] = [ 'E0' ]
        for i in range(len(dict['energy'])):
            self.__add_energy([dict['energy_label'][i], dict['energy'][i], True] )
        self.__reset_e_btn_states()
        
        if self.number==0 and self.predictor:
            self.predictor.set_all( keV_to_A(dict['energy'][0]), dict['distance'], 0)
            self.predictor.update(force=True)
        
    def get_parameters(self):
        run_data = {}
        run_data['prefix']      = self.entry['prefix'].get_text().strip()
        run_data['directory']   = self.entry['directory'].get_text().strip()
        run_data['energy']  =    self.energy
        run_data['energy_label'] = self.energy_label
        run_data['inverse_beam'] = self.inverse_beam.get_active()
        run_data['number'] = self.number
        keys = ['distance','delta','start_angle','end_angle','wedge','time'] # Floats
        for key in keys:
            run_data[key] = float(self.entry[key].get_text())
        keys = ['start_frame','end_frame']  # Convert this to int
        for key in keys:
            run_data[key] = int(self.entry[key].get_text())
        return run_data.copy()

    def default_parameters(self):
        run_data = {}
        run_data['prefix'] = 'test'
        run_data['directory'] = '/data'
        run_data['distance'] = 150.0
        run_data['delta'] = 0.5
        run_data['time'] = 5
        run_data['start_angle'] = 0
        run_data['end_angle']= 0.5
        run_data['start_frame']= 1
        run_data['end_frame']= 1
        run_data['inverse_beam']= False
        run_data['wedge']=180.0
        run_data['energy'] = [ beamline['motors']['energy'].get_position() ]
        run_data['energy_label'] = ['E0']
        run_data['number'] = 0
        return run_data
                
    def set_number(self, num=0):
        self.number = num
        self.title.set_text('<big><b>Run %d</b></big>' % self.number)
        self.title.set_use_markup(True)
        # Hide controls for Run 0
        if num == 0:
            keys = ['end_angle','end_frame','wedge']
            for key in keys:
                self.entry[key].set_sensitive(False)
                self.entry[key].hide()
            keys = ['end_angle','wedge']
            for key in keys:
                self.units[key].set_sensitive(False)
                self.units[key].hide()
            keys = ['End:','Wedge:']
            for key in keys:
                self.labels[key].set_sensitive(False)
                self.labels[key].hide()
            self.inverse_beam.hide()
            self.energy_btn_box.hide()
            self.inverse_beam.set_sensitive(False)
            self.energy_list.set_sensitive(False)
            self.sw.hide()    
            self.delete_btn.set_sensitive(False)
            if self.predictor is None:    
                #add Predictor
                self.predictor = Predictor()
                beamline['motors']['detector_2th'].connect('changed', self.predictor.on_two_theta_changed)
                self.predictor.set_size_request(220,220)
                self.pack_end( self.predictor, expand=False, fill=False)
    
    def check_changes(self):
        new_values = self.get_parameters()
        for key in new_values.keys():
            if key in ['energy', 'energy_label']:
                widget = self.energy_list
            elif key == 'inverse_beam':
                widget = self.inverse_beam
            elif key == 'number':
                widget = self.title
            else:
                widget = self.entry[key]
            if new_values[key] != self.parameters[key]:
                widget.modify_text(gtk.STATE_NORMAL, gtk.gdk.color_parse("red"))
            else:
                widget.modify_text(gtk.STATE_NORMAL, None)

    def on_prefix_changed(self, widget, event=None):
        self.check_changes()
        return False
    
    def on_distance_changed(self,widget,event=None):
        try:
            distance = float(self.entry['distance'].get_text())
        except:
            distance = 150.0            
        if self.number==0 and self.predictor:
            self.update_predictor()
        self.entry['distance'].set_text('%0.2f' % distance)
        self.check_changes()
        return False

    def on_start_angle_changed(self,widget,event=None):
        delta = float(self.entry['delta'].get_text())
        start_frame = int(self.entry['start_frame'].get_text())
        end_frame = int(self.entry['end_frame'].get_text())
        try:
            start_angle = float(self.entry['start_angle'].get_text())
        except:
            end_angle = float(self.entry['end_angle'].get_text())
            start_angle = end_angle - (end_frame - start_frame + 1) * delta
            
        self.entry['start_angle'].set_text('%0.2f' % start_angle)            
        end_angle = start_angle + delta * (end_frame - start_frame + 1)
        self.entry['end_angle'].set_text('%0.2f' % end_angle)
        self.check_changes()
        return False
    
    def on_end_angle_changed(self,widget,event=None):
        start_angle = float(self.entry['start_angle'].get_text())    
        start_frame = int(self.entry['start_frame'].get_text())
        delta = float(self.entry['delta'].get_text())
        try:
            end_angle = float(self.entry['end_angle'].get_text())
        except:
            end_frame = int(self.entry['end_frame'].get_text())
            end_angle = start_angle + ((end_frame - start_frame + 1) * delta )

        if end_angle < start_angle:
            tmp = end_angle
            end_angle = start_angle
            start_angle = tmp
        self.entry['start_angle'].set_text('%0.2f' % start_angle) 
        self.entry['end_angle'].set_text('%0.2f' % end_angle)                       
        end_frame = start_frame + (end_angle - start_angle)/delta - 1 
        self.entry['end_frame'].set_text('%d' % end_frame)
        self.check_changes()
        return False

    def on_delta_changed(self,widget,event=None):
        try:
            delta = float(self.entry['delta'].get_text())
            time = float(self.entry['time'].get_text())
        except:
            delta = 1.0
        delta = (delta > 0.2 and delta) or 0.2
        #if (delta/time) < (1.0/5.0): # temporary velocity limit
        #    delta = time * 1.0/5.0
        self.entry['delta'].set_text('%0.2f' % delta)
        start_angle = float(self.entry['start_angle'].get_text())
        end_angle = float(self.entry['end_angle'].get_text())
        start_frame = int(self.entry['start_frame'].get_text())
        end_frame = int(self.entry['end_frame'].get_text())

        if self.number == 0:
            end_angle = start_angle + delta
            self.entry['end_angle'].set_text('%0.2f' % end_angle)
        else:
            if (end_angle - start_angle) < delta:
                end_angle = start_angle + delta
                self.entry['end_angle'].set_text('%0.2f' % end_angle)             
            end_frame = start_frame + (end_angle - start_angle)/delta - 1
            self.entry['end_frame'].set_text('%d' % end_frame)
        self.check_changes()
        return False

    def on_time_changed(self,widget,event=None):
        try:
            delta = float(self.entry['delta'].get_text())
            time = float(self.entry['time'].get_text())
        except:
            time = 1.0
        time = (abs(time) > 0.1 and abs(time)) or 0.1
        #if (delta/time) < (1.0/5.0): # temporary velocity limit
        #    time = delta / (1.0/5.0)
        self.entry['time'].set_text('%0.2f' % time)
        self.check_changes()
        return False

    def on_start_frame_changed(self,widget,event=None):
        start_angle = float(self.entry['start_angle'].get_text())
        end_angle = float(self.entry['end_angle'].get_text())
        delta = float(self.entry['delta'].get_text())
        try:
            start_frame = int( float(self.entry['start_frame'].get_text()) )
        except:
            end_frame = int(self.entry['end_frame'].get_text())
            start_frame = end_frame - (end_angle - start_angle)/delta + 1
        
        self.entry['start_frame'].set_text('%d' % start_frame)
        end_frame = start_frame + ((end_angle - start_angle - delta)/delta )
    
        self.entry['end_frame'].set_text('%d' % end_frame)
        self.check_changes()
        return False

    def on_end_frame_changed(self,widget,event=None):
        start_frame = int( self.entry['start_frame'].get_text() )
        delta = float(self.entry['delta'].get_text())
        try:
            end_frame = float(self.entry['end_frame'].get_text() )
        except:
            start_angle = float(self.entry['start_angle'].get_text())
            end_angle = float(self.entry['end_angle'].get_text())
            end_frame = start_frame + (end_angle - start_angle)/delta - 1
        
        if end_frame < start_frame:
            tmp = end_frame
            end_frame = start_frame
            start_frame = tmp
        self.entry['start_frame'].set_text('%d' % start_frame) 
        self.entry['end_frame'].set_text('%d' % end_frame)
        start_angle = float(self.entry['start_angle'].get_text())
        end_angle = start_angle + ((end_frame - start_frame + 1) * delta )
    
        self.entry['end_angle'].set_text('%0.2f' % end_angle)
        self.check_changes()
        return False

    def on_wedge_changed(self,widget,event=None):
        try:
            wedge = float(self.entry['wedge'].get_text())    
        except:
            wedge = 180.0

        self.entry['wedge'].set_text('%0.2f' % wedge) 
        self.check_changes()
        return False
        
    def on_directory_changed(self,widget, event=None):
        directory = self.entry['directory'].get_text()
        self.check_changes()
        return False

    def on_select_dir(self, widget):
        folder = select_folder()
        if folder:
            self.entry['directory'].set_text(folder)
        return True
            
    def update_predictor(self):
        self.predictor.set_energy(self.energy[0])
        distance = float(self.entry['distance'].get_text())
        self.predictor.set_distance(distance)
        self.predictor.set_twotheta( beamline['motors']['detector_2th'].get_position() )
        self.predictor.update(force = True)
        

    def on_apply(self, widget):
        self.parameters = self.get_parameters()
        self.undo_stack.append(self.parameters)
        self.check_changes()
        self.undo_btn.set_sensitive(True)
        if self.predictor is not None:
            self.update_predictor()
        return True
    
    def on_undo(self,widget):
        if len(self.undo_stack) > 0:
            run_data = self.undo_stack.pop()
            self.set_parameters(run_data)
        if len(self.undo_stack) == 0:
            self.undo_btn.set_sensitive(False)
        self.check_changes()
