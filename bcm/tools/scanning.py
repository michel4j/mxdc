import threading
import gobject
import numpy            
import scipy
import scipy.optimize
from matplotlib.mlab import slopes

from bcm.utils import read_periodic_table, gtk_idle
from bcm.protocols import ca
from bcm.tools.fitting import *
from bcm.devices.detectors import Normalizer


class Error(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message

class ScannerBase(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['new-point'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,gobject.TYPE_FLOAT))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['aborted'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['log'] = ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['error'] = ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
   
    def __init__(self):
        gobject.GObject.__init__(self)
        self.stopped = False
        self.aborted = False
        self.filename = None
        self.relative = False
        self.x_data_points = []
        self.y_data_points = []
        self.plotter = None
        self.plotting = False
        
    def do_new_point(self, x, y):
        if self.plotter is not None:
            self.plotter.add_point(x, y,0)
        return True

    def do_started(self):
        if self.plotter is not None and self.plotting:
            self.plotter.clear()
        
    def log(self, message):
        gobject.idle_add(self.emit, 'log', message)

    def start(self):
        self.stopped = False
        self.aborded = False
        worker_thread = threading.Thread(target=self.run)
        worker_thread.start()

    def stop(self):
        self.stopped = True    

    def abort(self):
        self.aborted = True
    
    def run(self):
        gobject.idle_add(self.emit, "done")
        gobject.idle_add(self.emit, "progress", 1.0 )
           
    def set_relative(self, rel):
        self.relative = rel

    def enable_plotting(self):
        self.plotting = True
    
    def disable_plotting(self):
        self.plotting = False

    def set_plotter(self, plotter=None):
        self.plotter = plotter
        
    def set_normalizer(self, normalizer=None):
        if normalizer:
            self.normalizer = Normalizer(normalizer)
        else:
            self.normalizer = Normalizer()
    
    def set_output(self, filename):
        self.filename = filename
       
class Scanner(ScannerBase):
    def __init__(self):
        ScannerBase.__init__(self)

    def setup(self, positioner, start, end, steps, counter, time, normalizer=None):
        self.positioner = positioner
        self.counter = counter
        self.time = time
        self.steps = steps
        self.start_pos = start
        self.end_pos = end
        self.set_normalizer(normalizer)

    def calc_targets(self):
        assert self.steps > 0
        self.positioner_targets = numpy.linspace(self.range_start,self.range_end,self.steps)
          
    def __call__(self, positioner, start, end, steps, counter, time=1.0, normalizer=None):
        self.setup(positioner, start, end, steps, counter, time)
        self.set_normalizer(normalizer)
        self.run()
        self.fit()
 
     
    def run(self):
        ca.thread_init()
        gobject.idle_add(self.emit, 'started')
        self.log("Scanning '%s' vs '%s' " % (self.positioner.name, self.counter.name))
        if self.relative:
            self.range_start = self.start_pos + self.positioner.get_position()
            self.range_end = self.end_pos + self.positioner.get_position()
        else:
            self.range_start = self.start_pos
            self.range_end = self.end_pos
        self.calc_targets()

        self.normalizer.initialize()
        self.normalizer.set_time(self.time)
        self.normalizer.start()
        
        self.x_data_points = []
        self.y_data_points = []
        
        self.count = 0
        for x in self.positioner_targets:
            if self.stopped or self.aborted:
                self.log( "Scan stopped!" )
                break
                
            self.count += 1
            prev = self.positioner.get_position()                
            self.positioner.move_to(x, wait=True)
            
            y = self.counter.count(self.time)         
            f = self.normalizer.get_factor()         
            y = y * f
            self.x_data_points.append( x )
            self.y_data_points.append( y )          
            fraction = float(self.count) / len(self.positioner_targets)
            
            self.log("%4d %15g %15g %15g" % (self.count, x, y, f))
            gobject.idle_add(self.emit, "new-point", x, y )
            gobject.idle_add(self.emit, "progress", fraction )

            gtk_idle()
             
        self.normalizer.stop()
        if self.aborted:
            gobject.idle_add(self.emit, "aborted")
            gobject.idle_add(self.emit, "progress", 0.0 )
        else:
            self.save()
            gobject.idle_add(self.emit, "done")
            gobject.idle_add(self.emit, "progress", 1.0 )               
        
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
                self.log('Error saving Scan data')

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
        
        self.log("\nMIDP_FIT=%g \nFWHM_FIT=%g \nFWHM_HIS=%g \nYMAX=%g \nXPEAK=%g \n" % (midp,fwhm, fwhm_h, ymax, xpeak)) 
        self.midp_fit, self.fwhm_fit, self.fwhm_his, self.ymax, self.xpeak = (midp,fwhm, fwhm_h, ymax, xpeak)
        return [midp,fwhm,success]

class ExcitationScanner(ScannerBase):
    def __init__(self, beamline):
        ScannerBase.__init__(self)
        self.peaks = []
        self.beamline = beamline
    
    def setup(self, energy, time=1.0, output=None):
        self.time = time
        self.edge_energy = energy
        self.filename = output
        self.beamline.mca.set_cooling(True)
                
    def run(self):
        ca.thread_init()
        gobject.idle_add(self.emit, 'started')
        
        self.beamline.energy.move_to(self.edge_energy, wait=True)
        self.beamline.mca.set_channel_roi()
        
        self.beamline.shutter.open()
        self.x_data_points, self.y_data_points = self.beamline.mca.acquire(t=self.time)
        self.beamline.shutter.close()
        self.peaks = find_peaks(self.x_data_points, self.y_data_points, threshold=0.3,w=20)
        assign_peaks(self.peaks)
        self.save()
        try:
            gobject.idle_add(self.emit, "done")
            gobject.idle_add(self.emit, "progress", 1.0 )

        except:
            self.beamline.shutter.close()
            gobject.idle_add(self.emit, "error")
            gobject.idle_add(self.emit, "progress", 1.0 )
            

    def save(self, filename = None):
        if filename:
            self.filename = filename
        scan_data  = "# Positioner: %s \n" % self.beamline.energy.get_name()
        scan_data += "# Detector: %s \n" % self.beamline.mca.get_name()
        scan_data += "# Detector count time: %0.4f sec \n" % (self.time)
        scan_data += "# \n" 
        scan_data += "# Columns: (%s) \t (%s) \n" % (self.beamline.energy.get_name(), self.beamline.mca.get_name())
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

class MADScanner(ScannerBase):
    def __init__(self, beamline):
        ScannerBase.__init__(self)
        self.beamline = beamline
        self.factor = 1.0
    
    def setup(self, energy, emission, count_time, output):
        self.energy = energy
        self.time = count_time
        self.filename = output
        self.beamline.mca.set_energy(emission)
        self.beamline.mca.set_cooling(True)
        
    def calc_targets(self):
        energy = self.energy
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
            
        self.energy_targets = targets

    def run(self):
        ca.thread_init()
        gobject.idle_add(self.emit, 'started')
        self.x_data_points = []
        self.y_data_points = []
        self.calc_targets()
        if not self.beamline.mca.is_cool():
            self.beamline.mca.set_cooling(True)
        self.beamline.energy.move_to(self.energy, wait=True)   
        
        #self.normalizer = Normalizer(self.beamline.i0)
        #self.normalizer.set_time(self.time)
        #self.normalizer.start()
        
        self.count = 0
        self.beamline.shutter.open()
        for x in self.energy_targets:
            if self.stopped or self.aborted:
                self.log( "Scan stopped!" )
                break
                
            self.count += 1
            prev = self.beamline.bragg_energy.get_position()                
            self.beamline.bragg_energy.move_to(x, wait=True)
            if self.count == 1:
                self.first_intensity = self.beamline.i0.count(0.1)
                self.factor = 1.0
            else:
                self.factor = self.first_intensity/self.beamline.i0.count(0.1)
            y = self.beamline.mca.count(self.time)
            print x, y, y*self.factor, self.factor
                
            # uncomment following line when normalizer is fixed
            y = y * self.factor
            self.x_data_points.append( x )
            self.y_data_points.append( y )
            
            fraction = float(self.count) / len(self.energy_targets)
            self.log("%4d %15g %15g %15g" % (self.count, x, y, self.factor))
            gobject.idle_add(self.emit, "new-point", x, y )
            gobject.idle_add(self.emit, "progress", fraction )

            gtk_idle()
             
        self.beamline.shutter.close()
        self.normalizer.stop()
        
        if self.aborted:
            gobject.idle_add(self.emit, "aborted")
            gobject.idle_add(self.emit, "progress", 0.0 )
        else:
            self.save()
            gobject.idle_add(self.emit, "done")
            gobject.idle_add(self.emit, "progress", 1.0 )

    def save(self, filename=None):
        if filename:
            self.set_output(filename)
        scan_data  = "# Positioner: %s \n" % self.beamline.bragg_energy.get_name()
        scan_data += "# Detector: %s \n" % self.beamline.mca.get_name()
        scan_data += "# Detector count time: %0.4f sec \n" % (self.time)
        scan_data += "# \n" 
        scan_data += "# Columns: (%s) \t (%s) \n" % (self.beamline.bragg_energy.get_name(), self.beamline.mca.get_name())
        for x,y in zip(self.x_data_points, self.y_data_points):
            scan_data += "%15.8g %15.8g \n" % (x, y)

        if self.filename != None:
            try:
                scan_file = open(self.filename,'w')        
                scan_file.write(scan_data)
                scan_file.flush()
                scan_file.close()
            except:
                self.log('Error saving Scan data')
      

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


gobject.type_register(ScannerBase)

scan = Scanner()
scan.enable_plotting()
rscan = Scanner()
rscan.set_relative(True)
rscan.enable_plotting()

