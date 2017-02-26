
from mxdc.beamline.mx import IBeamline
from mxdc.engine.spectroscopy import XRFScan, XANESScan, EXAFSScan
from mxdc.utils import lims_tools
from mxdc.utils.log import get_module_logger
from mxdc.utils import config, gui
from mxdc.widgets import dialogs
from mxdc.widgets.misc import ActiveProgressBar
from mxdc.widgets.periodictable import PeriodicTable
from mxdc.widgets.plotter import Plotter
from mxdc.widgets.textviewer import TextViewer
from twisted.python.components import globalRegistry
from gi.repository import GObject
from gi.repository import Gtk
import os, sys
import time

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
                nm = os.path.commonprefix([a[0], b[0]])
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
        
XRF_COLOR_LIST = ['#4185b4', '#ff7f0e', '#2ca02c', '#ff2627', 
                  '#9467bd', '#c49c94', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
                '#004794', '#885523', '#45663f', '#750300', '#4b2766', '#8c564b', 
                '#dc1a6e', '#252525', '#757500', '#157082']

class ScanManager(Gtk.Alignment):
    __gsignals__ = {
        'create-run': (GObject.SignalFlags.RUN_LAST, None, []),
        'update-strategy': (GObject.SignalFlags.RUN_FIRST, None, [GObject.TYPE_PYOBJECT,]),
    }

    def __init__(self):
        super(ScanManager, self).__init__()
        self._xml = gui.GUIFile(os.path.join(DATA_DIR, 'scan_manager'), 'scan_widget')

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
        sg = Gtk.SizeGroup(Gtk.SizeGroupMode.HORIZONTAL)
        sg.add_widget(self.scan_btn)
        sg.add_widget(self.stop_btn)
        sg.add_widget(self.update_strategy_btn)
        sg.add_widget(self.create_run_btn)
        
        # pbar
        self.scan_pbar = ActiveProgressBar()
        self.vbox3.pack_start(self.scan_pbar, False, False, 0)
        self.xanes_btn.set_active(True)
        
        # Scan options
        self.xanes_btn.connect('toggled', self.on_mode_change, 'XANES')
        self.xrf_btn.connect('toggled', self.on_mode_change, 'XRF')
        self.exafs_btn.connect('toggled', self.on_mode_change, 'EXAFS')
        self.entries = {
            'prefix': self.prefix_entry,
            'directory': dialogs.FolderSelector(self.directory_btn),
            'edge': self.edge_entry,
            'energy': self.energy_entry,
            'time': self.time_entry,
            'attenuation': self.attenuation_entry,
            'crystal': self.crystal_entry,
            'scans': self.scans_entry,
            'kmax': self.kmax_entry,
        }
        #self.layout_table.attach(self.entries['directory'], 1,3, 1,2, xoptions=Gtk.AttachOptions.EXPAND|Gtk.AttachOptions.FILL)
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
        
        # Disable EXAFS is Multi-MCA is not available
        # or MULTI-MCA is available but inactive
        if not self.beamline.registry.get('multi_mca', False):
            self.exafs_btn.set_sensitive(False)
        elif not self.beamline.multi_mca.is_active():
            self.beamline.multi_mca.connect('active', lambda x,y: self.exafs_btn.set_sensitive(y))
        else:
            self.exafs_btn.set_sensitive(True)
            
        self.periodic_table = PeriodicTable(loE, hiE)
        self.periodic_table.connect('edge-selected',self.on_edge_selected)
        self.plotter = Plotter(xformat='%g')
        self.periodic_frame.add(self.periodic_table)
        self.plot_frame.add(self.plotter)
        self.add(self.scan_widget)

        # XANES Results section
        self.energy_store = Gtk.ListStore(
            GObject.TYPE_STRING,
            GObject.TYPE_FLOAT,
            GObject.TYPE_FLOAT,
            GObject.TYPE_FLOAT
        )
        self.energy_list = Gtk.TreeView(model=self.energy_store)
        self.energy_list.set_rules_hint(True)
        self.xanes_sw.add(self.energy_list)
        self.create_run_btn.connect('clicked', self.on_create_run)
        self.update_strategy_btn.connect('clicked', self.on_update_strategy)

        #Label column
        renderer = Gtk.CellRendererText()
        column1 = Gtk.TreeViewColumn('Name', renderer, text=COLUMN_LABEL)
        
        #Energy column
        renderer = Gtk.CellRendererText()
        column2 = Gtk.TreeViewColumn('Energy(keV)', renderer, text=COLUMN_ENERGY)
        column2.set_cell_data_func(renderer, self._float_format, ('%7.4f', COLUMN_ENERGY))

        #FP column
        renderer = Gtk.CellRendererText()
        column3 = Gtk.TreeViewColumn("f'", renderer, text=COLUMN_FP)
        column3.set_cell_data_func(renderer, self._float_format, ('%5.2f', COLUMN_FP))

        #FPP column
        renderer = Gtk.CellRendererText()
        column4 = Gtk.TreeViewColumn('f"', renderer, text=COLUMN_FPP)
        column4.set_cell_data_func(renderer, self._float_format, ('%5.2f', COLUMN_FPP))
        
        self.energy_list.append_column(column1)
        self.energy_list.append_column(column2)
        self.energy_list.append_column(column4)
        self.energy_list.append_column(column3)
        self.xanes_sw.show_all()
        
        # XRF Results section
        self.xrf_store = Gtk.ListStore(
            GObject.TYPE_BOOLEAN,                          
            GObject.TYPE_STRING,
            GObject.TYPE_FLOAT
        )
        self.xrf_list = Gtk.TreeView(model=self.xrf_store)
        self.xrf_list.set_rules_hint(True)
        self.xrf_sw.add(self.xrf_list)
        
        #Toggle column
        renderer = Gtk.CellRendererToggle()
        renderer.connect('toggled', self.on_element_toggled, self.xrf_store)
        column = Gtk.TreeViewColumn('', renderer, active=COLUMN_DRAW)
        column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        column.set_fixed_width(24)

        self.xrf_list.append_column(column)
        
        #Name column
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn('Element', renderer, text=COLUMN_ELEMENT)
        column.set_cell_data_func(renderer, self._color_element, COLUMN_PERCENT)
        self.xrf_list.append_column(column)

        #Percent column
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Reliability (%)", renderer, text=COLUMN_PERCENT)
        column.set_cell_data_func(renderer, self._float_format, ('%5.2f', COLUMN_PERCENT))
        self.xrf_list.append_column(column)
        self.xrf_sw.show_all()

        #fix adjustments
        if self.kmax_adj is None:
            self.kmax_adj = Gtk.Adjustment(12, 1, 18, 1, 1, 0)
            self.kmax_entry.set_adjustment(self.kmax_adj)
            self.scans_adj = Gtk.Adjustment(1, 1, 128, 1, 10, 0)
            self.scans_entry.set_adjustment(self.scans_adj)
        
        self.show_all()
        self.set_parameters()
        
           
    def _add_xanes_energy(self, item=None): 
        itr = self.energy_store.append()        
        self.energy_store.set(itr, 
            COLUMN_LABEL, item[COLUMN_LABEL], 
            COLUMN_ENERGY, item[COLUMN_ENERGY],
            COLUMN_FP, item[COLUMN_FP],
            COLUMN_FPP, item[COLUMN_FPP]
        )
        self.energies.append(item[COLUMN_ENERGY])
        self.names.append(item[COLUMN_LABEL])
        self.scattering_factors.append({'fp':item[COLUMN_FP], 'fpp':item[COLUMN_FPP]})

    def _add_xrf_element(self, item=None): 
        itr = self.xrf_store.append()        
        self.xrf_store.set(itr, 
            COLUMN_DRAW, item[2], 
            COLUMN_ELEMENT, item[0],
            COLUMN_PERCENT, item[1]
        )
        
    def _float_format(self, cell, renderer, model, itr, data):
        fmt, column = data
        value = model.get_value(itr, column)
        index = model.get_path(itr)[0]
        renderer.set_property('text', fmt % value)
        if model == self.xrf_store:
            renderer.set_property("foreground", XRF_COLOR_LIST[index%len(XRF_COLOR_LIST)])
        return

    def _color_element(self, cell, renderer, model, itr, column):
        index = model.get_path(itr)[0]
        renderer.set_property("foreground", XRF_COLOR_LIST[index%len(XRF_COLOR_LIST)])
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
                'directory': config.SESSION_INFO.get('current_path', config.SESSION_INFO['path']),
                'energy': 12.6580,
                'edge': 'Se-K',
                'time': 0.5,
                'emission': 11.2100,
                'attenuation': self.beamline.config['default_attenuation'],
                'scans': 1,
                'kmax': 12,
            }
        for key in ['prefix','edge']:
            self.entries[key].set_text(params[key])
        for key in ['time','attenuation']:
            self.entries[key].set_text("%0.1f" % params[key])
        self.entries['directory'].set_current_folder(params['directory'])
        self.entries['energy'].set_text("%0.4f" % params['energy'])
        self._emission = params['emission']
        self.entries['scans'].set_value(params.get('scans', 1))
        self.entries['kmax'].set_value(params.get('kmax', 12))
        if params['mode'] == 'XANES' and params['mode']:
            self.xanes_btn.set_active(True)
        elif params['mode'] == 'XRF' and params['mode']:
            self.xrf_btn.set_active(True)

        return True
        
    def get_parameters(self):
        params = {}
        for key in ['prefix','edge']:
            params[key]  = self.entries[key].get_text().strip()
        for key in ['time','energy','attenuation']:
            params[key] = float(self.entries[key].get_text())
        params['scans'] = self.entries['scans'].get_value_as_int()
        params['kmax'] = self.entries['kmax'].get_value_as_int()
        params['crystal'] = self.active_sample.get('id', '')
        params['directory']   = self.entries['directory'].get_current_folder()
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
        if not config.SESSION_INFO.get('new', False):
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
                                     scan_parameters['prefix'], crystal=scan_parameters['crystal'],
                                     scans=scan_parameters['scans'],
                                     kmax=scan_parameters['kmax'])
        
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
        
        # if current energy is greater than offset from edge energy, use it
        # otherwise use edge_energy + offset
        # clip everything to be within beamline energy range
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
            self.scans_entry.set_sensitive(False)
            self.kmax_entry.set_sensitive(False)
        elif mode == 'XRF':
            self.scan_help.set_markup('Identify elements present in the sample from their fluorescence')
            self.edge_entry.set_sensitive(False)
            self.energy_entry.set_sensitive(True)
            self.scans_entry.set_sensitive(False)
            self.kmax_entry.set_sensitive(False)
        elif mode == 'EXAFS':
            self.scan_help.set_markup('Perform full EXAFS scan for the selected edge')
            self.edge_entry.set_editable(False)
            self.edge_entry.set_sensitive(True)
            self.energy_entry.set_sensitive(False)
            self.scans_entry.set_sensitive(True)
            self.kmax_entry.set_sensitive(True)
        
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
        if params['mode'] == 'XRF':
            params['energy'] = max(
                              self.beamline.config['energy_range'][0],
                              self.beamline.energy.get_position(),
                              min(float(vals[1]) + self.beamline.config['xrf_energy_offset'], self.beamline.config['energy_range'][1])
                              )
        else:
            params['energy'] = float(vals[1])
        params['emission'] = float(vals[2])
        self.set_parameters(params)      
        
    def on_new_scan_point(self, widget, point):
        self.plotter.add_point(point[0], point[1])
    
    def on_scan_paused(self, widget, state, warning=False):
        if not state and not warning:
            self.scan_pbar.set_text('Scan Resuming')
            self._set_scan_action(SCAN_RESUME)
        else:
            self.scan_pbar.set_text('Scan Paused')
            self._set_scan_action(SCAN_PAUSE)
            
            # Build the dialog message
            if warning:
                msg = "Beam not Available. When the beam is available again, resume your scan." 
                title = 'Attention Required'
                self.resp = dialogs.MyDialog(Gtk.MessageType.WARNING, 
                                             title, msg,
                                             parent=self.get_toplevel(),
                                             buttons=( ('OK', Gtk.ResponseType.ACCEPT),) )
                self._intervening = False
                self.resp()
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
            dialogs.warning('Error Analysing Scan', 'CHOOCH Analysis of XANES Scan failed', parent=self.get_toplevel())
            return True
        
        self.xanes_box.show()
        new_axis = self.plotter.add_axis(label="Anomalous scattering factors (f', f'')")
        if 'infl' in results.keys():
                self.plotter.axis[0].axvline( results['infl'][1], color='#999999', linestyle='--', linewidth=1)
        if 'peak' in results.keys():
                self.plotter.axis[0].axvline( results['peak'][1], color='#999999', linestyle='--', linewidth=1)
        if 'remo' in results.keys():
                self.plotter.axis[0].axvline( results['remo'][1], color='#999999', linestyle='--', linewidth=1)
        fontpar = {}
        fontpar["family"]="monospace"
        fontpar["size"]=7.5
        info = obj.results.get('text')
        self.plotter.fig.text(0.14,0.7, info,fontdict=fontpar, color='k')

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
        self.plotter.clear()
        return True
            
    def on_xrf_done(self, obj):
        self.clear_xrf_results()
        self.xrf_box.show()
        
        x = obj.results['data']['energy']
        y = obj.results['data']['counts']
        yc = obj.results['data']['fit']
        energy = obj.results['parameters']['energy']
        self.xrf_results = obj.results['assigned']
        self.plotter.set_labels(title='X-Ray Fluorescence',x_label='Energy (keV)',y1_label='Fluorescence')
        self.scan_book.set_current_page(1)

        self.plotter.add_line(x, y,'b-', label='Exp')
        self.plotter.add_line(x, yc,'k:', label='Fit')
        self.plotter.axis[0].axhline(0.0, color='gray', linewidth=0.5)
        self.output_log.clear()
        ax = self.plotter.axis[0]
        ax.axis('tight')
        ax.set_xlim((-0.25*self.beamline.config['xrf_energy_offset'], energy+0.25*self.beamline.config['xrf_energy_offset']))
        
        # get list of elements sorted in descending order of prevalence
        element_list = [(v[0], k) for k,v in self.xrf_results.items()]
        element_list.sort()
        element_list.reverse()

        peak_log = "%7s %7s %5s %8s %8s\n" % (
                      "Element",
                      "%Cont",
                      "Trans",
                      "Energy",
                      "Height")
                      
        for index, (prob, el) in enumerate(element_list):
            peak_log += 39 * "-" + "\n"
            peak_log += "%7s %7.2f %5s %8s %8s\n" % (el, prob, "", "", "")
            contents = obj.results['assigned'][el]
            for trans,_nrg,height in contents[1]:
                peak_log += "%7s %7s %5s %8.3f %8.2f\n" % (
                                "", "", trans, _nrg, height)
            if prob < 0.005 * element_list[0][0] or index > 20:
                del self.xrf_results[el] 
                continue
            show = (prob >= 0.1 * element_list[0][0])
            self._add_xrf_element((el, prob, show))
            _color = XRF_COLOR_LIST[index%len(XRF_COLOR_LIST)]
            element_info = self.xrf_results.get(el)
            line_list = summarize_lines(element_info[1])
            ln_points = []
            self.xrf_annotations[el] = []
            for _nm, _pos, _ht in line_list:
                if _pos > energy: continue
                ln_points.extend(([_pos, _pos],[0.0, _ht*0.95]))
                txt = ax.text(_pos, -0.5, 
                              "%s-%s" % (el, _nm), 
                              rotation=90, 
                              fontsize=8,
                              horizontalalignment='center',
                              verticalalignment='top',
                              color=_color
                      )
                self.xrf_annotations[el].append(txt)               
            lns = ax.plot(*ln_points, **{'linewidth':1.0, 'color':_color})            
            self.xrf_annotations[el].extend(lns)
            for antn in self.xrf_annotations[el]:
                antn.set_visible(show)
        ax.axvline(energy, c='#cccccc', ls='--', lw=0.5, label='Excitation Energy')
                   
        self.output_log.add_text(peak_log)
        self.plotter.axis[0].legend()
        self.scan_pbar.idle_text("Scan complete.", 1.0)
        self._set_scan_action(SCAN_STOP)

        # Upload scan to lims
        lims_tools.upload_scan(self.beamline, [obj.results])

        alims = ax.axis()
        _offset = 0.2 * alims[3]
        ax.axis(ymin=alims[2]-_offset, ymax=alims[3]+_offset)
        self.plotter.redraw()
        return True
        
    def on_element_toggled(self, cell, path, model):
        itr = model.get_iter(path)
        index = model.get_path(itr)[0]
        _color = XRF_COLOR_LIST[index%len(XRF_COLOR_LIST)]

        element = model.get_value(itr, COLUMN_ELEMENT)                 
        state = model.get_value(itr, COLUMN_DRAW)
        model.set(itr, COLUMN_DRAW, (not state) )
        if state:
            # Hide drawings
            for _anotation in self.xrf_annotations[element]:
                _anotation.set_visible(False)
        else:
            # Show Drawings
            for _anotation in self.xrf_annotations[element]:
                _anotation.set_visible(True)
        self.plotter.redraw()        
        return True
                                                             
