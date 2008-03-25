from mxdc.gui.Plotter import Plotter
from bcm.tools.fitting import *
from bcm.devices.detectors import Normalizer
import threading
import gtk, gobject
from bcm.protocols import ca
import numpy            

gobject.threads_init()
 
class Scanner(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['new-point'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,gobject.TYPE_FLOAT))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['aborted'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['log'] = ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    
    def __init__(self, positioner=None, start=0, end=0, steps=0, counter=None, time=1.0, output=None):
        gobject.GObject.__init__(self)
        self.positioner = positioner
        self.counter = counter
        self.time = time
        self.stopped = False
        self.aborted = False
        self.filename = output
        self.steps = steps
        self.range_start = start
        self.range_end = end
        self.calc_targets()
        self.x_data_points = []
        self.y_data_points = []
        self.plotter = None
        self.normalizer = Normalizer()
        self.waitress = None
        self._connections = []

    def _add_point(self, widget, x, y):
        self.plotter.add_point(x, y,0)
        return True
    
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)
            
    def _done(self, widget):
        self.fit()
        while self._connections:
            self.disconnect( self._connections.pop() )

    def do_log(self, message):
        print message
        
    def __call__(self, positioner=None, start=0, end=0, steps=0, counter=None, time=1.0, output=None, normalizer=None):
        self.positioner = positioner
        self.counter = counter
        self.time = time
        self.filename = output
        self.steps = steps
        self.range_start = start
        self.range_end = end
        self.calc_targets()
        self.set_normalizer(normalizer)
        win = gtk.Window()
        win.set_default_size(800,600)
        win.set_border_width(2)
        win.set_title("Scanner")
        self.plotter = Plotter()
        win.add(self.plotter)
        win.show_all()
        con = self.connect('done', self._done)
        self._connections.append(con)
        con = self.connect('new-point', self._add_point)
        self._connections.append(con)    
        self.start()
        
    
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
            
            self._log("%8d %8g %8g %8g" % (self.count, x, y, f))
            y = y * f
            self.x_data_points.append( x )
            self.y_data_points.append( y )
            
            fraction = float(self.count) / len(self.positioner_targets)
            gobject.idle_add(self.emit, "new-point", x, y )
            gobject.idle_add(self.emit, "progress", fraction )
             
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

gobject.type_register(Scanner)
scan = Scanner()
