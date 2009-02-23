# -*- coding: utf-8 -*-
"""Science Utilities."""

import os
import sys
import numpy

def xanes_targets(energy):
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

def get_periodic_table():
    table_data = {}
    data = PERIODIC_TABLE.split('\n')
    keys = data[0].split()
    for line in data[1:] :
        vals = line.split()
        table_data[vals[1]] = {}
        for (key,val) in zip(keys,vals):
            table_data[vals[1]][key] = val
    return table_data
   
def get_energy_database():
    table_data = get_periodic_table()
    emissions = {
            'K':  'Ka',
            'L1': 'Lg2',
            'L2': 'Lb2',
            'L3': 'Lb1'
    }
    data_dict = {}
    for key in table_data.keys():
            for edge in emissions.keys():
                val = float(table_data[key][edge])
                e_val = float(table_data[key][ emissions[edge] ])
                data_dict["%s-%s" % (key,edge)] = (val, e_val)
    return data_dict

def get_emission_database():
    table_data = get_periodic_table()
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

def get_peak_database():
    table_data = get_periodic_table()
    peak_db = {}
    em_keys = ['Ka', 'Ka1', 'Ka2', 'Kb', 'Kb1','La1'] #,'Lb1','Lb2', 'Lg1','Lg2','Lg3','Lg4','Ll']
    em_names = ['Kα', 'Kα₁', 'Kα₂', 'Kβ', 'Kβ₁','Lα₁'] #,'Lβ₁','Lβ₂', 'Lγ₁','Lγ₂','Lγ₃','Lγ₄','Lλ']
    for key in table_data.keys():
        for em, nm in zip(em_keys, em_names):
            v = float(table_data[key][em])
            if v > 0.01:
                peak_db["%s-%s" % (key,nm)] = v
    return peak_db
    

def get_signature(elements):
    table_data = get_periodic_table()
    signature = []
    for key in elements:
        for em in ['Ka', 'Ka1', 'Ka2', 'Kb', 'Kb1','La1']:
            v = float(table_data[key][em])
            if v > 0.01:
                signature.append(v)
    return signature


def assign_peaks(peaks, dev=0.01):
    mypeaks = peaks[:]
    data = get_peak_database()
    for peak in mypeaks:
        hits = []
        for key, value in data.items():
            score = abs(value - peak[0])/ (2.0 * dev)
            if abs(value - peak[0]) < 2.0 * dev:
                hits.append( (score, key, value) )
            hits.sort()
        for score, key,value in hits:
            peak.append("%s" % (key,))
    return mypeaks

def savitzky_golay(data, kernel = 9, order = 4, deriv=0):
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
    except ValueError, msg:
        raise ValueError("kernel and order have to be of type int (floats will be converted).")
    if kernel % 2 != 1 or kernel < 1:
        raise TypeError("kernel size must be a positive odd number, was: %d" % kernel)
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

def peak_search(x, y, w=7, threshold=0.01, min_peak=0.01):
    # make sure x is in ascending order
    if x[0] > x[-1]:
        x = x[::-1]
        y = y[::-1]
    peaks = []
    yp = savitzky_golay(y, kernel=w, order=(w-3), deriv=1)
    ypp = savitzky_golay(y, kernel=w, order=(w-3), deriv=2)
    i = 0
    stdypp = numpy.std(-ypp)
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
                if fwhm >= 0.8 * threshold and fwhm <= 10*threshold and peak_height > min_peak:
                    peaks.append([peak_pos, peak_height, fwhm,  stdpk])
        i += 1
    return peaks


