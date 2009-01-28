import threading
import gobject
import numpy, math           
import scipy
import scipy.optimize
from matplotlib.mlab import slopes

from bcm.utils.utils import read_periodic_table, gtk_idle
from bcm.protocol import ca
from bcm.engine.fitting import *
import logging

__log_section__ = 'bcm.scans'
scan_logger = logging.getLogger(__log_section__)

class ScanError(Exception):
    """Scan Error."""

class ScannerBase(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['new-point'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,gobject.TYPE_FLOAT))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['aborted'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
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
        ca.threads_init()
        gobject.idle_add(self.emit, 'started')
        scan_logger.info("Scanning '%s' vs '%s' " % (self.positioner.name, self.counter.name))
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
                scan_logger.info( "Scan stopped!" )
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
            
            scan_logger.info("%4d %15g %15g %15g" % (self.count, x, y, f))
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
                scan_logger.error('Unable to saving Scan data to "%s".' % (self.filename,))

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
        
        scan_logger.info("\nMIDP_FIT=%g \nFWHM_FIT=%g \nFWHM_HIS=%g \nYMAX=%g \nXPEAK=%g \n" % (midp,fwhm, fwhm_h, ymax, xpeak)) 
        self.midp_fit, self.fwhm_fit, self.fwhm_his, self.ymax, self.xpeak = (midp,fwhm, fwhm_h, ymax, xpeak)
        return [midp,fwhm,success]



gobject.type_register(ScannerBase)

scan = Scanner()
scan.enable_plotting()
rscan = Scanner()
rscan.set_relative(True)
rscan.enable_plotting()

