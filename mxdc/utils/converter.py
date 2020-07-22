import math

import numpy

# Physical Constats
_h = 4.135667516e-15  # eV.s
_c = 299792458e10  # A/s
_m = 5.685629904369271e-32  # eV.A^-2 , calculated using
_hb = _h / (2 * math.pi)


def energy_to_d(energy, unit_cell):
    bragg = radians(energy_to_bragg(energy, unit_cell=unit_cell))
    return energy_to_wavelength(energy) / (2 * math.sin(bragg))


def energy_to_wavelength(energy):
    """Convert energy in keV to wavelength in angstroms."""
    if energy == 0.0:
        return 0.0
    return (_h * _c) / (energy * 1000.0)


def energy_to_kspace(delta_e):
    """Convert delta_energy in KeV to k-space in A-1."""
    # return numpy.sign(delta_e)*numpy.sqrt(0.2625 * abs(delta_e))
    return numpy.sign(delta_e) * numpy.sqrt(2000.0 * _m * abs(delta_e)) / _hb


def kspace_to_energy(k):
    """Convert k-space in A-1 to delta_energy in KeV """
    # return numpy.sign(k)*(k**2)/0.2625
    return numpy.sign(k) * numpy.sign(k) * (k * _hb) ** 2 / (2000.0 * _m)


def wavelength_to_energy(wavelength):
    """Convert wavelength in angstroms to energy in keV."""
    if wavelength == 0.0:
        return 0.0
    return (_h * _c) / (wavelength * 1000.0)

def radians(angle):
    """Convert angle from degrees to radians."""

    return math.pi * angle / 180.0


def degrees(angle):
    """Convert angle from radians to degrees."""

    return 180 * angle / math.pi


def bragg_to_energy(bragg, unit_cell=5.4310209):
    """Convert bragg angle in degrees to energy in keV.

    Arguments:
    bragg       --  bragg angle in degrees to convert to energy
    """

    d = unit_cell / math.sqrt(3.0)
    wavelength = 2.0 * d * math.sin(radians(bragg))
    return wavelength_to_energy(wavelength)


def energy_to_bragg(energy, unit_cell=5.4310209):
    """Convert energy in keV to bragg angle in degrees.

    Arguments:
    energy      --  energy value to convert to bragg angle
    """

    d = unit_cell / math.sqrt(3.0)
    bragg = math.asin(energy_to_wavelength(energy) / (2.0 * d))
    return degrees(bragg)


def dec_to_bin(x):
    """Convert from decimal number to a binary string representation."""

    return bin(x)[2:].zfill(4)


def dist_to_resol(distance, detector_size, energy, two_theta=0):
    """Convert from distance in mm to resolution in angstroms.

    Arguments:
    detector_size   --  width of detector in mm
    distance   -- detector distance in mm
    energy          --  X-ray energy

    """

    if distance == 0.0:
        return 0.0

    theta = 0.5 * math.atan(0.5 * detector_size / distance)
    theta = theta + two_theta
    return 0.5 * energy_to_wavelength(energy) / math.sin(theta)


def resol_to_dist(resolution, detector_size, energy, two_theta=0):
    """Convert from resolution in angstroms to distance in mm.

    Arguments:
    resolution    -- desired resolution
    pixel_size      --  pixel size of detector
    detector_size   --  width of detector
    energy          --  X-ray energy

    """

    if resolution == 0.0:
        return 0.0

    theta = math.asin(max(-1, min(0.5 * energy_to_wavelength(energy) / resolution, 1)))
    theta = max(0, (theta - two_theta))
    return 0.5 * detector_size / math.tan(2 * theta)