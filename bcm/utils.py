import os
import math, time
import gtk

# Physical Constats
h = 4.13566733e-15 # eV.s
c = 299792458e10   # A/s
S111_a_rt   = 5.4310209 # A at RT
S111_a_ln2  = 5.4297575 # A at LN2 

def energy_to_wavelength(energy): #Angstroms
	return (h*c)/(energy*1000.0)

def wavelength_to_energy(wavelength): #eV
	return (h*c)/(wavelength*1000.0)

def radians(angle):
    return math.pi * angle / 180.0

def degrees(angle):
    return 180 * angle / math.pi
    

def bragg_to_energy(bragg):
    d = S111_a_ln2 / math.sqrt(3.0)
    wavelength = 2.0 * d * math.sin( radians(bragg) )
    return wavelength_to_energy(wavelength)

def energy_to_bragg(energy):
    d = S111_a_ln2 / math.sqrt(3.0)
    bragg = math.asin( energy_to_wavelength(energy)/(2.0*d) )
    return degrees(bragg)

def dec_to_bin(x):
    return x and (dec_to_bin(x/2) + str(x%2)) or '0'
    
def read_periodic_table():
    filename = os.environ['BCM_DATA_PATH'] + '/periodic_table.dat'
    data_file = open(filename)
    table_data = {}
    data = data_file.readlines()
    data_file.close()
    keys = data[0].split()
    for line in data[1:] :
        vals = line.split()
        table_data[vals[1]] = {}
        for (key,val) in zip(keys,vals):
            table_data[vals[1]][key] = val
    return table_data
   
def gtk_idle(sleep=None):
    while gtk.events_pending():
        gtk.main_iteration()

def dist_to_resol(*args, **kwargs):
	pixel_size = kwargs['pixel_size']
	detector_size = kwargs['detector_size']
	detector_distance = kwargs['detector_distance']
	energy = kwargs['energy']
	#two_theta = kwargs['two_theta']
	
	theta = 0.5 * math.atan( 0.5 * pixel_size * detector_size / detector_distance)
	#theta = theta+two_theta
	return 0.5 * energy_to_wavelength(energy) / math.sin(theta)
	
def resol_to_dist(*args, **kwargs):
	
	pixel_size = kwargs['pixel_size']
	detector_size = kwargs['detector_size']
	resolution = kwargs['resolution']
	energy = kwargs['energy']
	#two_theta = kwargs['two_theta']
	
	theta = math.asin(0.5 * energy_to_wavelength(energy) / resolution)
	#theta = max(0, (theta-two_theta))
	return 0.5 * pixel_size * detector_size / math.tan( 2 * theta )
	