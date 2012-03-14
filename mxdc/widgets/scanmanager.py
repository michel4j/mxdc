
import os, sys
import time
import gtk
import gtk.glade
import gobject
import numpy

from mxdc.widgets.periodictable import PeriodicTable
from mxdc.widgets.textviewer import TextViewer
from mxdc.widgets.plotter import Plotter
from mxdc.widgets.dialogs import  warning, error, MyDialog
from mxdc.utils import config
from mxdc.widgets.misc import ActiveProgressBar
from bcm.beamline.mx import IBeamline
from twisted.python.components import globalRegistry
from bcm.engine.spectroscopy import XRFScan, XANESScan, EXAFSScan
from bcm.utils import science, lims_tools
from bcm.utils.log import get_module_logger


_logger = get_module_logger('mxdc.scanmanager')

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
(
  COLUMN_LABEL,
  COLUMN_ENERGY,
  COLUMN_FPP,
  COLUMN_FP,
) = range(4)

(
  COLUMN_DRAW,
  COLUMN_ELEMENT,
  COLUMN_PERCENT,
) = range(3)

(
  SCAN_START,
  SCAN_PAUSE,
  SCAN_RESUME,
  SCAN_STOP,
) = range(4)

SCAN_CONFIG_FILE = 'scan_config.json'

def summarize_lines(data):
    name_dict = {
        'L1M2,3,L2M4': 'L1,2M',
        'L1M3,L2M4': 'L1,2M',       
        'L1M,L2M4': 'L1,2M',
    }
    def join(a,b):
        if a==b:
            return [a]
        if abs(b[1]-a[1]) < 0.200:
            if a[0][:-1] == b[0][:-1]:
                #nm = '%s,%s' % (a[0], b[0][-1])
                nm = b[0][:-1]
            else:
                nm = '%s,%s' % (a[0], b[0])
            nm = name_dict.get(nm, nm)
            ht =  (a[2] + b[2])
            pos = (a[1]*a[2] + b[1]*b[2])/ht
            return [(nm, round(pos,4), round(ht,2))]
        else:
            return [a, b]
    #data.sort(key=lambda x: x[1])
    data.sort()
    #print data
    new_data = [data[0]]
    for entry in data:
        old = new_data[-1]
        _new = join(old, entry)
        new_data.remove(old)
        new_data.extend(_new)
    #print new_data
    return new_data
        
XRF_COLOR_LIST = ['#800080','#FF0000','#008000',
                  '#FF00FF','#800000','#808000',
                  '#008080','#00FF00','#000080',
                  '#00FFFF','#0000FF','#000000']

