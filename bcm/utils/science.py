from bcm.engine import fitting
from bcm.utils import converter
from bcm.utils import json
from scipy import interpolate, optimize
import numpy
import os
import re

SPACE_GROUP_NAMES = {
    1:'P1', 3:'P2', 4:'P2(1)', 5:'C2', 16:'P222', 
    17:'P222(1)', 18:'P2(1)2(1)2',
    19:'P2(1)2(1)2(1)', 21:'C222', 20:'C222(1)', 22:'F222', 23:'I222',
    24:'I2(1)2(1)2(1)', 75:'P4', 76:'P4(1)', 77:'P4(2)', 78:'P4(3)', 89:'P422',
    90:'P42(1)2', 91:'P4(1)22', 92:'P4(1)2(1)2', 93:'P4(2)22', 94:'P4(2)2(1)2',
    95:'P4(3)22', 96:'P4(3)2(1)2', 79:'I4', 80:'I4(1)', 97:'I422', 98:'I4(1)22',
    143:'P3', 144:'P3(1)', 145:'P3(2)', 149:'P312', 150:'P321', 151:'P3(1)12',
    152:'P3(1)21', 153:'P3(2)12', 154:'P3(2)21', 168:'P6', 169:'P6(1)',
    170:'P6(5)', 171:'P6(2)', 172:'P6(4)', 173:'P6(3)', 177:'P622', 178:'P6(1)22',
    179:'P6(5)22', 180:'P6(2)22', 181:'P6(4)22', 182:'P6(3)22', 146:'R3',
    155:'R32', 195:'P23', 198:'P2(1)3', 207:'P432', 208:'P4(2)32', 212:'P4(3)32',
    213:'P4(1)32', 196:'F23', 209:'F432', 210:'F4(1)32', 197:'I23', 199:'I2(1)3',
    211:'I432', 214:'I4(1)32'             
    }

EMISSIONS_DATA = {}
PERIODIC_TABLE = {}
PEAK_FWHM = 0.1

# load data tables
# Data was compiled from the NIST database
# Emission rates were compiled using the PyMCA tables

EMISSIONS_DATA = json.load(file(os.path.join(os.path.dirname(__file__), 'data','emissions.json')))
PERIODIC_TABLE = json.load(file(os.path.join(os.path.dirname(__file__), 'data', 'periodictable.json')))

def nearest(x, precision):
    return int(numpy.round(x/precision, 0))

def xanes_targets(energy):
    low_start = energy -0.10
    low_end = energy -0.03
    mid_start = low_end
    mid_end = energy + 0.03
    hi_start = mid_end + 0.002
    hi_end = energy + 0.10

    targets = []
    
    # Decreasing step size for the beginning
    step_size = 0.03
    val = low_start
    while val < low_end:
        targets.append(val)
        step_size -= 0.002
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
        step_size += 0.002
        val += step_size
        
        
    return targets

def exafs_targets(energy, start=-0.2, edge=-0.005, exafs=0.006, kmax=14, pe_factor=10.0, e_step=0.0005, k_step=0.05):
    # Calculate energy positions for exafs scans
    
    pre_edge_end = edge
    edge_end = exafs
    exafs_end = kmax
    
    targets = []
    
    # Decreasing step size for the pre-edge
    val = start
    targets.append(val)
    while val < pre_edge_end:
        step_size = abs(val)/(pe_factor)
        val += step_size
        targets.append(val)
    
    # edge region
    while val < edge_end:
        step_size = e_step
        val += step_size
        targets.append(val)
    
    #the exafs region
    kval = converter.energy_to_kspace(val)
    while kval < exafs_end:
        kval += k_step
        targets.append(converter.kspace_to_energy(kval))
            
    return energy + numpy.array(targets)


def exafs_time_func(t, k, n=2, kmin=3.0, kmax=14.0):
    
    if k < kmin: # anything below kmin gets min time = t
        _t = t
    else:
        _t = t + (9.0*t)*((k-kmin)/(kmax-kmin))**n
    return _t
    
def get_periodic_table():
    return PERIODIC_TABLE
   
