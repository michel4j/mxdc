#!/usr/bin/env python

import gtk, gobject

from ScanControl import ScanControl
from PeriodicTable import PeriodicTable
from LogView import LogView
from Plotter import Plotter
from Scanner import Scanner
from Beamline import beamline
from AutoChooch import AutoChooch
from pylab import load
from Utils import *

class ScanManager(gtk.HBox):
    __gsignals__ = {
            'create-run': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    }
    def __init__(self):
        gtk.HBox.__init__(self,False,6)
        
        self.scan_control = ScanControl()
        self.scan_control.set_border_width(12)
        self.scan_control.start_btn.connect('clicked', self.on_start_scan)
        self.pack_start(self.scan_control, expand=False, fill=False)
        
        self.scan_book = gtk.Notebook()
        self.scan_book.set_border_width(12)
        self.periodic_table = PeriodicTable()
        self.periodic_table.set_border_width(12)
        self.periodic_table_page = self.scan_book.append_page(self.periodic_table, tab_label=gtk.Label('Periodic Table'))
        
        self.plotter = Plotter()
        self.plotter.set_border_width(12)
        self.plotter_page = self.scan_book.append_page(self.plotter, tab_label=gtk.Label('Scan Plot'))
        
        self.log_view = LogView(label='Scan Log')
        self.log_view.set_border_width(12)
        self.log_page = self.scan_book.append_page(self.log_view, tab_label=gtk.Label('Scan Log'))
        self.log_view.set_expanded(True)
        
        self.periodic_table.connect('edge-selected',self.on_edge_selection)
        
        self.pack_start(self.scan_book)

        self.show_all()

        self.bragg_energy = beamline['motors']['energy']
        self.bragg_energy.set_bragg_only(True)        
        self.mca   = beamline['detectors']['mca']

        self.auto_chooch = AutoChooch()
        
        self.scanning = False
            
        
    def on_edge_selection(self, widget, data):
        vals = data.split(':')
        new_data = {}
        new_data['edge'] = vals[0]
        new_data['energy'] = float(vals[1])
        new_data['emission'] = float(vals[2])

        self.scan_control.set_parameters(new_data)
        return True        
        
    def on_new_scan_point(self, widget, x, y):
        self.plotter.add_point(x, y)
        return True
    
    def on_scan_done(self, widget):
        self.scan_control.stop_btn.set_sensitive(False)
        self.scan_control.abort_btn.set_sensitive(False)
        self.scan_control.start_btn.set_sensitive(True)
        self.scan_book.set_current_page( self.log_page )
        self.run_auto_chooch()
        self.scanning = False
        return True

    def on_scan_aborted(self, widget):
        self.scan_control.start_btn.set_sensitive(True)
        self.scan_control.stop_btn.set_sensitive(False)
        self.scan_control.abort_btn.set_sensitive(False)
        self.scanning = False
        return True
    
    def on_chooch_done(self,widget):
        self.scan_control.start_btn.set_sensitive(True)
        self.scan_control.create_run_btn.set_sensitive(True)
        self.scan_book.set_current_page( self.plotter_page )
        data = self.auto_chooch.get_data()
        results = self.auto_chooch.get_results()
        new_axis = self.plotter.add_axis(label="Anomalous scattering factors (f', f'')")
        self.plotter.axis[0].axvline( results['infl'][1], color='c', linestyle=':', linewidth=1)
        self.plotter.axis[0].axvline( results['peak'][1], color='c', linestyle=':', linewidth=1)
        self.plotter.axis[0].axvline( results['remo'][1], color='c', linestyle=':', linewidth=1)
        self.plotter.add_line(data[:,0],data[:,1], 'r', ax=new_axis)
        self.plotter.add_line(data[:,0],data[:,2], 'g', ax=new_axis)
                
        self.scan_control.set_results(results)
        self.scan_control.create_run_btn.connect('clicked', self.on_create_run)
        return True
        
    def on_start_scan(self,widget):        
        pars = self.scan_control.get_parameters()
        if pars['mode'] == 'MAD':
            self.edge_scan()
        else:
            self.excitation_scan()

    def get_run_data(self):
        return  self.scan_control.get_run_data()
        
    def on_create_run(self,widget):
        self.emit('create-run')
        return True
                    
    def generate_scan_targets(self, energy):
        very_low_start = energy - 0.2
        very_low_end = energy - 0.17
        low_start = energy -0.15
        low_end = energy -0.03
        mid_start = low_end
        mid_end = energy + 0.03
        hi_start = mid_end + 0.0015
        hi_end = energy + 0.16
        very_hi_start = energy + 0.18
        very_hi_end = energy + 0.21

        targets = []
        # Add very low points
        targets.append(very_low_start)
        targets.append(very_low_end)
        
        # Decreasing step size for the beginning
        step_size = 0.02
        val = low_start
        while val < low_end:
            targets.append(val)
            step_size -= 0.0015
            val += step_size

        # Fixed step_size for the middle
        val = mid_start
        step_size = 0.001
        while val < mid_end:
            targets.append(val)
            val += step_size
            
        # Increasing step size for the end
        step_size = 0.002
        val = hi_start
        while val < hi_end:
            targets.append(val)
            step_size += 0.0015
            val += step_size
            
        # Add very hi points
        targets.append(very_hi_start)
        targets.append(very_hi_end)
            
        return targets
        
    def edge_scan(self):
        if self.scanning:
            return True
        self.plotter.clear()
        scan_parameters = self.scan_control.get_parameters()
            
        if not check_directory(    scan_parameters['directory'] ):
            return True    
            
        title = scan_parameters['edge'] + " Edge Scan"
        self.plotter.set_labels(title=title, x_label="Energy (keV)", y1_label='Fluorescence')
        energy = scan_parameters['energy']
        
        self.mca.set_roi_energy( scan_parameters['emission'] )
        steps = 100
        count_time = scan_parameters['time']
        scan_filename = "%s/%s_%s.raw" % (scan_parameters['directory'],    
            scan_parameters['prefix'], scan_parameters['edge'])
        self.scanner = Scanner(positioner=self.bragg_energy, detector=self.mca, time=count_time, output=scan_filename)
        self.scanner.set_targets( self.generate_scan_targets(energy) )
        self.scanner.connect('new-point', self.on_new_scan_point)
        self.scanner.connect('done', self.on_scan_done)
        self.scanner.connect('aborted', self.on_scan_aborted)        
        self.connect('destroy', lambda x: self.scanner.stop())
        self.scan_control.stop_btn.connect('clicked', lambda x: self.scanner.stop())
        self.scan_control.abort_btn.connect('clicked', lambda x: self.scanner.abort())
        self.scan_control.stop_btn.set_sensitive(True)
        self.scan_control.abort_btn.set_sensitive(True)
        self.scan_control.start_btn.set_sensitive(False)
        self.scan_book.set_current_page( self.plotter_page )
        self.scanner.start()
        self.scanning = True
        return True
        
    def excitation_scan(self):
        x,y = self.mca.acquire(t=1.0)
        self.plotter.clear()
        self.plotter.set_labels(title='Excitation Scan',x_label='Channel',y1_label='Fluorescence')
        self.plotter.add_line(x,y,'r-')
        self.scan_book.set_current_page( self.plotter_page )
        return True
                
    def run_auto_chooch(self):
        self.auto_chooch = AutoChooch()
        self.auto_chooch.set_parameters( self.scan_control.get_parameters() )
        self.auto_chooch.connect('done', self.on_chooch_done)
        self.auto_chooch.connect('done', lambda x: self.log_view.log( self.auto_chooch.output, False ))
        self.auto_chooch.start()
        return True
                        
gobject.type_register(ScanManager)
