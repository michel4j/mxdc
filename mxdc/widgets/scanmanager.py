
import os
import gtk
import gtk.glade
import gobject
import numpy

from mxdc.widgets.periodictable import PeriodicTable
from mxdc.widgets.textviewer import TextViewer
from mxdc.widgets.plotter import Plotter
from mxdc.widgets.dialogs import  warning, error
from mxdc.utils import config
from bcm.beamline.mx import IBeamline
from twisted.python.components import globalRegistry
from bcm.engine.spectroscopy import XRFScan, XANESScan
from bcm.utils import science
from bcm.utils.log import get_module_logger
try:
    import json
except:
    import simplejson as json

_logger = get_module_logger('mxdc.scanmanager')

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
(
  COLUMN_LABEL,
  COLUMN_ENERGY,
  COLUMN_FPP,
  COLUMN_FP,
) = range(4)

SCAN_CONFIG_FILE = 'scan_config.json'

class ScanManager(gtk.Frame):
    __gsignals__ = {
        'create-run': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'active-strategy': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, [gobject.TYPE_PYOBJECT,]),
    }
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'scan_manager.glade'), 
                                  'scan_widget')            

        self._create_widgets()

        self.xanes_scanner = XANESScan()
        self.xrf_scanner = XRFScan()
                
        self.xanes_scanner.connect('new-point', self.on_new_scan_point)    
        self.xanes_scanner.connect('done', self.on_xanes_done)
        self.xanes_scanner.connect('stopped', self.on_xanes_done)
        self.xanes_scanner.connect('progress', self.on_progress)    
        self.xanes_scanner.connect('error', self.on_xanes_error)        
        self.xrf_scanner.connect('done', self.on_xrf_done)   
        self.xrf_scanner.connect('stopped', self.on_scan_stopped)
        self.xrf_scanner.connect('error', self.on_scan_error)

        # initial variables
        self.scanning = False
        self.progress_id = None
        self.scan_mode = 'XANES'
        
        # lists to hold results data
        self.energies = []
        self.names = []
        self.scattering_factors = []
        self._load_config()
        #self.xanes_scanner.analyse_file('/home/michel/Downloads/test_scan_Se-K.raw')
    
    def do_create_run(self):
        pass
    
    def do_active_strategy(self, data):
        pass

    def __getattr__(self, key):
        try:
            return super(ScanManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def _create_widgets(self):
        
        self.scan_btn.set_label('mxdc-scan')
        self.scan_btn.connect('clicked', self.on_scan_activated)
        
        # Scan options
        self.xanes_btn.connect('toggled', self.on_mode_change)
        self.entries = {
            'prefix': self.prefix_entry,
            'directory': self.directory_btn,
            'edge': self.edge_entry,
            'energy': self.energy_entry,
            'time': self.time_entry,
            'attenuation': self.attenuation_entry,
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
        self.xanes_vbox.set_sensitive(False)
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
        
        self.show_all()
        self.set_parameters()
   
    def _add_energy(self, item=None): 
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
        
    def _float_format(self, cell, renderer, model, iter, data):
        format, column = data
        value = model.get_value(iter, column)
        renderer.set_property('text', format % value)
        return

    def _set_scan_action(self, state):
        self.scanning = state
        if self.scanning:
            self.scan_btn.set_label('mxdc-stop-scan')
        else:
            self.scan_btn.set_label('mxdc-scan')

    def clear_xanes_results(self):
        self.energy_store.clear()
        self.energies = []
        self.names = []
        self.scattering_factors = []
        self.create_run_btn.set_sensitive(False)
        
    def set_results(self,results):
        keys = ['peak','infl','remo']  # collect peak infl remo in that order
        for key in keys:
            if key in results.keys():  # all energies are not necessarily present
                self._add_energy(results[key])
        self.xanes_vbox.set_sensitive(True)
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
        else:
            self.xrf_btn.set_active(True)
        return True
        
    def get_parameters(self):
        params = {}
        for key in ['prefix','edge']:
            params[key]  = self.entries[key].get_text().strip()
        for key in ['time','energy','attenuation']:
            params[key] = float(self.entries[key].get_text())
        params['directory']   = self.entries['directory'].get_filename()
        if params['directory'] is None:
            params['directory'] = os.environ['HOME']
        if self.xanes_btn.get_active():
            params['mode'] = 'XANES'
        else:
            params['mode'] = 'XRF'
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
                                     scan_parameters['prefix'])
        
        self._set_scan_action(True)
        self.scan_book.set_current_page(1)
        self.scan_pbar.set_fraction(0.0)
        self.scan_pbar.set_text("Starting MAD scan...")
        self.xanes_scanner.start()
        return True
        
    def run_xrf(self):
        if self.scanning:
            return True
        scan_parameters = self.get_parameters() 
        self._save_config(scan_parameters)
        self.plotter.clear()
        
        self.xrf_scanner.configure(scan_parameters['energy'], scan_parameters['time'],  
                                   scan_parameters['attenuation'], scan_parameters['directory'],
                                   scan_parameters['prefix'])
        
        self._set_scan_action(True)
        self.scan_book.set_current_page(1)
        self.scan_pbar.set_fraction(0.0)
        self.scan_pbar.set_text('Performing Excitation Scan...')
        self.xrf_scanner.start()
        return True
    
    def on_mode_change(self, widget):
        if widget.get_active():
            self.scan_help.set_markup('Scan absorption edge to find peak, inflection and remote energies for MAD experiments')
            self.scan_mode = 'XANES'
        else:
            self.scan_help.set_markup('Collect a full spectrum to identify elements present in the sample')
            self.scan_mode = 'XRF'
        return

    def on_scan_activated(self, widget):
        pars = self.get_parameters()
        if self.scanning:
            self.xanes_scanner.stop()
            self.xrf_scanner.stop()
            self._set_scan_action(False)
        else:
            if pars['mode'] == 'XANES':
                self.run_xanes()
            else:
                self.run_xrf()
    
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
    
    def on_scan_stopped(self, widget):
        self._set_scan_action(False)
        self.scan_pbar.set_text('Scan Stopped')
        return True
    
    def on_scan_error(self, widget, reason):
        self._set_scan_action(False)
        self.scan_pbar.set_text('Scan Error: %s' % (reason,))
        return True
    
    def on_xanes_error(self, obj, reason):
        self._set_scan_action(False)
        self.scan_pbar.set_text('Scan Error: %s' % (reason,))
        self.output_log.add_text(obj.results.get('log'))
        return True
    
    def on_xanes_done(self, obj):
        self._set_scan_action(False)
        self.scan_book.set_current_page(1)
        results = obj.results.get('energies')
        
        if results is None:
            warning('Error Analysing Scan', 'CHOOCH Analysis of XANES Scan failed')
            return True
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
        self.scan_pbar.set_fraction(1.0)
        self.scan_pbar.set_text("Scan Complete")
        self.output_log.add_text(obj.results.get('log'))
        info_log = '\n---------------------------------------\n\n'
        self.output_log.add_text(info_log)
        self.create_run_btn.set_sensitive(True) 
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
            self.emit('active-strategy', strategy)

    def on_progress(self, widget, fraction):
        self.scan_pbar.set_fraction(fraction)
        self.scan_pbar.set_text('%0.0f %%' % (fraction * 100))
        return True
                    
    def on_xrf_done(self, obj):
        em_names = {'Ka': r'K$\alpha$', 
                    'Ka1': r'K$\alpha_1$',
                    'Ka2': r'K$\alpha_2$',
                    'Kb': r'K$\beta$',
                    'Kb1': r'K$\beta_1$',
                    'La1': r'L$\alpha 1$'}
        x = obj.data[:,0]
        y = obj.data[:,1]
        self.plotter.set_labels(title='X-Ray Fluorescence',x_label='Energy (keV)',y1_label='Fluorescence')
        self.scan_book.set_current_page(1)
        sy = science.savitzky_golay(y, kernel=31)
        self.plotter.add_line(x, sy,'b-')
        self.output_log.clear()
        peak_log = "#%9s %10s %10s    %s\n" % ('Position',
                                            'Height',
                                            'FWHM',
                                            'Identity')
        peaks = obj.results.get('peaks')
        if peaks is None:
            return
        tick_size = max(y)/50.0
        for peak in peaks:
            if len(peak)> 4:
                el, pk = peak[4].split('-')
                #lbl = '%s-%s' % (el, em_names[pk])
                lbl = '%s-%s' % (el, pk)

                lbls = ', '.join(peak[4:])
            else:
                lbl = '?'
                lbls = ''
            self.plotter.axis[0].plot([peak[0], peak[0]], [peak[1]+tick_size,peak[1]+tick_size*2], 'm-')
            self.plotter.axis[0].text(peak[0], 
                                      peak[1]+tick_size*2.2,
                                      lbl,
                                      horizontalalignment='center', 
                                      color='black', size=9)
            peak_log += "%10.3f %10.3f %10.3f    %s\n" % (peak[0],
                                                        peak[1],
                                                        peak[2],
                                                        lbls)
        self.output_log.add_text(peak_log)
        self.plotter.redraw()
        self.scan_pbar.set_text("Scan complete.")
        self.scan_pbar.set_fraction(1.0)
        self._set_scan_action(False)
        return True
                                                            