def get_energy_database():    
    emissions = {
        'K': 'KL3',
        'L1': 'L1M3',
        'L2': 'L2M4',
        'L3': 'L3M4',
        }
    data_dict = {}
    for symbol, db in EMISSIONS_DATA.items():
        for edge, data in db.items():
            edge_descr = "%s-%s" % (symbol, edge)
            if emissions[edge] in data[1]:
                e_val = data[1][emissions[edge]][0]
                val = data[0]
                data_dict[edge_descr] = (val, e_val)
    return data_dict

def savitzky_golay(data, kernel = 9, order = 3, deriv=0):
    """
        applies a Savitzky-Golay filter
        input parameters:
        - data => data as a 1D numpy array
        - kernel => a positiv integer > 2*order giving the kernel size
        - order => order of the polynomal
        - deriv => derivative to return default (smooth only)
        returns smoothed data as a numpy array

        invoke like:
        smoothed = savitzky_golay(<rough>, [kernel = value], [order = value]
    """
    try:
            kernel = abs(int(kernel))
            order = abs(int(order))
    except ValueError:
        raise ValueError("kernel and order have to be of type int (floats will be converted).")
    if kernel % 2 != 1: kernel += 1
    if kernel < 1: kernel = 1

    if kernel < order + 2:
        raise TypeError("kernel is to small for the polynomals\nshould be > order + 2")

    # a second order polynomal has 3 coefficients
    order_range = range(order+1)
    half_window = (kernel -1) // 2
    b = numpy.mat([[k**i for i in order_range] for k in range(-half_window, half_window+1)])
    # since we don't want the derivative, else choose [1] or [2], respectively
    assert deriv <= 2
    m = numpy.linalg.pinv(b).A[deriv]
    window_size = len(m)
    half_window = (window_size-1) // 2

    # precompute the offset values for better performance
    offsets = range(-half_window, half_window+1)
    offset_data = zip(offsets, m)

    smooth_data = list()

    # temporary data, extended with a mirror image to the left and right
    firstval=data[0]
    lastval=data[len(data)-1]
    #left extension: f(x0-x) = f(x0)-(f(x)-f(x0)) = 2f(x0)-f(x)
    #right extension: f(xl+x) = f(xl)+(f(xl)-f(xl-x)) = 2f(xl)-f(xl-x)
    leftpad=numpy.zeros(half_window)+2*firstval
    rightpad=numpy.zeros(half_window)+2*lastval
    leftchunk=data[1:1+half_window]
    leftpad=leftpad-leftchunk[::-1]
    rightchunk=data[len(data)-half_window-1:len(data)-1]
    rightpad=rightpad-rightchunk[::-1]
    data = numpy.concatenate((leftpad, data))
    data = numpy.concatenate((data, rightpad))

    for i in range(half_window, len(data) - half_window):
            value = 0.0
            for offset, weight in offset_data:
                value += weight * data[i + offset]
            smooth_data.append(value)
    return numpy.array(smooth_data)

def smooth_data(data, times=1, window=11, order=1):
    ys = data
    for _ in range(times):
        ys = savitzky_golay(ys, kernel=window, order=order)
    return ys
    
def find_peaks(x, y, w=9, sensitivity=0.01, smooth=True):
    hw = w//3
    if smooth:
        ys = smooth_data(y, times=2, window=w)
    else:
        ys = y
    ypp = savitzky_golay(ys, w, 2, 2)
    ypp[ypp>0] = 0.0
    ypp *= -1
    yp =  savitzky_golay(ypp, 1+w/2, 1, 1)
    peak_patt = "(H{%d}.L{%d})" % (hw-1, hw-1)
    ps = ""
    for v in yp:
        if v == 0.0:
            ps += '-'
        elif v > 0.0:
            ps += 'H'
        else:
            ps += 'L'
    def get_peak(pos):
        return x[pos], y[pos], ypp[pos]
    peak_positions = [get_peak(m.start()+hw-1) for m in re.finditer(peak_patt, ps)]
    ymax = max(ys)
    yppmax = max(ypp)
    peaks = [v[:2] for v in  peak_positions if (v[1] >= sensitivity*ymax and v[2] > 0.5*sensitivity*yppmax)]
    return peaks

