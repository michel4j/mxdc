import gtk, gobject, numpy, sys

from ScanControl import ScanControl
from PeriodicTable import PeriodicTable
from LogView import LogView
from Plotter import Plotter
from Dialogs import *
from bcm.tools.scanning import MADScanner, ExcitationScanner
from bcm.tools.AutoChooch import AutoChooch

class ScanManager(gtk.HBox):
    __gsignals__ = {
            'create-run': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    }
    def __init__(self, beamline=None):
        gtk.HBox.__init__(self,False,6)
        self.beamline = beamline
        
        self.scan_control = ScanControl()
        self.scan_control.set_border_width(12)
        self.scan_control.start_btn.connect('clicked', self.on_start_scan)
        self.scan_control.create_run_btn.connect('clicked', self.on_create_run)
        self.scan_control.create_run_btn.set_sensitive(False)
        self.pack_start(self.scan_control, expand=False, fill=False)
        
        self.scan_book = gtk.Notebook()
        self.scan_book.set_border_width(12)
        if self.beamline is not None:
            loE, hiE = self.beamline.config['energy_range']
        else:
            loE, hiE = 4.0, 18.0
        self.periodic_table = PeriodicTable(loE, hiE)
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

        self.auto_chooch = AutoChooch()
        self.mad_scanner = MADScanner(self.beamline)
        self.ex_scanner = ExcitationScanner(self.beamline)
        
        self.auto_chooch.connect('done', self.on_chooch_done)
        self.auto_chooch.connect('error', self.on_chooch_error)
        
        self.mad_scanner.connect('new-point', self.on_new_scan_point)
        self.mad_scanner.connect('done', self.on_scan_done)
        self.mad_scanner.connect('aborted', self.on_scan_aborted)        
        self.mad_scanner.connect('progress', self.on_progress)
        self.scan_control.stop_btn.connect('clicked', self.mad_scanner.stop)
        self.scan_control.abort_btn.connect('clicked', self.mad_scanner.abort)
       
        self.ex_scanner.connect('done', self.on_excitation_done)
        self.ex_scanner.connect('error', self.on_scan_aborted)

        self.scanning = False
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
        self.scan_control.stop_btn.set_sensitive(False)
        self.scan_control.abort_btn.set_sensitive(False)
        self.scan_control.start_btn.set_sensitive(True)
        self.run_auto_chooch()
        self.scanning = False
        return True

    def on_scan_aborted(self, widget):
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
        self.log_view.log( self.auto_chooch.output, False )     

        return True
        
    def on_chooch_error(self,widget, error):
        self.scan_control.start_btn.set_sensitive(True)
        self.scan_book.set_current_page( self.plotter_page )
        self.scan_control.progress_bar.idle_text("Scan Error:  analysis failed!")
        self.log_view.log( self.auto_chooch.output, False )
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

    def on_progress(self, widget, fraction):
        self.scan_control.progress_bar.set_complete(fraction)
        return True
                    
        
    def edge_scan(self):
        if self.scanning:
            return True
        self.plotter.clear()
        self.scan_control.clear()
        scan_parameters = self.scan_control.get_parameters()
            
        title = scan_parameters['edge'] + " Edge Scan"
        self.plotter.set_labels(title=title, x_label="Energy (keV)", y1_label='Fluorescence')
        
        energy = scan_parameters['energy']
        emission = scan_parameters['emission']
        count_time = scan_parameters['time']
        scan_filename = "%s/%s_%s.raw" % (scan_parameters['directory'],    
            scan_parameters['prefix'], scan_parameters['edge'])
        
        self.mad_scanner.setup(energy, emission, count_time, scan_filename)
        
        self.scan_control.stop_btn.set_sensitive(True)
        self.scan_control.abort_btn.set_sensitive(True)
        self.scan_control.start_btn.set_sensitive(False)
        
        self.scan_book.set_current_page( self.plotter_page )
        
        self.scan_control.progress_bar.set_complete(0.0)
        self.scan_control.progress_bar.busy_text("Starting MAD scan...")

        self.mad_scanner.start()
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
        
        self.ex_scanner.setup(energy, count_time, scan_filename)
        
        self.scan_control.start_btn.set_sensitive(False)
        self.ex_scanner.start()
        self.scan_control.progress_bar.busy_text('Performing Excitation Scan...')
        return True

    def on_excitation_done(self, object):

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
        if self.mad_scanner is not None:
            self.mad_scanner.stop()
                            
    def run_auto_chooch(self):
        self.auto_chooch.setup( self.scan_control.get_parameters() )
        self.scan_control.progress_bar.busy_text("Analysing scan data ...")
        self.auto_chooch.start()
        return True
                        
gobject.type_register(ScanManager)

def main():
    from bcm.beamline import PX
    gtk.window_set_auto_startup_notification(True)    
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_title("MX Data Collector Demo")
    bl = PX('08id1.conf')
    bl.setup()
    scan_manager = ScanManager(bl)
    win.add(scan_manager)
    win.show_all()
    try:
        gtk.main()
    finally:
        scan_manager.stop()
        sys.exit()
    
if __name__ == "__main__":
    main()