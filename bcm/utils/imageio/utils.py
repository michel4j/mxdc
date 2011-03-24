'''
Created on Nov 26, 2010

@author: michel
'''

import numpy

def stretch(gamma):
    lut = numpy.zeros(65536, dtype=numpy.uint)
    lut[65280:] = 255
    for i in xrange(65280):
        v = int(i*gamma)
        if v >= 255:
            lut[i] = 254
        else:
            lut[i] = v
    return lut

def calc_gamma(avg_int):
    return 29.378 * avg_int ** -0.86
            