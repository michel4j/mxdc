#!/usr/bin/env python

import gtk, gobject, numpy, sys

from ScanControl import ScanControl
from PeriodicTable import PeriodicTable
from LogView import LogView
from Plotter import Plotter
from Scanner import Scanner
from Beamline import beamline
from AutoChooch import AutoChooch
from pylab import load
from Dialogs import *
from EmissionTools import *

class ScanManager(gtk.HBox):
    __gsignals__ = {
            'create-run': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    }
    def __init__(self):
        gtk.HBox.__init__(self,False,6)
        
        self.scan_control = ScanControl()
        self.scan_control.set_border_width(12)
        self.scan_control.start_btn.connect('clicked', self.on_start_scan)
        self.scan_control.create_run_btn.connect('clicked', self.on_create_run)
        self.scan_control.create_run_btn.set_sensitive(False)
        self.pack_start(self.scan_control, expand=False, fill=False)
        
        self.scan_book = gtk.Notebook()
        self.scan_book.set_border_width(12)
        self.periodic_table = PeriodicTable()
        self.periodic_table.set_border_width(12)
        self.periodic_table_page = self.scan_book.append_page(self.periodic_table, tab_label=gtk.Label('Periodic Table'))
        
        self.plotter = Plotter()
        self.plotter.set_border_width(12)
        self.plotter_page = self.scan_book.append_page(self.plotter, tab_label=gtk.Label('Scan Plot'))
        
        self.log_view = LogView(label='Log')
        self.log_view.set_border_width(12)
        self.log_page = self.scan_book.append_page(self.log_view, tab_label=gtk.Label('Output Log'))
        self.log_view.set_expanded(True)
        
        self.periodic_table.connect('edge-selected',self.on_edge_selection)
        
        self.pack_start(self.scan_book)

        self.show_all()
        
        self.bragg_energy = beamline['motors']['bragg_energy']      
        self.mca   = beamline['detectors']['mca']
        self.shutter = beamline['shutters']['xbox_shutter']

        self.auto_chooch = AutoChooch()
        
        self.scanning = False
        self.scanner = None
        self.progress_id = None
                    
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
        self.bragg_energy.set_mask( [1,1,1] )  # Move all
        self.shutter.close()
        self.scan_control.stop_btn.set_sensitive(False)
        self.scan_control.abort_btn.set_sensitive(False)
        self.scan_control.start_btn.set_sensitive(True)
        #self.scan_book.set_current_page( self.log_page )
        self.run_auto_chooch()
        self.scanning = False
        return True

    def on_scan_aborted(self, widget):
        self.bragg_energy.set_mask( [1,1,1] )  # Move all
        self.shutter.close()
        self.scan_control.start_btn.set_sensitive(True)
        self.scan_control.stop_btn.set_sensitive(False)
        self.scan_control.abort_btn.set_sensitive(False)
        self.scanning = False
        self.scan_control.progress_bar.idle_text('Scan Aborted', 0.0)
        return True
    
    def on_chooch_done(self,widget):
        self.scan_control.start_btn.set_sensitive(True)
        self.scan_book.set_current_page( self.plotter_page )
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
                
        self.scan_control.set_results(results)
        self.scan_control.create_run_btn.set_sensitive(True)
        self.scan_control.progress_bar.idle_text("Scan Complete", 1.0)
        return True
        
    def on_chooch_error(self,widget, error):
        self.scan_control.start_btn.set_sensitive(True)
        self.scan_book.set_current_page( self.plotter_page )
        self.scan_control.progress_bar.idle_text("Scan Error:  analysis failed!")
        return True

    def on_start_scan(self,widget):        
        pars = self.scan_control.get_parameters()
        self.mca.set_cooling(True)
        if pars['mode'] == 'MAD':
            self.edge_scan()
        else:
            self.excitation_scan()

    def get_run_data(self):
        return  self.scan_control.get_run_data()
        
    def on_create_run(self,widget):
        self.emit('create-run')

    def on_progress(self, widget, fraction):
        self.scan_control.progress_bar.set_complete(fraction)
        return True
                    
    def linear_scan_targets(self,energy):
        targets = numpy.arange(energy-0.1,energy+0.1,0.001)
        return targets
        
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
        self.scan_control.clear()
        scan_parameters = self.scan_control.get_parameters()
            
        if not check_folder( scan_parameters['directory'], None ):
            return False    
        
        title = scan_parameters['edge'] + " Edge Scan"
        self.plotter.set_labels(title=title, x_label="Energy (keV)", y1_label='Fluorescence')
        energy = scan_parameters['energy']
        self.mca.set_roi_energy( scan_parameters['emission'] )
        count_time = scan_parameters['time']
        scan_filename = "%s/%s_%s.raw" % (scan_parameters['directory'],    
            scan_parameters['prefix'], scan_parameters['edge'])
        
        #move to peak energy and optimize
        beamline['motors']['energy'].move_to( energy )
            
        #Optimize beam here
        self.bragg_energy.set_mask( [1,0,0] )  # Move only bragg
        
        self.scanner = Scanner(positioner=self.bragg_energy, detector=self.mca, time=count_time, output=scan_filename)
        self.scanner.set_targets( self.generate_scan_targets(energy) )
        self.scanner.set_normalizer(beamline['detectors']['i1_bpm'])
        #self.scanner.set_targets( self.linear_scan_targets(energy) )
        self.scanner.connect('new-point', self.on_new_scan_point)
        self.scanner.connect('done', self.on_scan_done)
        self.scanner.connect('aborted', self.on_scan_aborted)        
        self.scanner.connect('progress', self.on_progress)
        self.scan_control.stop_btn.connect('clicked', self.scanner.stop)
        self.scan_control.abort_btn.connect('clicked', self.scanner.abort)
        self.scan_control.stop_btn.set_sensitive(True)
        self.scan_control.abort_btn.set_sensitive(True)
        self.scan_control.start_btn.set_sensitive(False)
        self.scan_book.set_current_page( self.plotter_page )
        self.scan_control.progress_bar.set_complete(0.0)
        self.scan_control.progress_bar.busy_text("Starting MAD scan...")
        self.shutter.open()
        self.scanner.waitress = beamline['motors']['energy']
        self.scanner.start()
        self.scanning = True
        return True
        
    def excitation_scan(self):
        scan_parameters = self.scan_control.get_parameters() 
        count_time = scan_parameters['time']
        energy = scan_parameters['energy']
        self.plotter.clear()
        self.scan_control.clear()
        scan_filename = "%s/%s_excite_%s.raw" % (scan_parameters['directory'],    
            scan_parameters['prefix'], scan_parameters['edge'])
        self.ex_scanner = ExcitationScanner(self.bragg_energy, self.mca, energy, count_time, scan_filename)
        self.ex_scanner.connect('done', self.on_excitation_done)
        self.ex_scanner.connect('error', self.on_scan_aborted)
        
        self.shutter.open()
        self.scan_control.start_btn.set_sensitive(False)
        self.ex_scanner.start()
        self.scan_control.progress_bar.busy_text('Performing Excitation Scan...')
        return True

    def on_excitation_done(self, object):
        self.shutter.close()
        self.scan_control.start_btn.set_sensitive(True)
        x = object.x_data_points
        y = smooth(object.y_data_points, 20,1)
        self.plotter.set_labels(title='Excitation Scan',x_label='Energy (keV)',y1_label='Fluorescence')
        self.plotter.add_line(x,y,'r-')
        self.scan_book.set_current_page( self.plotter_page )
        maxy = max(y)
        tick_size = maxy/30.0
        peaks = object.peaks
        self.log_view.clear()
        fontpar = {
            "family" :"monospace",
            "size"   : 8
        }
        
        for i in range(len(peaks)):
            peak = peaks[i]
            #self.plotter.axis[0].plot([peak[0], peak[0]], [maxy+tick_size*2,maxy+tick_size*3], 'g-')
            self.plotter.axis[0].text(peak[0], peak[1]+tick_size*1.5,'%d' % (i+1), horizontalalignment='center', color='green', size=8)
            peak_log = "Peak #%d: %8.3f keV  Height: %8.2f" % (i+1, peak[0],peak[1])
            for ident in peak[2:]:
                peak_log = "%s \n%s" % (peak_log, ident)
            self.log_view.log( peak_log, False )
        self.plotter.canvas.draw()
        self.scan_control.progress_bar.idle_text("Scan complete.", 1.0)
        return True
        
        
    def stop(self, object=None, event=None):
        if self.scanner is not None:
            self.scanner.stop()
                            
    def run_auto_chooch(self):
        self.auto_chooch = AutoChooch()
        self.auto_chooch.set_parameters( self.scan_control.get_parameters() )
        self.auto_chooch.connect('done', self.on_chooch_done)
        self.auto_chooch.connect('error', self.on_chooch_error)
        self.auto_chooch.connect('done', lambda x: self.log_view.log( self.auto_chooch.output, False ))       
        self.auto_chooch.connect('error', lambda x: self.log_view.log( self.auto_chooch.output, False ))
        self.scan_control.progress_bar.busy_text("Analysing scan data ...")
        self.auto_chooch.start()
        return True
                        
gobject.type_register(ScanManager)

def main():
    gtk.window_set_auto_startup_notification(True)    
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_title("MX Data Collector Demo")
    scan_manager = ScanManager()
    win.add(scan_manager)
    win.show_all()
    try:
        gtk.main()
    finally:
        scan_manager.stop()
        sys.exit()
    
if __name__ == "__main__":
    import hotshot
    import hotshot.stats
    prof = hotshot.Profile("test.prof")
    benchtime = prof.runcall(main)
    prof.close()
    stats = hotshot.stats.load("test.prof")
    stats.strip_dirs()
    stats.sort_stats('time','calls')
    stats.print_stats(100)