class ScanManager(gtk.Frame):
    __gsignals__ = {
        'create-run': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'update-strategy': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
    }
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'scan_manager.glade'), 
                                  'scan_widget')            

        self._create_widgets()

        self.xanes_scanner = XANESScan()
        self.xrf_scanner = XRFScan()
        self.exafs_scanner = EXAFSScan()
        
        # XANES   
        self.xanes_scanner.connect('new-point', self.on_new_scan_point)    
        self.xanes_scanner.connect('done', self.on_xanes_done)
        self.xanes_scanner.connect('stopped', self.on_xanes_done)
        self.xanes_scanner.connect('progress', self.on_progress)    
        self.xanes_scanner.connect('error', self.on_xanes_error)
        self.xanes_scanner.connect('started', self.on_scan_started)  
        self.xanes_scanner.connect('paused', self.on_scan_paused)  
        
        # XRF      
        self.xrf_scanner.connect('done', self.on_xrf_done)   
        self.xrf_scanner.connect('stopped', self.on_scan_stopped)
        self.xrf_scanner.connect('error', self.on_scan_error)
        self.xrf_scanner.connect('progress', self.on_progress)
        self.xrf_scanner.connect('started', self.on_scan_started)  
        
        # EXAFS
        self.exafs_scanner.connect('new-point', self.on_new_scan_point)    
        self.exafs_scanner.connect('progress', self.on_progress)    
        self.exafs_scanner.connect('done', self.on_scan_done)
        self.exafs_scanner.connect('stopped', self.on_scan_stopped)
        self.exafs_scanner.connect('error', self.on_scan_error)        
        self.exafs_scanner.connect('started', self.on_scan_started)  
        self.exafs_scanner.connect('paused', self.on_scan_paused)

        # initial variables
        self.scanning = False
        self.paused = False
        self.progress_id = None
        self.scan_mode = 'XANES'
        self.active_sample = {}
        self.xrf_results = {}
        self.xrf_annotations = {}
        
        # housekeeping
        self._start_time = 0.0

        
        # lists to hold results data
        self.energies = []
        self.names = []
        self.scattering_factors = []
        self._load_config()
        #self.xanes_scanner.analyse_file('/home/michel/Downloads/test_scan_Se-K.raw')
    
    def do_create_run(self):
        pass
    
    def do_update_strategy(self, data):
        pass

    def __getattr__(self, key):
        try:
            return super(ScanManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def _create_widgets(self):
        
        self.scan_btn.set_label('mxdc-scan')
        self.stop_btn.set_label('mxdc-stop-scan')
        self.scan_btn.connect('clicked', self.on_scan_activated)
        self.stop_btn.connect('clicked', self.on_stop_activated)
        
        # Sizegroups for buttons horizontal sizes
        sg = gtk.SizeGroup(gtk.SIZE_GROUP_HORIZONTAL)
        sg.add_widget(self.scan_btn)
        sg.add_widget(self.stop_btn)
        sg.add_widget(self.update_strategy_btn)
        sg.add_widget(self.create_run_btn)
        
        # pbar
        self.scan_pbar = ActiveProgressBar()
        self.vbox3.pack_start(self.scan_pbar, expand=False, fill=False)
        self.xanes_btn.set_active(True)
        
        # Scan options
        self.xanes_btn.connect('toggled', self.on_mode_change, 'XANES')
        self.xrf_btn.connect('toggled', self.on_mode_change, 'XRF')
        self.exafs_btn.connect('toggled', self.on_mode_change, 'EXAFS')
        self.entries = {
            'prefix': self.prefix_entry,
            'directory': self.directory_btn,
            'edge': self.edge_entry,
            'energy': self.energy_entry,
            'time': self.time_entry,
            'attenuation': self.attenuation_entry,
            'crystal': self.crystal_entry
        }
        self.layout_table.attach(self.entries['directory'], 1,3, 1,2, xoptions=gtk.EXPAND|gtk.FILL)
        for key in ['prefix','edge']:
            self.entries[key].set_alignment(0.5)
        for key in ['energy','time','attenuation']:
            self.entries[key].set_alignment(1)

        # Notebook 
        self.output_log = TextViewer(self.output_text)
        
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
            loE, hiE = self.beamline.config['energy_range']
        except:
            self.beamline = None
            loE, hiE = 4.0, 18.0
        self.periodic_table = PeriodicTable(loE, hiE)
        self.periodic_table.connect('edge-selected',self.on_edge_selected)
        self.plotter = Plotter(xformat='%g')
        self.periodic_frame.add(self.periodic_table)
        self.plot_frame.add(self.plotter)
        self.add(self.scan_widget)

        # XANES Results section
        self.energy_store = gtk.ListStore(
            gobject.TYPE_STRING,
            gobject.TYPE_FLOAT,
            gobject.TYPE_FLOAT,
            gobject.TYPE_FLOAT
        )
        self.energy_list = gtk.TreeView(model=self.energy_store)
        self.energy_list.set_rules_hint(True)
        self.xanes_sw.add(self.energy_list)
        self.create_run_btn.connect('clicked', self.on_create_run)
        self.update_strategy_btn.connect('clicked', self.on_update_strategy)

        #Label column
        renderer = gtk.CellRendererText()
        column1 = gtk.TreeViewColumn('Name', renderer, text=COLUMN_LABEL)
        
        #Energy column
        renderer = gtk.CellRendererText()
        column2 = gtk.TreeViewColumn('Energy(keV)', renderer, text=COLUMN_ENERGY)
        column2.set_cell_data_func(renderer, self._float_format, ('%7.4f', COLUMN_ENERGY))

        #FP column
        renderer = gtk.CellRendererText()
        column3 = gtk.TreeViewColumn("f'", renderer, text=COLUMN_FP)
        column3.set_cell_data_func(renderer, self._float_format, ('%5.2f', COLUMN_FP))

        #FPP column
        renderer = gtk.CellRendererText()
        column4 = gtk.TreeViewColumn('f"', renderer, text=COLUMN_FPP)
        column4.set_cell_data_func(renderer, self._float_format, ('%5.2f', COLUMN_FPP))
        
        self.energy_list.append_column(column1)
        self.energy_list.append_column(column2)
        self.energy_list.append_column(column4)
        self.energy_list.append_column(column3)
        self.xanes_sw.show_all()
        
        # XRF Results section
        self.xrf_store = gtk.ListStore(
            gobject.TYPE_BOOLEAN,                          
            gobject.TYPE_STRING,
            gobject.TYPE_FLOAT
        )
        self.xrf_list = gtk.TreeView(model=self.xrf_store)
        self.xrf_list.set_rules_hint(True)
        self.xrf_sw.add(self.xrf_list)
        
        #Toggle column
        renderer = gtk.CellRendererToggle()
        renderer.connect('toggled', self.on_element_toggled, self.xrf_store)
        column = gtk.TreeViewColumn('', renderer, active=COLUMN_DRAW)
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.set_fixed_width(24)

        self.xrf_list.append_column(column)
        
        #Name column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn('Element', renderer, text=COLUMN_ELEMENT)
        column.set_cell_data_func(renderer, self._color_element, COLUMN_PERCENT)
        self.xrf_list.append_column(column)

        #Percent column
        renderer = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Reliability (%)", renderer, text=COLUMN_PERCENT)
        column.set_cell_data_func(renderer, self._float_format, ('%5.2f', COLUMN_PERCENT))
        self.xrf_list.append_column(column)
        self.xrf_sw.show_all()
        
        self.show_all()
        self.set_parameters()
   
    def _add_xanes_energy(self, item=None): 
        iter = self.energy_store.append()        
        self.energy_store.set(iter, 
            COLUMN_LABEL, item[COLUMN_LABEL], 
            COLUMN_ENERGY, item[COLUMN_ENERGY],
            COLUMN_FP, item[COLUMN_FP],
            COLUMN_FPP, item[COLUMN_FPP]
        )
        self.energies.append(item[COLUMN_ENERGY])
        self.names.append(item[COLUMN_LABEL])
        self.scattering_factors.append({'fp':item[COLUMN_FP], 'fpp':item[COLUMN_FPP]})

    def _add_xrf_element(self, item=None): 
        iter = self.xrf_store.append()        
        self.xrf_store.set(iter, 
            COLUMN_DRAW, False, 
            COLUMN_ELEMENT, item[0],
            COLUMN_PERCENT, item[1]
        )
        
    def _float_format(self, cell, renderer, model, iter, data):
        format, column = data
        value = model.get_value(iter, column)
        index = model.get_path(iter)[0]
        renderer.set_property('text', format % value)
        if model == self.xrf_store:
            renderer.set_property("foreground", XRF_COLOR_LIST[index])
        return

    def _color_element(self, cell, renderer, model, iter, column):
        index = model.get_path(iter)[0]
        renderer.set_property("foreground", XRF_COLOR_LIST[index])
        return

    def _set_scan_action(self, state):
        if state in [SCAN_START, SCAN_RESUME]:
            self.scanning = True
            self.paused = False
            self.scan_btn.set_label('mxdc-pause-scan')
            self.stop_btn.set_sensitive(True)
        else:
            self.scanning = False
            if state is SCAN_PAUSE:
                self.paused = True
                self.scan_btn.set_label('mxdc-resume-scan')
            else:
                self.paused = False
                self.scan_btn.set_label('mxdc-scan')
                self.scan_btn.set_sensitive(True)
                self.stop_btn.set_sensitive(False)
                self.scan_pbar.set_text('Scan Stopped')

    def clear_xanes_results(self):
        self.energy_store.clear()
        self.energies = []
        self.names = []
        self.scattering_factors = []
        self.create_run_btn.set_sensitive(False)
        self.xanes_box.hide()

    def clear_xrf_results(self):
        self.xrf_store.clear()
        self.xrf_box.hide()
        self.xrf_results = {}
        self.xrf_annotations = {}
        
        
    def set_results(self,results):
        keys = ['peak','infl','remo']  # collect peak infl remo in that order
        for key in keys:
            if key in results.keys():  # all energies are not necessarily present
                self._add_xanes_energy(results[key])
        if len(results.keys()) > 0:
            self.xanes_box.set_sensitive(True)
        return True
    
    def set_parameters(self, params=None):
        if params is None:
            # load defaults
            params = {
                'mode': 'XANES',
                'prefix': 'test_scan',
                'directory': os.environ['HOME'],
                'energy': 12.6580,
                'edge': 'Se-K',
                'time': 0.5,
                'emission': 11.2100,
                'attenuation': 90.0,
            }
        for key in ['prefix','edge']:
            self.entries[key].set_text(params[key])
        for key in ['time','attenuation']:
            self.entries[key].set_text("%0.1f" % params[key])
        self.entries['directory'].set_filename(params['directory'])
        self.entries['energy'].set_text("%0.4f" % params['energy'])
        self._emission = params['emission']
        if params['mode'] == 'XANES':
            self.xanes_btn.set_active(True)
        elif params['mode'] == 'XRF':
            self.xrf_btn.set_active(True)
        elif params['mode'] == 'EXAFS':
            self.exafs_btn.set_active(True)
        return True
        
    def get_parameters(self):
        params = {}
        for key in ['prefix','edge']:
            params[key]  = self.entries[key].get_text().strip()
        for key in ['time','energy','attenuation']:
            params[key] = float(self.entries[key].get_text())
        params['crystal'] = self.active_sample.get('id', '')
        params['directory']   = self.entries['directory'].get_filename()
        if params['directory'] is None:
            params['directory'] = os.environ['HOME']
        if self.xanes_btn.get_active():
            params['mode'] = 'XANES'
        elif self.xrf_btn.get_active():
            params['mode'] = 'XRF'
        elif self.exafs_btn.get_active():
            params['mode'] = 'EXAFS'
        params['emission'] = self._emission
        return params

    def get_run_data(self):
        params = self.get_parameters()
        run_data = {}
        run_data['name'] = params['prefix']
        run_data['directory'] = params['directory']
        run_data['energy'] = self.energies
        run_data['energy_label'] = self.names
        run_data['scattering_factors'] = self.scattering_factors
        run_data['number'] = -1
        return run_data

    def _load_config(self):
        data = config.load_config(SCAN_CONFIG_FILE)
        if data is not None:
            self.set_parameters(data)

    def _save_config(self, parameters):
        config.save_config(SCAN_CONFIG_FILE, parameters)

    
    def run_xanes(self):
        self.xrf_box.hide()
        if self.scanning:
            return True
        self.plotter.clear()
        self.clear_xanes_results()
        scan_parameters = self.get_parameters()
        self._save_config(scan_parameters)
            
        title = scan_parameters['edge'] + " Edge Scan"
        self.plotter.set_labels(title=title, x_label="Energy (keV)", y1_label='Fluorescence Counts')      
        self.xanes_scanner.configure(scan_parameters['edge'], scan_parameters['time'], 
                                     scan_parameters['attenuation'], scan_parameters['directory'],
                                     scan_parameters['prefix'], scan_parameters['crystal'])
        
        self._set_scan_action(SCAN_START)
        self.scan_book.set_current_page(1)
        self.scan_pbar.set_fraction(0.0)
        self.scan_pbar.set_text("Starting MAD scan...")
        self.xanes_scanner.start()
        return True

    def run_exafs(self):
        self.xanes_box.hide()
        self.xrf_box.hide()
        if self.scanning:
            return True
        self.plotter.clear()
        scan_parameters = self.get_parameters()
        self._save_config(scan_parameters)
            
        title = scan_parameters['edge'] + " EXAFS Scan"
        self.plotter.set_labels(title=title, x_label="Energy (keV)", y1_label='Fluorescence Counts')      
        self.exafs_scanner.configure(scan_parameters['edge'], scan_parameters['time'], 
                                     scan_parameters['attenuation'], scan_parameters['directory'],
                                     scan_parameters['prefix'], scan_parameters['crystal'])
        
        self._set_scan_action(SCAN_START)
        self.scan_book.set_current_page(1)
        self.scan_pbar.set_fraction(0.0)
        self.scan_pbar.set_text("Starting EXAFS scan...")
        self.exafs_scanner.start()
        return True
        
    def run_xrf(self):
        self.xanes_box.hide()
        if self.scanning:
            return True
        scan_parameters = self.get_parameters() 
        self._save_config(scan_parameters)
        self.plotter.clear()
        
        self.xrf_scanner.configure(scan_parameters['energy'], scan_parameters['edge'], 
                                   scan_parameters['time'], scan_parameters['attenuation'], 
                                   scan_parameters['directory'], scan_parameters['prefix'],
                                   scan_parameters['crystal'])
        
        self._set_scan_action(SCAN_START)
        self.scan_book.set_current_page(1)
        self.scan_pbar.set_fraction(0.0)
        self.scan_pbar.set_text('Performing Excitation Scan...')
        self.xrf_scanner.start()
        return True
    
    def on_mode_change(self, widget, mode='XANES'):
        self.scan_mode = mode
        if mode == 'XANES':
            self.scan_help.set_markup('Find peak, inflection and remote energies for MAD experiments')
            self.edge_entry.set_editable(False)
            self.edge_entry.set_sensitive(True)
            self.energy_entry.set_sensitive(False)
        elif mode == 'XRF':
            self.scan_help.set_markup('Identify elements present in the sample from their fluorescence')
            self.edge_entry.set_sensitive(False)
            self.energy_entry.set_sensitive(True)
        elif mode == 'EXAFS':
            self.scan_help.set_markup('Perform full EXAFS scan for the selected edge')
            self.edge_entry.set_editable(False)
            self.edge_entry.set_sensitive(True)
            self.energy_entry.set_sensitive(False)
        
        return
    
    def on_stop_activated(self, widget):
        # Stop the scan 
        self.xanes_scanner.stop()
        self.xrf_scanner.stop()
        self.exafs_scanner.stop()
        self.scan_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(False)

    def on_scan_activated(self, widget):
        pars = self.get_parameters()
        if self.scanning:
            # Pause the scan if running
            self.xanes_scanner.pause(True)
            self.xrf_scanner.pause(True)
            self.exafs_scanner.pause(True)
            self._set_scan_action(SCAN_PAUSE)
        elif self.paused:
            self.xanes_scanner.pause(False)
            self.xrf_scanner.pause(False)
            self.exafs_scanner.pause(False)
            self._set_scan_action(SCAN_RESUME)
        else:
            # Start the scan if not running
            if pars['mode'] == 'XANES':
                self.run_xanes()
            elif pars['mode'] == 'XRF':
                self.run_xrf()
            elif pars['mode'] == 'EXAFS':
                self.run_exafs()
    
    def on_edge_selected(self, widget, data):
        vals = data.split(':')
        params = self.get_parameters()
        params['edge'] = vals[0]
        params['energy'] = float(vals[1])
        params['emission'] = float(vals[2])
        self.set_parameters(params)
        return True        
        
    def on_new_scan_point(self, widget, point):
        self.plotter.add_point(point[0], point[1])
        return True
    
    def on_scan_paused(self, widget, state, warning=False):
        if state:
            self.scan_pbar.set_text('Scan Paused')
        else:
            if self.paused:
                self._set_scan_action(SCAN_RESUME)
            self.scan_pbar.set_text('Scan Resuming')
            
        # Build the dialog message
        if warning:
            self._set_scan_action(SCAN_PAUSE)
            msg = "Beam not Available. The scan has been paused and can be resumed once the beam becomes available."
            title = 'Attention Required'
            self.resp = MyDialog(gtk.MESSAGE_WARNING, 
                                         title, msg,
                                         buttons=( ('OK', gtk.RESPONSE_ACCEPT),) )
            self._intervening = False
            response = self.resp()
            if response == gtk.RESPONSE_ACCEPT:
                return 
        return True
    
    def on_scan_stopped(self, widget):
        self._set_scan_action(SCAN_STOP)
        self.scan_pbar.set_text('Scan Stopped')
        return True
    
    def on_scan_error(self, widget, reason):
        self._set_scan_action(SCAN_STOP)
        self.scan_pbar.set_text('Scan Error: %s' % (reason,))
        return True

    def on_scan_done(self, widget):
        self._set_scan_action(SCAN_STOP)
        self.scan_pbar.idle_text('Scan Complete!', 1.0)
        return True
    
    def on_xanes_error(self, obj, reason):
        self._set_scan_action(SCAN_STOP)
        self.scan_pbar.set_text('Scan Error: %s' % (reason,))
        self.output_log.add_text(obj.results.get('log'))
        return True
    
    def on_xanes_done(self, obj):        
        self._set_scan_action(SCAN_STOP)
        self.scan_book.set_current_page(1)
        results = obj.results.get('energies')
        if results is None:
            warning('Error Analysing Scan', 'CHOOCH Analysis of XANES Scan failed')
            return True
        
        self.xanes_box.show()
        new_axis = self.plotter.add_axis(label="Anomalous scattering factors (f', f'')")
        if 'infl' in results.keys():
                self.plotter.axis[0].axvline( results['infl'][1], color='m', linestyle=':', linewidth=1)
        if 'peak' in results.keys():
                self.plotter.axis[0].axvline( results['peak'][1], color='m', linestyle=':', linewidth=1)
        if 'remo' in results.keys():
                self.plotter.axis[0].axvline( results['remo'][1], color='m', linestyle=':', linewidth=1)
        fontpar = {}
        fontpar["family"]="monospace"
        fontpar["size"]=7.5
        info = obj.results.get('text')
        self.plotter.fig.text(0.14,0.7, info,fontdict=fontpar, color='b')

        data = obj.results.get('efs')       
        self.plotter.add_line(data['energy'], data['fpp'], 'r', ax=new_axis)
        self.plotter.add_line(data['energy'], data['fp'], 'g', ax=new_axis, redraw=True)
                
        self.set_results(results)
        self.scan_pbar.idle_text("Scan Complete", 1.0)
        self.output_log.add_text(obj.results.get('log'))
        info_log = '\n---------------------------------------\n\n'
        self.output_log.add_text(info_log)
        self.create_run_btn.set_sensitive(True) 
        try:
	    result = list()
	    result.append(obj.results)
            lims_tools.upload_scan(self.beamline, result)
        except:
            print sys.exc_info()
            _logger.warn('Could not upload scan to MxLIVE.')
        return True
                
    def on_create_run(self, obj):
        self.emit('create-run')

    def on_update_strategy(self, obj):
        if len(self.energies) > 0:
            strategy = {
                'energy': self.energies,
                'energy_label': self.names,
                'scattering_factors': self.scattering_factors,
                }
            self.emit('update-strategy', strategy)
            
    def update_active_sample(self, sample=None):
        if sample is None:
            self.active_sample = {}
        else: 
            self.active_sample = sample
        # always display up to date active crystal
        if self.active_sample:
            txt = '%s [ID:%s]' %(self.active_sample['name'], self.active_sample['id'])
            self.crystal_entry.set_text(txt)
        elif self.active_sample.get('crystal_id'):                                                                          
            txt = '[ID:%s]' % (self.active_sample['crystal_id'])
            self.crystal_entry.set_text(txt)
        else:
            self.crystal_entry.set_text('[ Unknown ]')

    def on_progress(self, widget, fraction, msg):
        if fraction > 0.0:
            _used_time = time.time() - self._start_time
            _tot_time = _used_time/fraction
            eta = _tot_time - _used_time
            eta_format = eta >= 3600 and '%H:%M:%S' or '%M:%S'
            txt = '%s %0.1f%% - ETA %s'% (msg, fraction*100,
                                        time.strftime(eta_format ,time.gmtime(eta)))
            self.scan_pbar.idle_text(txt, fraction)
        elif fraction == 0.0:
            self._start_time = time.time()
        else:
            self.scan_pbar.busy_text(msg)
        return True

    def on_scan_started(self, obj):
        return True
            
    def on_xrf_done(self, obj):
        self.clear_xrf_results()
        self.xrf_box.show()
        
        x = obj.results['data']['energy']
        y = obj.results['data']['counts']
        yc = obj.results['data']['fit']
        self.xrf_results = obj.results['assigned']
        self.plotter.set_labels(title='X-Ray Fluorescence',x_label='Energy (keV)',y1_label='Fluorescence')
        self.scan_book.set_current_page(1)

        self.plotter.add_line(x, y,'b-', label='Exp')
        self.plotter.add_line(x, yc,'k:', label='Fit')
        self.plotter.axis[0].axhline(0.0, color='gray', linewidth=0.5)
        self.output_log.clear()
        
        # get list of elements sorted in descending order of prevalence
        element_list = [(v[0], k) for k,v in obj.results['assigned'].items()]
        element_list.sort()
        element_list.reverse()

        peak_log = "%7s %7s %5s %8s %8s\n" % (
                      "Element",
                      "%Cont",
                      "Trans",
                      "Energy",
                      "Height")
                      
        # Display at most 20 entries in the xrf_list
        count = 0
        for prob, el in element_list:
            if count < 20:
                self._add_xrf_element((el, prob))
                count += 1
            peak_log += 39 * "-" + "\n"
            peak_log += "%7s %7.2f %5s %8s %8s\n" % (el, prob, "", "", "")
            contents = obj.results['assigned'][el]
            for trans,energy,height in contents[1]:
                peak_log += "%7s %7s %5s %8.3f %8.2f\n" % (
                                "", "", trans, energy, height)

        self.output_log.add_text(peak_log)
        self.plotter.axis[0].legend()
        self.plotter.redraw()
        self.scan_pbar.idle_text("Scan complete.", 1.0)
        self._set_scan_action(SCAN_STOP)

        # Upload scan to lims
        lims_tools.upload_scan(self.beamline, [obj.results])

        return True
        
    def on_element_toggled(self, cell, path, model):
        iter = model.get_iter(path)
        index = model.get_path(iter)[0]
        _color = XRF_COLOR_LIST[index]

        element = model.get_value(iter, COLUMN_ELEMENT)                 
        element_info = self.xrf_results.get(element)
        state = model.get_value(iter, COLUMN_DRAW)
        model.set(iter, COLUMN_DRAW, (not state) )
        ax = self.plotter.axis[0]
        ax.axis('tight')
        alims = ax.axis()
        line_list = summarize_lines(element_info[1])
        if state:
            # Delete drawings
            for _anotation in self.xrf_annotations[element]:
                _anotation.remove()
            del self.xrf_annotations[element]
        else:
            # Add Drawings
            self.xrf_annotations[element] = []
            ln_points = []
            for _nm, _pos, _ht in line_list:
                ln_points.extend(([_pos, _pos],[0.0, _ht*0.95]))
                #ax.axvline(_pos, label=_nm)
                txt = ax.text(_pos, -0.5, 
                              "%s-%s" % (element, _nm), 
                              rotation=90, 
                              fontsize=7,
                              horizontalalignment='center',
                              verticalalignment='top',
                              color=_color
                      )
                self.xrf_annotations[element].append(txt)
            lns = ax.plot(*ln_points, **{'linewidth':1.0, 'color':_color})
            self.xrf_annotations[element].extend(lns)
            
        _offset = 0.1 * alims[3]
        ax.axis(ymin=alims[2]-_offset, ymax=alims[3]+_offset)
        self.plotter.redraw()
        return True
                                                             
