import os
import math
import time


# Physical Constats
_h = 4.13566733e-15 # eV.s
_c = 299792458e10   # A/s
_S111_a_rt   = 5.4310209 # A at RT
_S111_a_ln2  = 5.4297575 # A at LN2 


def energy_to_wavelength(energy): 
    """Convert energy in keV to wavelength in angstroms."""
    
    return (_h*_c)/(energy*1000.0)

def wavelength_to_energy(wavelength): 
    """Convert wavelength in angstroms to energy in keV."""
    
    return (_h*_c)/(wavelength*1000.0)

def radians(angle):
    """Convert angle from degrees to radians."""
    
    return math.pi * angle / 180.0

def degrees(angle):
    """Convert angle from radians to degrees."""
    
    return 180 * angle / math.pi
    

def bragg_to_energy(bragg, room_temp=False):
    """Convert bragg angle in degrees to energy in keV.
    
    Arguments:
    bragg       --  bragg angle in degrees to convert to energy
    room_temp   --  boolean value specifying whether the crystal is at room
                    temperature (default False)
    """
    
    if room_temp:
        _S111_a = _S111_a_rt
    else:
        _S111_a = _S111_a_ln2
        
    d = _S111_a / math.sqrt(3.0)
    wavelength = 2.0 * d * math.sin( radians(bragg) )
    return wavelength_to_energy(wavelength)

def energy_to_bragg(energy, room_temp=False):
    """Convert energy in keV to bragg angle in degrees.
    
    Arguments:
    energy      --  energy value to convert to bragg angle
    room_temp   --  boolean value specifying whether the crystal is at room
                    temperature (default False)
    """
    
    if room_temp:
        _S111_a = _S111_a_rt
    else:
        _S111_a = _S111_a_ln2
    d = _S111_a / math.sqrt(3.0)
    bragg = math.asin( energy_to_wavelength(energy)/(2.0*d) )
    return degrees(bragg)

def dec_to_bin(x):
    """Convert from decimal number to a binary string representation."""
    
    return x and (dec_to_bin(x/2) + str(x%2)) or '0'


def dist_to_resol(*args, **kwargs):
    """Convert from distance in mm to resolution in angstroms.
    
    Keyword arguments:
    pixel_size      --  pixel size of detector
    detector_size   --  width of detector
    detector_distance   -- detector distance
    energy          --  X-ray energy
    
    """
    
    pixel_size = kwargs['pixel_size']
    detector_size = kwargs['detector_size']
    detector_distance = kwargs['detector_distance']
    energy = kwargs['energy']
    #two_theta = kwargs['two_theta']
    
    theta = 0.5 * math.atan( 0.5 * pixel_size * detector_size / detector_distance)
    #theta = theta+two_theta
    return 0.5 * energy_to_wavelength(energy) / math.sin(theta)


def resol_to_dist(*args, **kwargs):
    """Convert from resolution in angstroms to distance in mm.
    
    Keyword arguments:
    pixel_size      --  pixel size of detector
    detector_size   --  width of detector
    detector_distance   -- detector distance
    energy          --  X-ray energy
    
    """
    
    pixel_size = kwargs['pixel_size']
    detector_size = kwargs['detector_size']
    resolution = kwargs['resolution']
    energy = kwargs['energy']
    #two_theta = kwargs['two_theta']
    
    theta = math.asin(0.5 * energy_to_wavelength(energy) / resolution)
    #theta = max(0, (theta-two_theta))
    return 0.5 * pixel_size * detector_size / math.tan( 2 * theta )

