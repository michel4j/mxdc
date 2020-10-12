import os
import re
import json

import numpy
from mxdc.utils import converter
from scipy import interpolate, optimize, signal
from mxdc.utils import fitting

from mxdc.conf import SHARE_DIR

SPACE_GROUP_NAMES = {
    1: 'P1', 3: 'P2', 4: 'P2(1)', 5: 'C2', 16: 'P222',
    17: 'P222(1)', 18: 'P2(1)2(1)2',
    19: 'P2(1)2(1)2(1)', 21: 'C222', 20: 'C222(1)', 22: 'F222', 23: 'I222',
    24: 'I2(1)2(1)2(1)', 75: 'P4', 76: 'P4(1)', 77: 'P4(2)', 78: 'P4(3)', 89: 'P422',
    90: 'P42(1)2', 91: 'P4(1)22', 92: 'P4(1)2(1)2', 93: 'P4(2)22', 94: 'P4(2)2(1)2',
    95: 'P4(3)22', 96: 'P4(3)2(1)2', 79: 'I4', 80: 'I4(1)', 97: 'I422', 98: 'I4(1)22',
    143: 'P3', 144: 'P3(1)', 145: 'P3(2)', 149: 'P312', 150: 'P321', 151: 'P3(1)12',
    152: 'P3(1)21', 153: 'P3(2)12', 154: 'P3(2)21', 168: 'P6', 169: 'P6(1)',
    170: 'P6(5)', 171: 'P6(2)', 172: 'P6(4)', 173: 'P6(3)', 177: 'P622', 178: 'P6(1)22',
    179: 'P6(5)22', 180: 'P6(2)22', 181: 'P6(4)22', 182: 'P6(3)22', 146: 'R3',
    155: 'R32', 195: 'P23', 198: 'P2(1)3', 207: 'P432', 208: 'P4(2)32', 212: 'P4(3)32',
    213: 'P4(1)32', 196: 'F23', 209: 'F432', 210: 'F4(1)32', 197: 'I23', 199: 'I2(1)3',
    211: 'I432', 214: 'I4(1)32'
}

PEAK_FWHM = 0.1

# load data tables
# Data was compiled from the NIST database
# Emission rates were compiled using the PyMCA tables

with open(os.path.join(SHARE_DIR, 'data', 'emissions.json'), 'r') as handle:
    EMISSIONS_DATA = json.load(handle)

with open(os.path.join(SHARE_DIR, 'data', 'periodictable.json'), 'r') as handle:
    PERIODIC_TABLE = json.load(handle)


def nearest(x, precision):
    return int(numpy.round(x / precision, 0))


def xanes_targets(energy):
    low_start = energy - 0.10
    low_end = energy - 0.03
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
        step_size = abs(val) / (pe_factor)
        val += step_size
        targets.append(val)

    # edge region
    while val < edge_end:
        step_size = e_step
        val += step_size
        targets.append(val)

    # the exafs region
    kval = converter.energy_to_kspace(val)
    while kval < exafs_end:
        kval += k_step
        targets.append(converter.kspace_to_energy(kval))

    return energy + numpy.array(targets)


def exafs_time_func(t, k, n=2, kmin=3.0, kmax=14.0):
    if k < kmin:  # anything below kmin gets min time = t
        _t = t
    else:
        _t = t + (9.0 * t) * ((k - kmin) / (kmax - kmin)) ** n
    return _t


def get_periodic_table():
    return PERIODIC_TABLE


def get_energy_database(min_energy=0, max_energy=1000):
    emissions = {
        'K': 'KL3',
        'L1': 'L1M3',
        'L2': 'L2M4',
        'L3': 'L3M4',
    }
    data_dict = {}
    for symbol, db in list(EMISSIONS_DATA.items()):
        for edge, data in list(db.items()):
            edge_descr = "{}-{}".format(symbol, edge)
            if emissions[edge] in data[1]:
                e_val = data[1][emissions[edge]][0]
                if min_energy <= data[0] <= max_energy:
                    val = data[0]
                    data_dict[edge_descr] = (val, e_val)
    return data_dict


