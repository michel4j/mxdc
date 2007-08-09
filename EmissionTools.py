import scipy
import scipy.optimize
from matplotlib.mlab import slopes
from random import *
from PeriodicTable import read_periodic_table


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
    stdev = 0.05 #kev
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
    noise = 0.1
    y = y + noise*(scipy.rand(len(y))-0.5)
    return y

def find_peaks(x, y, w=10, threshold=0.1):
    peaks = []
    ys = smooth(x,y,w,2)
    ny = correct_baseline(x,ys)
    yp = slopes(x, ny)
    ypp = slopes(x, yp)
    yr = max(y) - min(y)
    factor = threshold*get_baseline(x,y).std()
    for i in range(1,len(x)):
        if scipy.sign(yp[i]) < scipy.sign(yp[i-1]):
            if ny[i] > factor:
                peaks.append( [x[i], y[i]] )
    return peaks

def smooth(x, y, w, iterates=1):
    hw = 1 +  w/2
    my = scipy.array(y)
    for count in range(iterates):
        ys = my.copy()
        for i in range(0,hw):
            ys[i] = my[0:hw].mean()
        for i in range(len(x)-hw,len(x)):
            ys[i] = my[len(x)-hw:len(x)].mean()
        for i in range(hw,len(x)-hw):
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