def peak_search(x, y, w=7, threshold=0.01, min_peak=0.01):
    # make sure x is in ascending order
    if x[0] > x[-1]:
        x = x[::-1]
        y = y[::-1]
    peaks = []
    t_peaks = []
    ypp = savitzky_golay(y, kernel=w, order=3, deriv=2)
    i = 0
    while i < len(x):  
        # find start of peak
        while -ypp[i] <= 0.0 and i < len(x)-1:
            i +=1
        if i < len(x)-1:
            lo = i
            # lo found, now find hi
            while -ypp[i] > 0.0 and i < (len(x)-1):
                i +=1
            if i < len(x)-1:
                hi = i
                # hi found
                fwhm = x[hi] - x[lo]
                if sum(-ypp[lo:hi]**4) == 0.0:
                    continue
                else:
                    peak_pos = sum(x[lo:hi]*(-ypp[lo:hi]**4))/sum(-ypp[lo:hi]**4)
                stdpk = numpy.std(y[lo:hi])
                pk = lo
                while x[pk] < peak_pos and pk < hi:
                    pk += 1
                peak_height = y[pk]
                t_peaks.append([float(peak_pos), float(peak_height), float(fwhm),  float(stdpk)])
        i += 1

    if len(t_peaks) == 0:
        return []

    pk_heights = numpy.array([v[1] for v in t_peaks])       
    max_y = max(pk_heights)
    std_h = numpy.std(pk_heights)
    std_y = numpy.std(y)
    for peak in t_peaks:
        if peak[2] >= 0.8 * threshold and peak[2] <= 10*threshold and peak[3] > abs(std_h-std_y)*min_peak and peak[1] > min_peak * max_y:
            peaks.append(peak)
    return peaks

def get_candidate_elements(energy):
    """find all edges which can be excited at given energy.
    Returns a list of tuples. Each tuple containing the element
    symbol followed by the edges which are potentially present.  
    
    E.g   [('Se', 'K'), ('Au', 'L3')]
    """
    elements = []
    for symbol, edges in EMISSIONS_DATA.items():
        entry = [symbol,]
        for edge, data in edges.items():
            if data[0] < energy:
                entry.append(edge)
        if len(entry) > 1:
            elements.append(tuple(entry))
    return elements

def get_peak_elements(energy, peaks=[], prec=0.05):
    """find all edges which can be excited at given energy.
    Returns a list of tuples. Each tuple containing the element
    symbol followed by the edges which are potentially present.  
    
    E.g   [('Se', 'K'), ('Au', 'L3')]
    """
    peak_energies = set([nearest(v[0], prec) for v in peaks])
    elements = []
    lonly = []
    for symbol, edges in EMISSIONS_DATA.items():
        entry = [symbol,]
        entry_peaks = []
        for edge, data in edges.items():
            if data[0] > energy: continue
            _fl = [(v[0], v[1], edge) for v in data[1].values()]
            entry_peaks.extend(_fl)
        if len(entry_peaks) > 1:
            entry_peaks.sort(key=lambda v: v[1], reverse=True)
        for pk in entry_peaks:    
            if nearest(pk[0], prec) in peak_energies:
                entry.append(pk[2])
                break
        if len(entry) > 1 :
            elements.append(tuple(entry))
            if 'K' in entry[1:]:
                lonly.append(0.0)
            else:
                lonly.append(1.0)  
    return elements, numpy.array(lonly)
    
def get_line_info(element_info, factor):
    """Get information about emission lines for each element according to
    the coefficients from fitting"""
    el = element_info[0]

    el_peaks = []
    if 'K' in element_info[1:]:
        edges = ['K']
    else:
        edges = element_info[1:]

    for edge in edges:
        edge_data = EMISSIONS_DATA[el][edge]
        for _ln, _pars in edge_data[1].items():
            if factor * _pars[1] > 0.1:
                el_peaks.append((_ln, _pars[0], round(_pars[1]*factor,2)))
    if len(el_peaks) > 0:
        hts = [v[-1] for v in el_peaks]
        if max(hts) > 0.1:
            return el_peaks

    return None
    
