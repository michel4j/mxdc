import gtk, gobject
import sys, os
from Dialogs import select_folder, check_folder, DirectoryButton
from ActiveWidgets import ActiveProgressBar

(
  COLUMN_LABEL,
  COLUMN_ENERGY,
  COLUMN_FPP,
  COLUMN_FP,
) = range(4)

class ScanControl(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self,False,12)

        # lists to hold results data
        self.energies = []
        self.names = []
        
        # Scan Mode Section
        scan_frame = gtk.Frame('<b>Scan Mode:</b>')
        scan_frame.set_shadow_type(gtk.SHADOW_NONE)
        scan_frame.get_label_widget().set_use_markup(True)
        scan_align = gtk.Alignment()
        scan_box = gtk.VBox(True,0)
        scan_align.set(0.5,0.5,1,1)
        scan_align.set_padding(0,0,12,0)
        scan_frame.add(scan_align)
        scan_align.add(scan_box)
        self.scan_option = {}
        for key in ['MAD','Excitation']:
            lbl = key + ' Scan'
            self.scan_option[key] = gtk.RadioButton(group=None, label=lbl)
            scan_box.pack_start(self.scan_option[key],expand=False, fill=False)
        self.scan_option['MAD'].set_group(self.scan_option['Excitation'])
        self.scan_option['MAD'].set_active(True)
        self.pack_start(scan_frame,expand=False,fill=False)
        
        
        # Scan description Section
        descr_frame = gtk.Frame('<b>Description:</b>')
        self.descriptions = {
            'MAD': 'Scan absorption edge to find '
           +'peak, inflection and remote energies.',
            'Excitation': 'Collect a full spectrum '
           +'to identify elements present in the sample.' 
        }
        descr_frame.set_shadow_type(gtk.SHADOW_NONE)
        descr_frame.get_label_widget().set_use_markup(True)
        descr_align = gtk.Alignment()
        descr_align.set(0.5,0.5,1,1)
        descr_align.set_padding(0,0,24,0)
        descr_frame.add(descr_align)
        self.scan_description = gtk.Label(self.descriptions['MAD'])
        self.scan_description.set_property('wrap', True)
        self.scan_description.set_size_request(200,-1)
        descr_align.add(self.scan_description)
        self.pack_start(descr_frame,expand=False,fill=False)
        
        # Scan parameters Section
        param_frame = gtk.Frame('<b>Scan Parameters:</b>')
        param_frame.set_shadow_type(gtk.SHADOW_NONE)
        param_frame.get_label_widget().set_use_markup(True)
        param_align = gtk.Alignment()
        param_box = gtk.Table(3,4,False)
        param_box.set_col_spacings(3)
        param_box.set_row_spacings(3)
        param_align.set(0.5,0.5,1,1)
        param_align.set_padding(0,0,0,0)
        param_frame.add(param_align)
        param_align.add(param_box)
        items = {
            'prefix': ('Prefix:',0,'',2),
            'edge':    ('Edge:', 2, '',1),
            'energy': ('Energy:',3,'keV',1),
            'time': ('Time:', 4, 'sec',1)
        }
        self.entry = {}
        for key in items.keys():
            val = items[key]
            lbl = gtk.Label(val[0])
            lbl.set_alignment(1,0.5)
            param_box.attach(lbl, 0, 1, val[1], val[1]+1)
            param_box.attach(gtk.Label(val[2]), 2, 3, val[1], val[1]+1,xoptions=gtk.EXPAND)
            self.entry[key] = gtk.Entry()
            self.entry[key].set_alignment(0.5)
            self.entry[key].set_width_chars(val[3]*8)
            param_box.attach(self.entry[key], 1,1+ val[3],val[1], val[1]+1)
        self.entry['edge'].set_editable(False)        
        self.pack_start(param_frame,expand=False, fill=False)
        
        for key in ['MAD','Excitation']:
            self.scan_option[key].connect('toggled',self.update_description, key)
        
        # Select Directory Button
        lbl = gtk.Label('Directory:')
        lbl.set_alignment(1,0.5)
        param_box.attach(lbl, 0, 1, 1, 2)
        self.entry['directory'] = DirectoryButton()
        param_box.attach(self.entry['directory'], 1, 3, 1, 2,xoptions=gtk.FILL)

        # command button area        
        bbox = gtk.VBox(False,6)
        self.start_btn = gtk.Button('Start Scan')
        self.stop_btn = gtk.Button('Stop Scan')
        self.abort_btn = gtk.Button('Abort Scan')
        self.create_run_btn = gtk.Button('Create MAD Run')
        self.stop_btn.set_sensitive(False) # initially disabled
        self.abort_btn.set_sensitive(False)
        self.create_run_btn.set_sensitive(False)
        self.progress_bar = ActiveProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_text('0.0%')
        

        # Results section
        # Energy
        self.energy_store = gtk.ListStore(
            gobject.TYPE_STRING,
            gobject.TYPE_FLOAT,
            gobject.TYPE_FLOAT,
            gobject.TYPE_FLOAT
        )
        self.energy_list = gtk.TreeView(model=self.energy_store)
        self.energy_list.set_rules_hint(True)
        self.sw = gtk.ScrolledWindow()
        self.sw.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        self.sw.set_policy(gtk.POLICY_NEVER, gtk.POLICY_NEVER)
        self.sw.add(self.energy_list)
        self.sw.set_border_width(6)
        self.pack_start(self.sw)
        self.sw.set_sensitive(False)

        #Label column
        renderer = gtk.CellRendererText()
        column1 = gtk.TreeViewColumn('Name', renderer, text=COLUMN_LABEL)
        
        #Energy column
        renderer = gtk.CellRendererText()
        column2 = gtk.TreeViewColumn('Energy (keV)', renderer, text=COLUMN_ENERGY)
        column2.set_cell_data_func(renderer, self.__float_format, ('%8.4f', COLUMN_ENERGY))

        #FP column
        renderer = gtk.CellRendererText()
        column3 = gtk.TreeViewColumn("f'", renderer, text=COLUMN_FP)
        column3.set_cell_data_func(renderer, self.__float_format, ('%6.2f', COLUMN_FP))

        #FPP column
        renderer = gtk.CellRendererText()
        column4 = gtk.TreeViewColumn('f"', renderer, text=COLUMN_FPP)
        column4.set_cell_data_func(renderer, self.__float_format, ('%6.2f', COLUMN_FPP))
        
        self.energy_list.append_column(column1)
        self.energy_list.append_column(column2)
        self.energy_list.append_column(column4)
        self.energy_list.append_column(column3)

        bbox.pack_start(self.start_btn)
        bbox.pack_start(self.stop_btn)
        bbox.pack_start(self.abort_btn)
        bbox.pack_start(self.create_run_btn)
        bbox.pack_end(self.progress_bar)
        
        bbox.set_border_width(6)
        self.pack_end(bbox, expand=False,fill=False)
        
        params = {}
        params['prefix']      = 'test_scan'
        params['directory']   = os.environ['HOME']
        params['energy']  =    12.6580
        params['edge'] =  'Se-K'
        params['time'] = 1.0
        params['emission'] = 11.2100
        self.set_parameters(params)
        self.show_all()

    def __add_energy(self, item=None): 
        iter = self.energy_store.append()        
        self.energy_store.set(iter, 
            COLUMN_LABEL, item[COLUMN_LABEL], 
            COLUMN_ENERGY, item[COLUMN_ENERGY],
            COLUMN_FP, item[COLUMN_FP],
            COLUMN_FPP, item[COLUMN_FPP]
        )
        self.energies.append(item[COLUMN_ENERGY])
        self.names.append(item[COLUMN_LABEL])
        
    def __float_format(self, cell, renderer, model, iter, data):
        format, column = data
        value = model.get_value(iter, column)
        renderer.set_property('text', format % value)
        return
    
    def clear(self):
        self.energy_store.clear()
        self.energies = []
        self.names = []
        self.create_run_btn.set_sensitive(False)
        
    def set_results(self,results):
        #keys = results.keys()
        keys = ['peak','infl','remo']  # collect peak infl remo in that order
        for key in keys:
            if key in results.keys():  # all energies are not necessarily present
                self.__add_energy(results[key])
        self.sw.set_sensitive(True)
        self.create_run_btn.set_sensitive(True)
        return True
    
    def update_description(self, widget,key):
        self.scan_description.set_text(self.descriptions[key])
        return True

    def set_parameters(self, dict):
        keys = ['prefix','directory','edge'] # Text
        for key in keys:
            if key in dict.keys():
                self.entry[key].set_text("%s" % dict[key])

        self.entry['energy'].set_text("%0.4f" % dict['energy'])
        if 'time' in dict.keys():
            self.entry['time'].set_text("%0.1f" % dict['time'])
        self.emission_line = dict['emission']
        return True
        
    def get_parameters(self):
        params = {}
        params['prefix']      = self.entry['prefix'].get_text().strip()
        params['directory']   = self.entry['directory'].get_text().strip()
        params['energy']  =    float( self.entry['energy'].get_text() )
        params['edge'] =  self.entry['edge'].get_text().strip()
        params['time'] = float( self.entry['time'].get_text() )
        if self.scan_option['MAD'].get_active():
            params['mode'] = 'MAD'
        else:
            params['mode'] = 'Excitation'
        params['emission'] = self.emission_line
        return params

    def get_run_data(self):
        run_data = self.get_parameters()
        run_data['distance'] = 150.0
        run_data['delta'] = 1
        run_data['time'] = 1
        run_data['start_angle'] = 0
        run_data['angle_range']= 180
        run_data['start_frame']= 1
        run_data['num_frames']= 180
        run_data['inverse_beam']= False
        run_data['wedge']=180
        run_data['energy'] = self.energies
        run_data['energy_label'] = self.names
        run_data['number'] = -1
        return run_data
                    
def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(6)
    #win.set_size_request(250,400)
    win.set_title("SCAN Demo")
    
    myscan = ScanControl()
    win.add(myscan)

    win.show_all()

    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()


if __name__ == '__main__':
    main()
    
