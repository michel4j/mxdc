#!/usr/bin/env python

import numpy

def get_thickness(att, energy):
    att_frac = att / 100.0
    thck = numpy.log(1.0-att_frac) * (energy*1000)**2.9554 / -4.4189e12
    return round(thck*10)/10
    


def get_attenuation(thck, energy):
    att = 1.0 - numpy.exp( -4.4189e12 * thck / (energy*1000)**2.9554 )
    return att * 100