def generate_spectrum(info, energy, xa):
    """ Generate a spectrum for a given element and its edges provided as 
    a tuple of the element name followed by it's edeges
    
    xa is an array of energy values
    """
    
    y = numpy.zeros(len(xa))
    
    el = info[0]    
    if not el in EMISSIONS_DATA:
        return y
    
    coeffs = []
    edges = info[1:]
    for edge in edges:
        edge_data = EMISSIONS_DATA[el][edge]
        #if edge in ['L1', 'L2', 'L3']:  continue  # ignore 'L' edges
        for _pos, _ri in edge_data[1].values():
            if _ri >= 0.001 and _pos < energy:
                fwhm = PEAK_FWHM  * (1.0 + _pos/energy) # fwhm increases by energy
                coeffs.extend([_ri, fwhm, _pos, 0.0])
    return fitting.multi_peak(xa, coeffs, target='voigt', fraction=0.2)

def _rebin(a, *args):
    '''rebin ndarray data into a smaller ndarray of the same rank whose dimensions
    are factors of the original dimensions. eg. An array with 6 columns and 4 rows
    can be reduced to have 6,3,2 or 1 columns and 4,2 or 1 rows.
    example usages:
    >>> a=rand(6,4); b=rebin(a,3,2)
    >>> a=rand(6); b=rebin(a,2)
    '''
    shape = a.shape
    lenShape = len(shape)
    factor = numpy.asarray(shape)/numpy.asarray(args)
    evList = ['a.reshape('] + \
             ['args[%d],factor[%d],'%(i,i) for i in range(lenShape)] + \
             [')'] + ['.sum(%d)'%(i+1) for i in range(lenShape)] + \
             ['/factor[%d]'%i for i in range(lenShape)]
    return eval(''.join(evList))

def interprete_xrf(xo, yo, energy, speedup=4):
    
    def calc_template(xa, elements, template=None):
        if template is None:     
            template = numpy.empty((len(xa), len(elements))) # elements + zero
        for i, el in enumerate(elements):
            template[:,i] = generate_spectrum(el, energy, xa)
        return template
    
    def model_err(coeffs, xa, yfunc, template, fixed=None, fixed_pars=None):
        pars = coeffs[:-1]
        #coeffs[-1] = min(1.05, max(0.95, coeffs[-1]))
        pars[pars < 0.0] = 0.0
        xt  = xa #+ coeffs[-1]
        yt = yfunc(xt)
        
        if fixed is not None and fixed_pars is not None:
            pars[fixed] = fixed_pars[fixed]
        
        full_template = template*pars
        yo = full_template.sum(1)
        err = (yt - yo)
        #if fixed is not None:
        #    err[fixed] = 0.01 * err[fixed]
        sel = err < 0
        err[sel] = err[sel]*5
        return err

    peaks = find_peaks(xo, yo, w=15, sensitivity=0.005)
    yo = smooth_data(yo, times=2, window=21)
    elements, lonly = get_peak_elements(energy, peaks, prec=0.1)
    
    # rebin data to speedup calculations
    sz = len(xo)
    sp = 1
    for i in range(1,24):
        if sz % i == 0: sp = i
    xc = _rebin(xo, sz//sp)
    yc = _rebin(yo, sz//sp)
    yfunc = interpolate.interp1d(xc, yc, kind='cubic', fill_value=0.0, copy=False, bounds_error=False)

    coeffs = numpy.zeros((len(elements)+1))
    coeffs[-1] = 1.0 # scale
        
    template = calc_template(xc, elements)
    # Fit K peaks
    k_template = template*numpy.abs(1-lonly)    
    k_coeffs, _ = optimize.leastsq(model_err, coeffs[:], args=(xc, yfunc, k_template), maxfev=25000)
    
    # Fit L peaks keeping K-coefficients constant
    new_coeffs, _ = optimize.leastsq(model_err, k_coeffs[:], args=(xc, yfunc, template, lonly==0.0, k_coeffs) , maxfev=25000)
    final_template = calc_template(xo, elements) * new_coeffs[:-1]
    return elements, final_template, new_coeffs