def smooth_data(data, times=1, window=11, order=1):
    ys = data
    for _ in range(times):
        ys = signal.savgol_filter(ys, window, order)
    return ys


def find_peaks_orig(x, y, width=9, sensitivity=0.01, smooth=True):
    hw = width // 3
    hw += (hw%2) + 1
    if smooth:
        ys = smooth_data(y, times=4, window=width)
    else:
        ys = y
    ypp = signal.savgol_filter(ys, width, 2, deriv=2)
    ypp[ypp > 0] = 0.0
    ypp *= -1
    sw = width // 2
    sw += (sw%2) + 1
    yp = signal.savgol_filter(ypp, sw, 1, deriv=1)
    peak_patt = "(H{%d}.L{%d})" % (hw - 1, hw - 1)
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

    peak_positions = [get_peak(m.start() + hw - 1) for m in re.finditer(peak_patt, ps)]
    ymax = max(ys)
    yppmax = max(ypp)
    peaks = [v[:2] for v in peak_positions if (v[1] >= sensitivity * ymax and v[2] > 0.5 * sensitivity * yppmax)]
    return peaks


def find_peaks(x, y, width=9, sensitivity=0.01, smooth=True):
    hw = max(width // 3, 2)
    width += (width%2) + 1
    ys = smooth_data(y, times=4, window=width) if smooth else y
    yfunc = interpolate.interp1d(x, ys, bounds_error=False, fill_value=0.0)
    yp = signal.savgol_filter(ys, width, 1, deriv=1)
    peak_str = numpy.array([True]*hw + [False]*hw).tostring()
    data_str = (yp > 0.0).tostring()
    offset = hw - 1

    def get_peak(pos):
        return x[pos], yfunc(pos)

    peak_positions = [get_peak(m.start() + offset) for m in re.finditer(peak_str, data_str)]
    ymax = max(ys)
    peaks = [v for v in peak_positions if (v[1] >= sensitivity * ymax)]
    return peaks


def find_valleys(x, y, width=9, sensitivity=0.01, smooth=True):
    hw = max(width // 3, 2)
    width += (width%2) + 1
    ys = smooth_data(y, times=4, window=width) if smooth else y
    yfunc = interpolate.interp1d(x, ys, bounds_error=False, fill_value=0.0)
    yp = signal.savgol_filter(ys, width, 1, deriv=1)
    peak_str = numpy.array([False]*hw + [True]*hw).tostring()
    data_str = (yp > 0.0).tostring()
    offset = hw - 1

    def get_peak(pos):
        return x[pos], yfunc(pos)

    peak_positions = [get_peak(m.start() + offset) for m in re.finditer(peak_str, data_str)]
    peaks = [v for v in peak_positions]
    return peaks


def find_peaks_y(y, width=11, sensitivity=0.01, smooth=True):
    ys = smooth_data(y, times=4, window=width) if smooth else y
    yfunc = interpolate.interp1d(numpy.arange(len(ys)), ys)
    width += (width%2) + 1
    yp = signal.savgol_filter(ys, width, 1, deriv=1)

    peak_str = numpy.array([True, True, False, False]).tostring()
    data_str = (yp > 0.0).tostring()

    def get_peak(pos):
        return pos, yfunc(pos)

    peak_positions = [get_peak(m.start() + 1.5) for m in re.finditer(peak_str, data_str)]
    ymax = max(y)
    return [
        v for v in peak_positions if (v[1] >= sensitivity * ymax and v[2])
    ]


def get_peak_elements(energy, peaks=[], prec=0.05):
    """find all edges which can be excited at given energy.
    Returns a list of tuples. Each tuple containing the element
    symbol followed by the edges which are potentially present.  
    
    E.g   [('Se', 'K'), ('Au', 'L3')]
    """
    peak_energies = set([nearest(v[0], prec) for v in peaks])
    elements = []
    lonly = []
    for symbol, edges in list(EMISSIONS_DATA.items()):
        entry = [symbol, ]
        entry_peaks = []
        for edge, data in list(edges.items()):
            if data[0] >= energy: continue
            _fl = [(v[0], v[1], edge) for v in list(data[1].values())]
            entry_peaks.extend(_fl)
        if len(entry_peaks) > 1:
            entry_peaks.sort(key=lambda v: v[1], reverse=True)
        for pk in entry_peaks:
            if nearest(pk[0], prec) in peak_energies:
                entry.append(pk[2])

        if len(entry) > 1:
            elements.append(tuple(entry))
            if 'K' in entry[1:]:
                lonly.append(0.0)
            else:
                lonly.append(1.0)
    return elements, numpy.array(lonly)


def get_line_info(element_info, factor):
    """Get information about _emission lines for each element according to
    the coefficients from fitting"""
    el = element_info[0]

    el_peaks = []
    if 'K' in element_info[1:]:
        edges = ['K']
    else:
        edges = element_info[1:]

    for edge in edges:
        edge_data = EMISSIONS_DATA[el][edge]
        for _ln, _pars in list(edge_data[1].items()):
            if factor * _pars[1] > 0.1:
                el_peaks.append((_ln, _pars[0], round(_pars[1] * factor, 2)))
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
        # if edge in ['L1', 'L2', 'L3']:  continue  # ignore 'L' edges
        for _pos, _ri in list(edge_data[1].values()):
            if _ri >= 0.001 and _pos < energy:
                fwhm = PEAK_FWHM * (1.0 + _pos / energy)  # fwhm increases by energy
                coeffs.extend([_ri, fwhm, _pos, 0.0])
    return fitting.multi_peak(xa, coeffs, target='voigt', fraction=0.2)


def interprete_xrf(xo, yo, energy, speedup=4):
    def calc_template(xa, elements, template=None):
        if template is None:
            template = numpy.empty((len(xa), len(elements)))  # elements + zero
        for i, el in enumerate(elements):
            template[:, i] = generate_spectrum(el, energy, xa)
        return template

    def model_err(coeffs, xa, yfunc, template, fixed=None, fixed_pars=None):
        pars = coeffs[:-1]
        # coeffs[-1] = min(1.05, max(0.95, coeffs[-1]))
        pars[pars < 0.0] = 0.0
        xt = xa  # + coeffs[-1]
        yt = yfunc(xt)

        if fixed is not None and fixed_pars is not None:
            pars[fixed] = fixed_pars[:-1][fixed]

        full_template = template * pars
        yo = full_template.sum(1)
        err = (yt - yo)
        # if fixed is not None:
        #    err[fixed] = 0.01 * err[fixed]
        sel = err < 0
        err[sel] = err[sel] * 5
        return err

    peaks = find_peaks_orig(xo, yo, width=21, sensitivity=0.005)
    yo = smooth_data(yo, times=3, window=11)
    elements, lonly = get_peak_elements(energy, peaks, prec=0.1)

    # rebin data to speedup calculations
    sz = len(xo)
    sp = 1
    for i in range(1, 24):
        if sz % i == 0: sp = i
    yfunc = interpolate.interp1d(xo, yo, kind='cubic', fill_value=0.0, copy=False, bounds_error=False)
    xc = numpy.linspace(xo.min(), xo.max(), 1+ sz//sp)

    coeffs = numpy.zeros((len(elements) + 1))
    coeffs[-1] = 1.0  # scale

    template = calc_template(xc, elements)
    # Fit K peaks
    k_template = template * numpy.abs(1 - lonly)
    k_coeffs, _ = optimize.leastsq(model_err, coeffs[:], args=(xc, yfunc, k_template), maxfev=25000)

    # Fit L peaks keeping K-coefficients constant
    new_coeffs, _ = optimize.leastsq(
        model_err, k_coeffs[:], args=(xc, yfunc, template, lonly==0.0, k_coeffs),
        maxfev=25000
    )
    final_template = calc_template(xo, elements) * new_coeffs[:-1]
    return elements, final_template, new_coeffs
