import threading
import gtk
import gobject
import numpy            
import scipy
import scipy.optimize
from matplotlib.mlab import slopes
from bcm.utils import read_periodic_table, gtk_idle
from bcm.protocols import ca
from bcm.tools.fitting import *
from bcm.devices.detectors import Normalizer
from mxdc.gui.Plotter import Plotter

class Error(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message

class Scanner(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['new-point'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,gobject.TYPE_FLOAT))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['aborted'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['log'] = ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    
    def __init__(self, positioner=None, start=0, end=0, steps=0, counter=None, time=1.0, output=None, relative=False):
        gobject.GObject.__init__(self)
        self.positioner = positioner
        self.counter = counter
        self.time = time
        self.stopped = False
        self.aborted = False
        self.filename = output
        self.steps = steps
        self.relative = relative
        self.range_start = start
        self.range_end = end
        self.calc_targets()
        self.x_data_points = []
        self.y_data_points = []
        self.plotter = None
        self.normalizer = Normalizer()
        self.waitress = None
        self._win = None

    def _add_point(self, widget, x, y):
        self.plotter.add_point(x, y,0)
        return True
    
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)
            

    def do_log(self, message):
        print message
        
    def __call__(self, positioner, start, end, steps, counter, time=1.0, normalizer=None, plot=False):
        self.positioner = positioner
        self.counter = counter
        self.time = time
        self.steps = steps
        if start == end:
            raise Error('Start and End positions are identical')
        if self.relative:
            self.range_start = start + self.positioner.get_position()
            self.range_end = end + self.positioner.get_position()
        else:
            self.range_start = start
            self.range_end = end
        self.calc_targets()
        self.set_normalizer(normalizer)
        self._check()
        if plot:
            self._run_gui()
        else:
            self._run_plain()
        
    def _check(self):
        self._log("Will scan '%s' from %g to %g with %d intervals" % (self.positioner.name, self.range_start, self.range_end, self.steps))
        self._log("Will count '%s' for %g second(s) at each point" % (self.counter.name, self.time))
    
    def _run_gui(self):
        if self._win:
            self.plotter.clear()
        else:
            self._win = gtk.Window()
            self._win.set_default_size(800,600)
            self._win.set_title("Scanner")
            self.plotter = Plotter()
            self._win.add(self.plotter)
            con = self.connect('new-point', self._add_point)
            self._win.show_all()
        self._do_scan()
        self.fit()
        #self.disconnect(con)

    def _run_plain(self):
        self._do_scan()
        self.fit()

        
    def start(self):
        self.worker_thread = threading.Thread(target=self._do_scan)
        self.worker_thread.start()
        
    def _do_scan(self):
        ca.thread_init()
        self._log("Scanning '%s' vs '%s' " % (self.positioner.name, self.counter.name))
        self.count = 0
        self.normalizer.initialize()
        self.normalizer.set_time(self.time)
        self.normalizer.start()
        if self.waitress:
            self.waitress.wait() # Wait for the waitress
        self.x_data_points = []
        self.y_data_points = []
        for x in self.positioner_targets:
            if self.stopped or self.aborted:
                self._log( "Scan stopped!" )
                break
                
            self.count += 1
            prev = self.positioner.get_position()                

            self.positioner.move_to(x, wait=True)
            
            y = self.counter.count(self.time)
            
            f = self.normalizer.get_factor()
            
            self._log("%4d %15g %15g %15g" % (self.count, x, y, f))
            y = y * f
            self.x_data_points.append( x )
            self.y_data_points.append( y )
            
            fraction = float(self.count) / len(self.positioner_targets)
            gobject.idle_add(self.emit, "new-point", x, y )
            gobject.idle_add(self.emit, "progress", fraction )

            gtk_idle()
             
        self.normalizer.stop()
        if self.aborted:
            gobject.idle_add(self.emit, "aborted")
            gobject.idle_add(self.emit, "progress", 0.0 )
        else:
            #self.save()
            gobject.idle_add(self.emit, "done")
            gobject.idle_add(self.emit, "progress", 1.0 )
                    

    def calc_targets(self):
        if self.steps > 0:
             self.positioner_targets = numpy.linspace(self.range_start,self.range_end,self.steps)
        else:
            self.positioner_targets = []
                
    def set_targets(self, targets):
        self.positioner_targets = targets
    
    def set_normalizer(self, normalizer=None):
        self.normalizer = Normalizer(normalizer)
    
    def stop(self, widget=None):
        self.stopped = True    

    def abort(self, widget=None):
        self.aborted = True    

    def set_output(self, filename):
        self.filename = filename

    def save(self, filename=None):
        if filename:
            self.set_output(filename)
        scan_data  = "# Positioner: %s \n" % self.positioner.get_name()
        scan_data += "# Detector: %s \n" % self.counter.get_name()
        scan_data += "# Detector count time: %0.4f sec \n" % (self.time)
        scan_data += "# \n" 
        scan_data += "# Columns: (%s) \t (%s) \n" % (self.positioner.get_name(), self.counter.get_name())
        for x,y in zip(self.x_data_points, self.y_data_points):
            scan_data += "%15.8g %15.8g \n" % (x, y)

        if self.filename != None:
            try:
                scan_file = open(self.filename,'w')        
                scan_file.write(scan_data)
                scan_file.flush()
                scan_file.close()
            except:
                self._log('Error saving Scan data')

    def fit(self):
        x = numpy.array(self.x_data_points)
        y = numpy.array(self.y_data_points)
        params, success = gaussian_fit(x,y)
        [A, midp, s, yoffset] = params
        (fwhm_h, xpeak, ymax, fwhm_x_left, fwhm_x_right) = histogram_fit(x, y)
        fwhm = s*2.35
        xi = numpy.linspace(min(x), max(x), 100)
        yi = gaussian(xi, params)
        if self.plotter:
            self.plotter.add_line(xi, yi, 'r.')
            #self.plotter.axis[0].axvline(midp, 'r--')
        
        self._log("\nMIDP_FIT=%g \nFWHM_FIT=%g \nFWHM_HIS=%g \nYMAX=%g \nXPEAK=%g \n" % (midp,fwhm, fwhm_h, ymax, xpeak)) 
        self.midp_fit, self.fwhm_fit, self.fwhm_his, self.ymax, self.xpeak = (midp,fwhm, fwhm_h, ymax, xpeak)
        return [midp,fwhm,success]


def emissions_list():
    table_data = read_periodic_table()
    emissions = {
            'K':  'Ka',
            'L1': 'Lg2',
            'L2': 'Lb2',
            'L3': 'Lb1'
    }
    emissions_dict = {}
    for key in table_data.keys():
        for line in emissions.values():
            emissions_dict["%s-%s" % (key,line)] = float(table_data[key][line])
    return emissions_dict

def assign_peaks(peaks):
    stdev = 0.01 #kev
    data = emissions_list()
    for peak in peaks:
        hits = []
        for key in data.keys():
            value = data[key]
            if value == 0.0:
                continue
            score = abs(value - peak[0])/ (2.0 * stdev)
            if abs(value - peak[0]) < 2.0 * stdev:
                hits.append( (score, key, value) )
            hits.sort()
        for score, key,value in hits:
            peak.append("%8s : %8.4f (%8.5f)" % (key,value, score))
    return peaks

def find_peaks(x, y, w=10, threshold=0.1):
    peaks = []
    ys = smooth(y,w,1)
    ny = correct_baseline(x,ys)
    yp = slopes(x, ny)
    ypp = slopes(x, yp)
    yr = max(y) - min(y)
    factor = threshold*get_baseline(x,y).std()
    offset = 1+w/2
    for i in range(offset+1, len(x)-offset):
        p_sect = scipy.mean(yp[(i-offset):(i+offset)])
        sect = scipy.mean(yp[(i+1-offset):(i+1+offset)])
        #if scipy.sign(yp[i]) < scipy.sign(yp[i-1]):
        if scipy.sign(sect) < scipy.sign(p_sect):
            if ny[i] > factor:
                peaks.append( [x[i], ys[i]] )
    return peaks

class ExcitationScanner:
    def __init__(self, positioner, mca, energy, time=1.0, output=None):
        self.mca = mca
        self.energy_motor = positioner
        self.time = time
        self.energy = energy
        self.filename = output
        self.x_data_points = []
        self.y_data_points = []
        self.peaks = []
        
    def __call__(self, *args, **kwargs):
        self.energy_motor.move_to(self.energy, wait=True)
        self.mca.set_channel_roi()
        try:
            self.x_data_points, self.y_data_points = self.mca.acquire(t=self.time)
            self.peaks = find_peaks(self.x_data_points, self.y_data_points, threshold=0.3,w=20)
            assign_peaks(self.peaks)
            self.save()
        except:
            raise Error('Could not run Excitation scan!')

    def set_output(self, filename):
        self.filename = filename

    def save(self, filename = None):
        if filename:
            self.set_output(filename)
        scan_data  = "# Positioner: %s \n" % self.energy_motor.get_name()
        scan_data += "# Detector: %s \n" % self.mca.get_name()
        scan_data += "# Detector count time: %0.4f sec \n" % (self.time)
        scan_data += "# \n" 
        scan_data += "# Columns: (%s) \t (%s) \n" % (self.energy_motor.get_name(), self.mca.get_name())
        for x,y in zip(self.x_data_points, self.y_data_points):
            scan_data += "%15.8g %15.8g \n" % (x, y)
        scan_data += '# Peak Assignments'
        for peak in self.peaks:
            peak_log = "#Peak position: %8.3f keV  Height: %8.2f" % (peak[0],peak[1])
            for ident in peak[2:]:
                peak_log = "%s \n%s" % (peak_log, ident)
            scan_data += peak_log

        if self.filename != None:
            try:
                scan_file = open(self.filename,'w')        
                scan_file.write(scan_data)
                scan_file.flush()
                scan_file.close()
            except:
                print scan_data
        else:
            print scan_data


gobject.type_register(Scanner)
scan = Scanner()
rscan = Scanner(relative=True)

