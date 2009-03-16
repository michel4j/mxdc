import sys
import os
import gtk
import gtk.glade
import gobject

from mxdc.widgets.periodictable import PeriodicTable
from mxdc.widgets.textviewer import TextViewer
from mxdc.widgets.plotter import Plotter
from mxdc.widgets.dialogs import DirectoryButton
from bcm.beamline.mx import IBeamline
from twisted.python.components import globalRegistry
from bcm.engine.spectroscopy import XRFScan, XANESScan
from bcm.engine import fitting
from bcm.utils import science
from bcm.engine.AutoChooch import AutoChooch
from bcm.utils.log import get_module_logger

_logger = get_module_logger('mxdc.scanmanager')

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
(
  COLUMN_LABEL,
  COLUMN_ENERGY,
  COLUMN_FPP,
  COLUMN_FP,
) = range(4)

class ScanManager(gtk.Frame):
    __gsignals__ = {
            'create-run': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    }
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)

        self._create_widgets()

        self.auto_chooch = AutoChooch()
        self.xanes_scanner = XANESScan()
        self.xrf_scanner = XRFScan()
        
        self.auto_chooch.connect('done', self.on_chooch_done)
        self.auto_chooch.connect('error', self.on_chooch_error)
        
        self.xanes_scanner.connect('new-point', self.on_new_scan_point)    
        self.xanes_scanner.connect('done', self.on_xanes_done)
        self.xanes_scanner.connect('stopped', self.on_scan_stopped)
        self.xanes_scanner.connect('progress', self.on_progress)    
        self.xanes_scanner.connect('error', self.on_scan_error)        
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

    def _register_icons(self):
        items = [('sm-scan', '_Start Scan', 0, 0, None),
                 ('sm-stop', 'S_top Scan', 0, 0, None)]

        # We're too lazy to make our own icons, so we use regular stock icons.
        aliases = [('sm-scan', gtk.STOCK_MEDIA_PLAY),
                   ('sm-stop', gtk.STOCK_STOP) ]

        gtk.stock_add(items)
        factory = gtk.IconFactory()
        factory.add_default()
        for new_stock, alias in aliases:
            icon_set = gtk.icon_factory_lookup_default(alias)
            factory.add(new_stock, icon_set)

    def _create_widgets(self):
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'scan_manager.glade'), 
                                  'scan_widget')            
        self._register_icons()
        self.scan_widget = self._xml.get_widget('scan_widget')
        self.scan_btn = self._xml.get_widget('scan_btn')
        self.scan_btn.set_label('sm-scan')
        self.scan_pbar = self._xml.get_widget('scan_pbar')
        self.scan_btn.connect('clicked', self.on_scan_activated)
        
        # Scan options
        self.xanes_btn = self._xml.get_widget('xanes_btn')
        self.xrf_btn = self._xml.get_widget('xanes_btn')
        self.xanes_btn.connect('toggled', self.on_mode_change)
        self.scan_help = self._xml.get_widget('scan_help')
        self.layout_table = self._xml.get_widget('layout_table')
        self.entries = {
            'prefix': self._xml.get_widget('prefix_entry'),
            'directory': DirectoryButton(),
            'edge': self._xml.get_widget('edge_entry'),
            'energy': self._xml.get_widget('energy_entry'),
            'time': self._xml.get_widget('time_entry'),
            'attenuation': self._xml.get_widget('attenuation_entry'),
        }
        self.layout_table.attach(self.entries['directory'], 1,3, 1,2, xoptions=gtk.EXPAND|gtk.FILL)
        for key in ['prefix','edge']:
            self.entries[key].set_alignment(0.5)
        for key in ['energy','time','attenuation']:
            self.entries[key].set_alignment(1)

        # Notebook 
        self.scan_book = self._xml.get_widget('scan_book')
        pt_frame = self._xml.get_widget('periodic_frame')
        plot_frame = self._xml.get_widget('plot_frame')
        text_view = self._xml.get_widget('output_text')
        self.output_log = TextViewer(text_view)
        
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
            loE, hiE = self.beamline.config['energy_range']
        except:
            self.beamline = None
            loE, hiE = 4.0, 18.0
        self.periodic_table = PeriodicTable(loE, hiE)
        self.periodic_table.connect('edge-selected',self.on_edge_selected)
        self.plotter = Plotter(xformat='%g')
        pt_frame.add(self.periodic_table)
        plot_frame.add(self.plotter)
        self.add(self.scan_widget)

        # XANES Results section
        self.sw = self._xml.get_widget('xanes_sw')
        self.energy_store = gtk.ListStore(
            gobject.TYPE_STRING,
            gobject.TYPE_FLOAT,
            gobject.TYPE_FLOAT,
            gobject.TYPE_FLOAT
        )
        self.energy_list = gtk.TreeView(model=self.energy_store)
        self.energy_list.set_rules_hint(True)
        self.sw.add(self.energy_list)
        self.create_run_btn = self._xml.get_widget('create_run_btn')
        self.xanes_results = self._xml.get_widget('xanes_vbox')
        self.xanes_results.set_sensitive(False)

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
        
    def _float_format(self, cell, renderer, model, iter, data):
        format, column = data
        value = model.get_value(iter, column)
        renderer.set_property('text', format % value)
        return

    def _set_scan_action(self, state):
        self.scanning = state
        if self.scanning:
            self.scan_btn.set_label('sm-stop')
        else:
            self.scan_btn.set_label('sm-scan')

    def clear_xanes_results(self):
        self.energy_store.clear()
        self.energies = []
        self.names = []
        self.create_run_btn.set_sensitive(False)
        
    def set_results(self,results):
        keys = ['peak','infl','remo']  # collect peak infl remo in that order
        for key in keys:
            if key in results.keys():  # all energies are not necessarily present
                self._add_energy(results[key])
        self.xanes_results.set_sensitive(True)
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
        run_data['two_theta'] = 0.0
        return run_data
    
    def run_xanes(self):
        if self.scanning:
            return True
        self.plotter.clear()
        self.clear_xanes_results()
        scan_parameters = self.get_parameters()
            
        title = scan_parameters['edge'] + " Edge Scan"
        self.plotter.set_labels(title=title, x_label="Energy (keV)", y1_label='Fluorescence Counts')      
        self._scan_filename = "%s/%s_%s.raw" % (scan_parameters['directory'],    
            scan_parameters['prefix'], scan_parameters['edge'])
        self.xanes_scanner.configure(scan_parameters['edge'], scan_parameters['time'], scan_parameters['attenuation'])
        
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
        self.plotter.clear()
        
        self._scan_filename = "%s/%s_excite_%s.raw" % (scan_parameters['directory'],    
            scan_parameters['prefix'], scan_parameters['edge'])
        
        self.xrf_scanner.configure(scan_parameters['time'], scan_parameters['energy'], scan_parameters['attenuation'])
        
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
    
    def on_xanes_done(self, widget):
        self.xanes_scanner.save(self._scan_filename)
        self.run_auto_chooch()
        self._set_scan_action(False)
        return True

    def on_scan_stopped(self, widget):
        self._set_scan_action(False)
        self.scan_pbar.set_text('Scan Stopped')
        return True
    
    def on_scan_error(self, widget, reason):
        self._set_scan_action(False)
        self.scan_pbar.set_text('Scan Error: %s' % (reason,))
        return True
    
    def on_chooch_done(self,widget):
        self.scan_book.set_current_page(1)
        data = self.auto_chooch.get_data()
        results = self.auto_chooch.get_results()
        if results is None:
            return True
        new_axis = self.plotter.add_axis(label="Anomalous scattering factors (f', f'')")
        if 'infl' in results.keys():
                self.plotter.axis[0].axvline( results['infl'][1], color='c', linestyle=':', linewidth=1)
        if 'peak' in results.keys():
                self.plotter.axis[0].axvline( results['peak'][1], color='c', linestyle=':', linewidth=1)
        if 'remo' in results.keys():
                self.plotter.axis[0].axvline( results['remo'][1], color='c', linestyle=':', linewidth=1)
        self.plotter.add_line(data[:,0],data[:,1], 'r', ax=new_axis)
        self.plotter.add_line(data[:,0],data[:,2], 'g', ax=new_axis)
        self.plotter.redraw()
                
        self.set_results(results)
        self.scan_pbar.set_fraction(1.0)
        self.scan_pbar.set_text("Scan Complete")
        self.output_log.add_text(self.auto_chooch.output)     
        return True
        
    def on_chooch_error(self,widget, error):
        self.scan_book.set_current_page(2)
        self.scan_pbar.set_text("Chooch Error:  Analysis failed!")
        self.output_log.add_text(self.auto_chooch.output)
        return True
        
    def on_create_run(self,widget):
        self.emit('create-run')

    def on_progress(self, widget, fraction):
        self.scan_pbar.set_fraction(fraction)
        self.scan_pbar.set_text('%0.0f %%' % (fraction * 100))
        return True
                    
    def on_xrf_done(self, obj):
        import pprint
        x = obj.data[:,0]
        y = obj.data[:,1]
        self.plotter.set_labels(title='X-Ray Fluorescence',x_label='Energy (keV)',y1_label='Fluorescence')
        self.scan_book.set_current_page(1)
        tick_size = max(y)/30.0
        peaks = science.peak_search(x, y, threshold=0.05, min_peak=50)
        apeaks = science.assign_peaks(peaks, dev=0.01)
        sy = science.savitzky_golay(y)
        self.plotter.add_line(x,sy,'b-')
        #self.log_view.clear()
        fontpar = {
            "family" :"monospace",
            "size"   : 8
        }
        peak_log = "#%9s %10s %10s    %s\n" % ('Position',
                                            'Height',
                                            'FWHM',
                                            'Identity')
        for peak in apeaks:
            if len(peak)> 4:
                lbl = peak[4]
                lbls = ', '.join(peak[4:])
            else:
                lbl = '?'
                lbls = ''
            self.plotter.axis[0].plot([peak[0], peak[0]], [peak[1]+tick_size,peak[1]+tick_size*2], 'r-')
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
                                    
    def run_auto_chooch(self):
        self.auto_chooch.setup( self.get_parameters() )
        self.scan_pbar.set_text("Analysing scan data ...")
        self.auto_chooch.start()
        return True
                        
gobject.type_register(ScanManager)
