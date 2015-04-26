import os
import math
import time
import numpy



# Physical Constats
_h = 4.135667516e-15 # eV.s
_c = 299792458e10   # A/s
_m = 5.685629904369271e-32 # eV.A^-2 , calculated using 
_hb =  _h/(2*math.pi)

_S111_A_DICT = {
    '08B1': 5.4310209,
    '08ID': 5.4297575,
}


def energy_to_d(energy):
    bragg = radians(energy_to_bragg(energy))
    return energy_to_wavelength(energy)/(2*math.sin(bragg))
    
def energy_to_wavelength(energy): 
    """Convert energy in keV to wavelength in angstroms."""
    if energy == 0.0:
        return 0.0
    return (_h*_c)/(energy*1000.0)

def energy_to_kspace(delta_e): 
    """Convert delta_energy in KeV to k-space in A-1."""
    #return numpy.sign(delta_e)*numpy.sqrt(0.2625 * abs(delta_e))
    return numpy.sign(delta_e)*numpy.sqrt(2000.0*_m*abs(delta_e))/_hb

def kspace_to_energy(k): 
    """Convert k-space in A-1 to delta_energy in KeV """
    #return numpy.sign(k)*(k**2)/0.2625
    return numpy.sign(k)*numpy.sign(k)*(k*_hb)**2/(2000.0*_m)


def wavelength_to_energy(wavelength): 
    """Convert wavelength in angstroms to energy in keV."""
    if wavelength == 0.0:
        return 0.0
    return (_h*_c)/(wavelength*1000.0)

def radians(angle):
    """Convert angle from degrees to radians."""
    
    return math.pi * angle / 180.0

def degrees(angle):
    """Convert angle from radians to degrees."""
    
    return 180 * angle / math.pi
    

def bragg_to_energy(bragg):
    """Convert bragg angle in degrees to energy in keV.
    
    Arguments:
    bragg       --  bragg angle in degrees to convert to energy
    """
    
    _S111_a = _S111_A_DICT.get(os.environ.get('BCM_BEAMLINE', '08id1'), 5.4310209)
        
    d = _S111_a / math.sqrt(3.0)
    wavelength = 2.0 * d * math.sin( radians(bragg) )
    return wavelength_to_energy(wavelength)

def energy_to_bragg(energy):
    """Convert energy in keV to bragg angle in degrees.
    
    Arguments:
    energy      --  energy value to convert to bragg angle
    """
    
    _S111_a = _S111_A_DICT.get(os.environ.get('BCM_BEAMLINE', '08id1'), 5.4310209)
    d = _S111_a / math.sqrt(3.0)
    bragg = math.asin( energy_to_wavelength(energy)/(2.0*d) )
    return degrees(bragg)

def dec_to_bin(x):
    """Convert from decimal number to a binary string representation."""
    
    return x and (dec_to_bin(x/2) + str(x%2)) or '0'


def dist_to_resol(distance, pixel_size, detector_size, energy, two_theta=0):
    """Convert from distance in mm to resolution in angstroms.
    
    Arguments:
    pixel_size      --  pixel size of detector
    detector_size   --  width of detector
    distance   -- detector distance
    energy          --  X-ray energy
    
    """
    
    
    theta = 0.5 * math.atan( 0.5 * pixel_size * detector_size / distance)
    theta = theta+two_theta
    return 0.5 * energy_to_wavelength(energy) / math.sin(theta)


def resol_to_dist(resolution, pixel_size, detector_size, energy, two_theta=0):
    """Convert from resolution in angstroms to distance in mm.
    
    Arguments:
    resolution    -- desired resolution
    pixel_size      --  pixel size of detector
    detector_size   --  width of detector
    energy          --  X-ray energy
    
    """
    
    
    theta = math.asin(0.5 * energy_to_wavelength(energy) / resolution)
    theta = max(0, (theta-two_theta))
    return 0.5 * pixel_size * detector_size / math.tan( 2 * theta )

