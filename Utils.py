import gtk, gobject
import os
import numpy, time

# Physical Constats
h = 4.13566733e-15 # eV.s
c = 299792458e10   # A/s
#S111_a = 5.4310209 # A at RT
S111_a  = 5.4297575 # A at LN2 

def keV_to_A(energy): #Angstroms
	return (h*c)/(energy*1000.0)

def A_to_keV(wavelength): #eV
	return (h*c)/(wavelength*1000.0)

def radians(angle):
    return numpy.pi * angle / 180.0

def degrees(angle):
    return 180 * angle / numpy.pi
    

def bragg_to_keV(bragg):
    d = S111_a / numpy.sqrt(3.0)
    wavelength = 2.0 * d * numpy.sin( radians(bragg) )
    return A_to_keV(wavelength)

def keV_to_bragg(energy):
    d = S111_a / numpy.sqrt(3.0)
    bragg = numpy.arcsin( keV_to_A(energy)/(2.0*d) )
    return degrees(bragg)

def dec2bin(x):
    return x and (dec2bin(x/2) + str(x%2)) or '0'
    