PERIODIC_TABLE = """No. Symbol            Name   Type Period  Group      Mass         K        L1        L2        L3        Ka       Ka1       Ka2        Kb       Kb1       La1       Lb1       Lb2       Lg1       Lg2       Lg3       Lg4        Ll
     1      H        Hydrogen     10      1      1    1.0079    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
     2     He          Helium      9      1     18    4.0026    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
     3     Li         Lithium      0      2      1    6.9410    0.0000    0.0000    0.0000    0.0000    0.0520    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
     4     Be       Beryllium      1      2      2    9.0122    0.0000    0.0000    0.0000    0.0000    0.1100    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
     5      B           Boron      6      2     13   10.8110    0.0000    0.0000    0.0000    0.0000    0.1850    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
     6      C          Carbon      7      2     14   12.0107    0.0000    0.0000    0.0000    0.0000    0.2820    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
     7      N        Nitrogen      7      2     15   14.0067    0.0000    0.0000    0.0000    0.0000    0.3920    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
     8      O          Oxygen      7      2     16   15.9994    0.0000    0.0000    0.0000    0.0000    0.5230    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
     9      F        Fluorine      8      2     17   18.9984    0.0000    0.0000    0.0000    0.0000    0.6770    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
    10     Ne            Neon      9      2     18   20.1797    0.0000    0.0000    0.0000    0.0000    0.8510    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
    11     Na          Sodium      0      3      1   22.9898    1.0721    0.0000    0.0000    0.0000    1.0410    1.0410    1.0410    1.0710    1.0670    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
    12     Mg       Magnesium      1      3      2   24.3050    1.3050    0.0000    0.0000    0.0000    1.2540    1.2530    1.2540    1.3020    1.2970    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
    13     Al       Aluminium      5      3     13   26.9815    1.5596    0.0000    0.0000    0.0000    1.4870    1.4860    1.4860    1.5570    1.5530    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
    14     Si         Silicon      6      3     14   28.0855    1.8389    0.0000    0.0000    0.0000    1.7400    1.7400    1.7390    1.8380    1.8320    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
    15      P      Phosphorus      7      3     15   30.9738    2.1455    0.0000    0.0000    0.0000    2.0150    2.0130    2.0140    2.1420    2.1360    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
    16      S          Sulfur      7      3     16   32.0650    2.4720    0.0000    0.0000    0.0000    2.3070    2.3070    2.3060    2.4680    2.4640    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
    17     Cl        Chlorine      8      3     17   35.4530    2.8224    0.0000    0.0000    0.0000    2.6220    2.6220    2.6210    2.8170    2.8150    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
    18     Ar           Argon      9      3     18   39.9480    3.2030    0.0000    0.0000    0.0000    2.9570    2.9570    2.9550    3.1910    3.1920    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
    19      K       Potassium      0      4      1   39.0983    3.6080    0.0000    0.0000    0.0000    3.3120    3.3130    3.3100    3.5890    3.5890    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
    20     Ca         Calcium      1      4      2   40.0780    4.0390    0.0000    0.0000    0.0000    3.6900    3.6910    3.6880    4.0120    4.0120    0.0000    0.3410    0.3440    0.0000    0.0000    0.0000    0.0000    0.0000
    21     Sc        Scandium      4      4      3   44.9559    4.4930    0.0000    0.0000    0.0000    4.0880    4.0900    4.0850    4.4590    4.4600    0.0000    0.3950    0.3990    0.0000    0.0000    0.0000    0.0000    0.0000
    22     Ti        Titanium      4      4      4   47.8670    4.9670    0.0000    0.0000    0.0000    4.5080    4.5100    4.5040    4.9310    4.9310    0.0000    0.4520    0.4580    0.0000    0.0000    0.0000    0.0000    0.0000
    23      V        Vanadium      4      4      5   50.9415    5.4660    0.0000    0.0000    0.0000    4.9490    4.9510    4.9440    5.4270    5.4270    0.0000    0.5100    0.5190    0.0000    0.0000    0.0000    0.0000    0.0000
    24     Cr        Chromium      4      4      6   51.9961    5.9900    0.0000    0.0000    0.0000    5.4110    5.4140    5.4050    5.9470    5.9460    0.0000    0.5710    0.5810    0.0000    0.0000    0.0000    0.0000    0.0000
    25     Mn       Manganese      4      4      7   54.9380    6.5390    0.0000    0.0000    0.0000    5.8950    5.8980    5.8870    6.4920    6.4900    0.0000    0.6360    0.6470    0.0000    0.0000    0.0000    0.0000    0.0000
    26     Fe            Iron      4      4      8   55.8450    7.1120    0.0000    0.0000    0.0000    6.4000    6.4030    6.3900    7.0590    7.0570    0.0000    0.7040    0.7170    0.0000    0.0000    0.0000    0.0000    0.0000
    27     Co          Cobalt      4      4      9   58.9332    7.7090    0.0000    0.0000    0.0000    6.9250    6.9290    6.9150    7.6490    7.6490    0.0000    0.7750    0.7900    0.0000    0.0000    0.0000    0.0000    0.0000
    28     Ni          Nickel      4      4     10   58.6934    8.3330    0.0000    0.0000    0.0000    7.4720    7.4770    7.4600    8.2650    8.2640    8.3280    0.8490    0.8660    0.0000    0.0000    0.0000    0.0000    0.0000
    29     Cu          Copper      4      4     11   63.5460    8.9790    0.0000    0.0000    0.0000    8.0410    8.0460    8.0270    8.9070    8.9040    8.9760    0.9280    0.9480    0.0000    0.0000    0.0000    0.0000    0.0000
    30     Zn            Zinc      4      4     12   65.4090    9.6590    0.0000    0.0000    0.0000    8.6310    8.6370    8.6150    9.5720    9.5710    9.6570    1.0090    1.0320    0.0000    0.0000    0.0000    0.0000    0.0000
    31     Ga         Gallium      5      4     13   69.7230   10.3670    0.0000    0.0000    0.0000    9.2430    9.2500    9.2340   10.2630   10.2630   10.3650    1.0980    1.1250    0.0000    0.0000    0.0000    0.0000    0.0000
    32     Ge       Germanium      6      4     14   72.6400   11.1030    0.0000    0.0000    0.0000    9.8760    9.8850    9.8540   10.9840   10.9810   11.1000    1.1880    1.2180    0.0000    0.0000    0.0000    0.0000    0.0000
    33     As         Arsenic      6      4     15   74.9216   11.8670    0.0000    0.0000    0.0000   10.5320   10.5420   10.5070   11.7290   11.7250   11.8630    1.2820    1.3170    0.0000    0.0000    0.0000    0.0000    0.0000
    34     Se        Selenium      7      4     16   78.9600   12.6580    0.0000    0.0000    0.0000   11.2100   11.2200   11.1810   12.5010   12.4950   12.6510    1.3790    1.4190    0.0000    0.0000    0.0000    0.0000    0.0000
    35     Br         Bromine      8      4     17   79.9040   13.4740    0.0000    0.0000    0.0000   11.9070   11.9220   11.8770   13.2960   13.2900   13.4650    1.4800    1.5260    0.0000    0.0000    0.0000    0.0000    0.0000
    36     Kr         Krypton      9      4     18   83.7980   14.3260    0.0000    0.0000    0.0000   12.6300   12.6480   12.5970   14.1200   14.1120   14.3130    1.5860    1.6360    0.0000    0.0000    0.0000    0.0000    0.0000
    37     Rb        Rubidium      0      5      1   85.4678   15.2000    0.0000    0.0000    0.0000   13.3750   13.3930   13.3350   14.9710   14.9600   15.1840    1.6940    1.7520    0.0000    0.0000    0.0000    0.0000    0.0000
    38     Sr       Strontium      1      5      2   87.6200   16.1050    0.0000    0.0000    0.0000   14.1420   14.1630   14.0970   15.8490   15.8340   16.0830    1.8060    1.8710    0.0010    0.0000    0.0000    0.0000    0.0000
    39      Y         Yttrium      4      5      3   88.9059   17.0380    0.0000    0.0000    0.0000   14.9330   14.9560   14.8820   16.7540   16.7360   17.0110    1.9220    1.9950    0.0000    0.0000    0.0000    0.0000    0.0000
    40     Zr       Zirconium      4      5      4   91.2240   17.9980    0.0000    0.0000    0.0000   15.7460   15.7720   15.6900   17.6870   17.6650   17.9590    2.0420    2.1240    2.2190    2.3020    2.5030    2.5030    0.0000
    41     Nb         Niobium      4      5      5   92.9060   18.9860    0.0000    0.0000    0.0000   16.5840   16.6120   16.5200   18.6470   18.6210   18.9510    2.1660    2.2570    2.3670    2.4620    2.6640    2.6640    0.0000
    42     Mo      Molybdenum      4      5      6   95.9400   20.0000    0.0000    0.0000    0.0000   17.4430   17.4760   17.3730   19.6330   19.6070   19.9640    2.2930    2.3940    2.5180    2.6230    2.8310    2.8310    0.0000
    43     Tc      Technetium      4      5      7   98.9063   21.0440    3.0430    0.0000    0.0000   18.3270   18.3640   18.3280   20.6470   20.5850   21.0120    2.4240    2.5360    2.6740    2.7920    0.0000    0.0000    0.0000
    44     Ru       Ruthenium      4      5      8  101.0700   22.1170    3.2240    0.0000    0.0000   19.2350   19.2760   19.1490   21.6870   21.6550   22.0720    2.5580    2.6830    2.8350    2.9640    3.1810    3.1810    0.0000
    45     Rh         Rhodium      4      5      9  102.9055   23.2200    3.4120    3.1470    3.0040   20.1670   20.2130   20.0720   22.7590   22.7210   23.1690    2.6960    2.8340    3.0010    3.1440    3.3640    3.3640    0.0000
    46     Pd       Palladium      4      5     10  106.4200   24.3500    3.6050    3.3310    3.1740   21.1230   21.1740   21.0180   23.8590   23.8160   24.2970    2.8380    2.9900    3.1710    3.3280    3.5530    3.5530    0.0000
    47     Ag          Silver      4      5     11  107.8682   25.5140    3.8060    3.5240    3.3520   22.1040   22.1590   21.9880   24.9870   24.9420   25.4540    2.9840    3.1500    3.3470    3.5190    3.7430    3.7500    0.0000
    48     Cd         Cadmium      4      5     12  112.4110   26.7110    4.0180    3.7270    3.5380   23.1090   23.1700   22.9820   26.1430   26.0930   26.6410    3.1330    3.3160    3.5280    3.7160    3.9510    0.0000    0.0000
    49     In          Indium      5      5     13  114.8180   27.9400    4.2380    3.9380    3.7310   24.1390   24.2060   24.0000   27.3820   27.2740   27.8590    3.2860    3.4870    3.7130    3.9200    4.1610    4.1610    4.2370
    50     Sn             Tin      5      5     14  118.7100   29.2000    4.4650    4.1570    3.9290   25.1930   25.2670   25.0420   28.6010   28.4830   29.1060    3.4430    3.6620    3.9040    4.1310    4.3770    4.3770    4.4640
    51     Sb        Antimony      6      5     15  121.7600   30.4910    4.6990    4.3810    4.1330   26.2740   26.3550   26.1090   29.8510   29.7230   30.3870    3.6040    3.8430    4.1000    4.3470    4.5600    4.6000    4.6970
    52     Te       Tellurium      6      5     16  127.6000   31.8140    4.9400    4.6120    4.3420   27.3800   27.4680   27.2000   31.1280   30.9930   31.6980    3.7690    4.0290    4.3010    4.5700    4.8290    4.8290    4.9370
    53      I          Iodine      8      5     17  126.9045   33.1690    5.1890    4.8530    4.5580   28.5120   28.6070   28.3150   32.4370   32.2920   33.0160    3.9370    4.2200    4.5070    4.8000    5.0660    5.0660    5.1850
    54     Xe           Xenon      9      5     18  131.2930   34.5610    5.4530    5.1040    4.7830   29.6690   29.7740   29.4850   33.7770   33.6440   34.4460    4.1090    4.4220    4.7200    5.0360    0.0000    0.0000    0.0000
    55     Cs         Caesium      0      6      1  132.9055   35.9820    5.7140    5.3600    5.0120   30.8540   30.9680   30.6230   35.1490   34.9840   35.8190    4.2860    4.6190    4.9350    5.2800    5.5420    5.5530    5.7030
    56     Ba          Barium      1      6      2  137.3270   37.4380    5.9890    5.6240    5.2470   32.0650   32.1880   31.8150   36.5530   36.3760   37.2550    4.4650    4.8270    5.1560    5.5310    5.7970    5.8090    5.9730
    57     La       Lanthanum      2      8      4  138.9055   38.9220    6.2620    5.8910    5.4830   33.3020   33.4360   33.0330   37.9860   37.7990   38.7280    4.6500    5.0410    5.3830    5.7890    6.0600    6.0740    6.2520
    58     Ce          Cerium      2      8      5  140.1160   40.4410    6.5490    6.1640    5.7240   34.5690   34.7140   34.2760   39.4530   39.2550   40.2310    4.8390    5.2610    5.6120    6.0520    6.3250    6.3410    6.5280
    59     Pr    Praseodymium      2      8      6  140.9076   41.9880    6.8350    6.4400    5.9640   35.8640   36.0200   35.5480   40.9530   40.7460   41.7720    5.0330    5.4880    5.8490    6.3220    6.5980    6.6160    6.8150
    60     Nd       Neodymium      2      8      7  144.2420   43.5660    7.1200    6.7220    6.2080   37.1850   37.3550   36.8450   42.4840   42.2690   43.2980    5.2290    5.7210    6.0880    6.6020    6.8830    6.9020    7.1070
    61     Pm      Promethium      2      8      8  146.9151   45.1890    7.4280    7.0130    6.4590   38.5350   38.7180   38.1600   44.0490   43.9450   44.9550    5.4320    5.9600    6.3380    6.8910    0.0000    0.0000    0.0000
    62     Sm        Samarium      2      8      9  150.3600   46.8310    7.7370    7.3120    6.7160   39.9140   40.1110   39.5230   45.6490   45.4000   46.5530    5.6350    6.2050    6.5850    7.1800    7.4670    7.4870    7.7140
    63     Eu        Europium      2      8     10  151.9640   48.5160    8.0520    7.6170    6.9770   41.3230   41.5350   40.8770   47.2830   47.0270   48.2410    5.8450    6.4550    6.8420    7.4780    7.7680    7.7960    8.0300
    64     Gd      Gadolinium      2      8     11  157.2500   50.2360    8.3760    7.9300    7.2430   42.7610   42.9890   42.2800   48.9490   48.7180   49.9610    6.0560    6.7120    7.1020    7.7880    8.0870    8.1050    8.3550
    65     Tb         Terbium      2      8     12  158.9254   51.9930    8.7080    8.2520    7.5140   44.2290   44.4740   43.7370   50.6500   50.3910   51.7370    6.2720    6.9770    7.3650    8.1040    8.3980    8.4230    8.6850
    66     Dy      Dysprosium      2      8     13  162.5000   53.7850    9.0460    8.5810    7.7900   45.7280   45.9910   45.1930   52.3840   52.1780   53.4910    6.4940    7.2460    7.6340    8.4180    8.7140    8.7530    9.0200
    67     Ho         Holmium      2      8     14  164.9303   55.6150    9.3940    8.9180    8.0710   47.2570   47.5390   46.6860   54.1550   53.9340   55.2920    6.7190    7.5240    7.9100    8.7480    9.0510    9.0870    9.3740
    68     Er          Erbium      2      8     15  167.2590   57.4820    9.7510    9.2640    8.3580   48.8180   49.1190   48.2050   55.9630   55.6900   57.0880    6.9470    7.8090    8.1880    9.0890    9.3850    9.4310    9.7220
    69     Tm         Thulium      2      8     16  168.9342   59.3860   10.1150    9.6170    8.6480   50.4100   50.7330   49.7620   57.8060   57.5760   58.9690    7.1790    8.1000    8.4670    9.4240    9.7300    9.7790   10.0840
    70     Yb       Ytterbium      2      8     17  173.0400   61.3290   10.4860    9.9780    8.9440   52.0350   52.3800   51.3260   59.6870   59.3520   60.9590    7.4140    8.4000    8.7570    9.7790   10.0900   10.1430   10.4600
    71     Lu        Lutetium      2      8     18  174.9670   63.3100   10.8700   10.3480    9.2440   53.6930   54.0610   52.9590   61.6070   61.2820   62.9460    7.6540    8.7080    9.0470   10.1420   10.4600   10.5110   10.8430
    72     Hf         Hafnium      4      6      4  178.4900   64.3470   11.2700   10.7390    9.5610   55.3820   55.7810   54.5790   63.5620   63.2090   64.9360    7.8980    9.0210    9.3460   10.5140   10.8340   10.8910   11.2330
    73     Ta        Tantalum      4      6      5  180.9479   67.4120   11.6810   11.1350    9.8810   57.1060   57.5230   56.2700   65.5560   65.2100   66.9990    8.1450    9.3420    9.6500   10.8920   11.2170   11.2780   11.6450
    74      W        Tungsten      4      6      6  183.8400   69.5210   12.0990   11.5430   10.2060   58.8640   59.3080   57.9730   67.5860   67.2330   69.0900    8.3960    9.6710    9.9600   11.2830   11.6080   11.6740   12.0630
    75     Re         Rhenium      4      6      7  186.2070   71.6720   12.5260   11.9580   10.5350   60.6550   61.1300   59.7070   69.6590   69.2960   71.2200    8.6510   10.0080   10.2730   11.6840   12.0100   12.0820   12.4920
    76     Os          Osmium      4      6      8  190.2300   73.8660   12.9670   12.3840   10.8700   62.4820   62.9900   61.4770   71.7750   71.4040   73.3930    8.9100   10.3540   10.5970   12.0940   12.4220   12.5000   12.9230
    77     Ir         Iridium      4      6      9  192.2170   76.1070   13.4180   12.8230   11.2150   64.3460   64.8850   63.2780   73.9330   73.5490   75.6050    9.1740   10.7060   10.9190   12.5090   12.8420   12.9240   13.3680
    78     Pt        Platinum      4      6     10  195.0840   78.3900   13.8790   13.2720   11.5630   66.2460   66.8210   65.1110   76.1310   75.7360   77.8660    9.4410   11.0690   11.2490   12.9390   13.2700   13.3610   13.8280
    79     Au            Gold      4      6     11  196.9666   80.7200   14.3510   13.7330   11.9180   68.1850   68.7920   66.9800   78.3720   77.9680   80.1650    9.7120   11.4400   11.5830   13.3790   13.7100   13.8090   14.3000
    80     Hg         Mercury      4      6     12  200.5900   83.0970   14.8380   14.2080   12.2830   70.1600   70.8070   68.8940   80.6560   80.2580   82.5260    9.9870   11.8210   11.9220   13.8280   14.1620   14.2650   14.7780
    81     Tl        Thallium      5      6     13  204.3833   85.5250   15.3460   14.6970   12.6570   72.1760   72.8590   70.8200   82.9850   82.5580   84.9040   10.2670   12.2110   12.2700   14.2880   14.6250   14.7370   15.2720
    82     Pb            Lead      5      6     14  207.2000   87.9990   15.8600   15.1190   13.0340   74.2280   74.9560   72.7940   85.3570   84.9220   87.3430   10.5500   12.6120   12.6210   14.7620   15.1010   15.2180   15.7770
    83     Bi         Bismuth      5      6     15  208.9804   90.5210   16.3870   15.7100   13.4180   76.3210   77.0950   74.8050   87.7740   87.3350   89.8330   10.8370   13.0210   12.9780   15.2440   15.5820   15.7100   16.2950
    84     Po        Polonium      6      6     16  208.9824   93.1000   16.9380   16.2430   13.8130   78.4600   79.2790   76.8680   90.2430   89.8090   92.3860   11.1290   13.4450   13.3380   15.7400   16.0700    0.0000    0.0000
    85     At        Astatine      8      6     17  209.9871   95.7240   17.4920   16.7840   14.2130   80.6360   81.4990   78.9560   92.7540   92.3190   94.9760   11.4250   13.8740   13.7050   16.2480    0.0000    0.0000    0.0000
    86     Rn           Radon      9      6     18  222.0176   97.3980   18.0480   17.3360   14.6190   82.8550   83.7680   81.0800   95.3150   94.8770   97.6150   11.7250   14.3130   14.0770   16.7680    0.0000    0.0000    0.0000
    87     Fr        Francium      0      7      1  223.0197  101.1300   18.6380   17.9050   15.0300   85.1240   86.0890   83.2430   97.9300   97.4830  100.3050   12.0290   14.7680   14.4480   17.3010    0.0000    0.0000    0.0000
    88     Ra          Radium      1      7      2  226.0254  103.9200   19.2360   18.4830   15.4430   87.4370   88.4540   85.4460  100.5230  100.1360  103.0480   12.3380   15.2330   14.8390   17.8450   18.1790   18.3570   19.0840
    89     Ac        Actinium      3      9      4  227.0278  106.7500   19.8390   19.0820   15.8700   89.7900   90.8680   87.8610  103.3100  102.8460  105.8380   12.6500   15.7100   15.2270   18.4050    0.0000    0.0000    0.0000
    90     Th         Thorium      3      9      5  232.0381  109.6400   20.4710   19.6920   16.2990   92.1900   93.3340   89.9420  106.0770  105.5920  108.6710   12.9670   16.1990   15.6210   18.9770   19.3050   19.5070   20.2920
    91     Pa    Protactinium      3      9      6  231.0359  112.5900   21.1030   20.3130   16.7320   94.6430   95.8520   92.2710  108.9060  108.4080  111.5750   13.2880   16.6990   16.0220   19.5590   19.8720   20.0980   20.8820
    92      U         Uranium      3      9      7  238.0289  115.6000   21.7560   20.9460   17.1650   97.1430   98.4220   94.6490  111.7860  111.2890  114.5490   13.6120   17.2170   16.4250   20.1630   20.4850   20.7130   21.5620
    93     Np       Neptunium      3      9      8  237.0482  118.6700   22.4250   21.5990   17.6090   99.6930  101.0050   97.0230  114.7200  114.1810  117.5330   13.9420   17.7470   16.8370   20.7740   21.1100   21.3400   22.2000
    94     Pu       Plutonium      3      9      9  244.0642  121.8100   23.0960   22.2650   18.0560  102.2950  103.6530   99.4570  117.7160  117.1460  120.5920   14.2760   18.2910   17.2520   21.4010   21.7250   21.9820   22.8910
    95     Am       Americium      3      9     10  243.0614    0.0000    0.0000    0.0000    0.0000  104.9520  106.3510  101.9320  120.7750  120.1630  123.7060   14.6150   18.8490   17.6730   22.0420   22.3610    0.0000    0.0000
    96     Cm          Curium      3      9     11  247.0703    0.0000    0.0000    0.0000    0.0000  107.6700  109.0980  104.4480  123.9030  123.2350  126.8750   14.9610   19.3930   18.1060   22.6990    0.0000    0.0000    0.0000
    97     Bk       Berkelium      3      9     12  247.0703    0.0000    0.0000    0.0000    0.0000  110.4500  111.5950  107.0230  127.1020  126.3620  130.1010   15.3090   19.9710   18.5400   23.3700    0.0000    0.0000    0.0000
    98     Cf     Californium      3      9     13  251.0796    0.0000    0.0000    0.0000    0.0000  113.2980  114.7450  109.6030  130.3770  129.5440  133.3830   15.5610   20.5620   18.9800   24.0560    0.0000    0.0000    0.0000
    99     Es     Einsteinium      3      9     14  252.0829    0.0000    0.0000    0.0000    0.0000  116.2170  117.6460  112.2440  133.7300  132.7810  136.7240   16.0180   21.1660   19.4250   24.7580    0.0000    0.0000    0.0000
   100     Fm         Fermium      3      9     15  257.0951    0.0000    0.0000    0.0000    0.0000  119.2100  120.5960  114.9260  137.1670  136.0750  140.1220   16.3790   21.7850   19.8790   25.4750    0.0000    0.0000    0.0000
   101     Md     Mendelevium      3      9     16  258.0986    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   102     No        Nobelium      3      9     17  259.1009    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   103     Lr      Lawrencium      3      9     18  260.1053    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   104     Rf   Rutherfordium      4      7      4  261.1087    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   105     Db         Dubnium      4      7      5  262.1138    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   106     Sg      Seaborgium      4      7      6  263.1182    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   107     Bh         Bohrium      4      7      7  262.1229    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   108     Hs         Hassium      4      7      8  265.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   109     Mt      Meitnerium      4      7      9  266.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   110     Ds    Darmstadtium      4      7     10  269.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   111     Rg     Roentgenium      4      7     11  272.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   112    Uub        Ununbium     11      7     12  285.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   113    Uut       Ununtrium     11      7     13  284.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   114    Uuq     Ununquadium     11      7     14  289.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   115    Uup     Ununpentium     11      7     15  288.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   116    Uuh      Ununhexium     11      7     16  292.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   117    Uus     Ununseptium     11      7     17  293.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000
   118    Uuo      Ununoctium     11      7     18  294.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000    0.0000"""