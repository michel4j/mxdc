import scipy
import scipy.optimize
from matplotlib.mlab import slopes
from random import *
from PeriodicTable import read_periodic_table
import threading
import EPICS as CA
import gobject, gtk
gobject.threads_init()


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

def gaussian(x, coeffs):
    return coeffs[0] * scipy.exp( - ( (x-coeffs[1])/coeffs[2] )**2 )


def gen_spectrum():
    x = scipy.linspace(0,4095,4096)
    y = scipy.zeros( [len(x)] )

    coeffs = [0,0,0]

    # generate peaks in spectrum
    for i in range(10):
        coeffs[0] = randint(3, 20)  # amplitude
        coeffs[1] = randint(20, 4070) # mean
        coeffs[2] = randint(15, 30) # sigma
        y += gaussian(x, coeffs) 
    # add some noise
    noise = 0.001
    y = y + noise*(scipy.rand(len(y))-0.5)
    return y

def find_peaks(x, y, w=10, threshold=0.1):
    peaks = []
    ys = smooth(y,w,1)
    ny = correct_baseline(x,ys)
    yp = slopes(x, ny)
    ypp = slopes(x, yp)
    yr = max(y) - min(y)
    factor = threshold*get_baseline(x,y).std()
    for i in range(1,len(x)):
        if scipy.sign(yp[i]) < scipy.sign(yp[i-1]):
            if ny[i] > factor:
                peaks.append( [x[i], ys[i]] )
    return peaks

def smooth(y, w, iterates=1):
    hw = 1 +  w/2
    my = scipy.array(y)
    for count in range(iterates):
        ys = my.copy()
        for i in range(0,hw):
            ys[i] = my[0:hw].mean()
        for i in range(len(y)-hw,len(y)):
            ys[i] = my[len(y)-hw:len(y)].mean()
        for i in range(hw,len(y)-hw):
            val=my[i-hw:i+hw].mean()
            ys[i] = val
        my = ys
    return ys

def anti_slope(x, y):
    ybl = y.copy()
    ybl[0] = y[0]
    for i in range(1,len(y)):
        ybl[i] = y[i] + ybl[i-1]
    return ybl

def get_baseline(x, y):
    return y -     anti_slope(x, slopes(x,y))
    
def correct_baseline(x, y):
    return anti_slope(x, slopes(x,y))

class ExcitationScanner(gobject.GObject, threading.Thread):
    __gsignals__ = {}
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    def __init__(self, positioner, mca, energy, time=1.0, output=None):
        gobject.GObject.__init__(self)
        threading.Thread.__init__(self)
        self.detector = mca
        self.motor = positioner
        self.time = time
        self.energy = energy
        self.filename = output
        self.x_data_points = []
        self.y_data_points = []
        self.peaks = []
        
    def run(self):
        CA.thread_init()
        self.motor.set_mask([1,1,1])
        #if abs(self.energy - self.motor.get_position()) > 1e-4:
        #    self.motor.move_to(self.energy, wait=True)
        self.detector.set_roi()
        self.x_data_points, self.y_data_points = self.detector.acquire(t=self.time)
        self.peaks = find_peaks(self.x_data_points, self.y_data_points, threshold=0.3,w=15)
        assign_peaks(self.peaks)
        self.save()
        gobject.idle_add(self.emit, "done")

    def set_output(self, filename):
        self.filename = filename

    def save(self, filename = None):
        if filename:
            self.set_output(filename)
        scan_data  = "# Positioner: %s \n" % self.motor.get_name()
        scan_data += "# Detector: %s \n" % self.detector.get_name()
        scan_data += "# Detector count time: %0.4f sec \n" % (self.time)
        scan_data += "# \n" 
        scan_data += "# Columns: (%s) \t (%s) \n" % (self.motor.get_name(), self.detector.get_name())
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
        
gobject.type_register(ExcitationScanner)
