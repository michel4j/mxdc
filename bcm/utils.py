import os
import math, time

# Physical Constats
h = 4.13566733e-15 # eV.s
c = 299792458e10   # A/s
S111_a_rt   = 5.4310209 # A at RT
S111_a_ln2  = 5.4297575 # A at LN2 

def keVToA(energy): #Angstroms
	return (h*c)/(energy*1000.0)

def AToKeV(wavelength): #eV
	return (h*c)/(wavelength*1000.0)

def radians(angle):
    return math.pi * angle / 180.0

def degrees(angle):
    return 180 * angle / math.pi
    

def braggToKeV(bragg):
    d = S111_a_ln2 / math.sqrt(3.0)
    wavelength = 2.0 * d * math.sin( radians(bragg) )
    return AToKeV(wavelength)

def keVToBragg(energy):
    d = S111_a_ln2 / math.sqrt(3.0)
    bragg = math.asin( keVToA(energy)/(2.0*d) )
    return degrees(bragg)

def decToBin(x):
    return x and (decToBin(x/2) + str(x%2)) or '0'
    
