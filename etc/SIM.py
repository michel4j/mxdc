# BCM GLOBAL Settings for SIM Beamline
from bcm.settings import *
import os

BEAMLINE_NAME = 'SIM-1'
BEAMLINE_TYPE = 'MX'
BEAMLINE_ENERGY_RANGE = (3.0, 18.5)
BEAMLINE_GONIO_POSITION = 2             # Goniometer orientation (XREC) 1,2,3

DEFAULT_EXPOSURE    = 2.0
DEFAULT_ATTENUATION = 50.0              # attenuation in %
DEFAULT_BEAMSTOP    = 30.0
SAFE_DISTANCE       = 400.0
SAFE_BEAMSTOP       = 50.0
XRF_BEAMSTOP        = 90.0
CENTERING_BACKLIGHT = 50
XRF_ENERGY_OFFSET   = +1.0              # KeV

LIMS_API_KEY = "4A8285AB-9E5F-476E-B17B-92BEB299A985"

# pitch function for PitchOptimizer
def _energy2pitch(x):
    # any function which calculates the optimal pitch given energy ONLY
    return 0.0

# maps names to device objects
_tmp1 = SimMotor('Detector Distance', 150.0, 'mm', speed=10.0) # use the same motor for distance and z
DEVICES = {
    # Energy, DCM devices, MOSTAB, Optimizers
    'energy':   SimMotor('Energy', 12.5, 'keV'),
    'bragg_energy': SimMotor('Bragg Energy', 12.5, 'keV'),
    'dcm_pitch':  SimMotor('DCM Pitch', 0.0, 'deg'),
    'boss': SimOptimizer('Sim Boss'),    
    'mostab': PitchOptimizer('Sim Pitch Optimzer', _energy2pitch),
    
    # Goniometer/goniometer head devices
    'goniometer': SimGoniometer(),
    'omega':    SimMotor('Omega', 0.0, 'deg', speed=30.0),
    'sample_x':  SimMotor('Sample X', 0.0, 'mm'),
    'sample_y':  SimMotor('Sample Y', 0.0, 'mm'),
    
    # Beam position & Size
    'aperture': SimChoicePositioner("Aperture", 50, choices=[100,50,25], units='um'),
    'beam_x':   SimMotor('Beam X', 0.0, 'mm'),
    'beam_y':   SimMotor('Beam Y', 0.0, 'mm'),
    'beam_w':   SimMotor('Beam W', 0.2, 'mm'),
    'beam_h':   SimMotor('Beam H', 0.2, 'mm'),
    
    # Detector, distance & two_theta
    'distance': _tmp1,
    'detector_z':  _tmp1,
    'two_theta':  SimMotor('Detector Two Theta', 0.0, 'deg', speed=5.0),
    #'detector': SimCCDImager('Simulated CCD Detector', 4096, 0.07243),
    #'detector': MXCCDImager('BL08B1-01:CCD', 4096, 0.07243, 'MX300HE'),
    'detector': PIL6MImager('DEC1608-01:cam1'),

    # Sample environment, beam stop, cameras, zoom, lighting
    'beamstop_x':  SimMotor('Beamstop X', 0.0, 'mm'),
    'beamstop_y':  SimMotor('Beamstop Y', 0.0, 'mm'),
    'beamstop_z':  SimMotor('Beamstop Z', 30.0, 'mm'),  
    'sample_zoom':  SimPositioner('Sample Zoom', 2),
    'camera_center_x':  SimPositioner('Camera Center x', 388),
    'camera_center_y':  SimPositioner('Camera Center y', 288),
    'cryojet':  SimCryojet('Simulated Cryojet'),
    'sample_camera': SimCamera(),
    'sample_backlight': SimLight('Back light', 45.0, '%'),
    'sample_frontlight': SimLight('Front light', 55.0, '%'),    
    'hutch_video':  SimPTZCamera(),
    
    # Facility, storage-ring, shutters, etc
    'ring_current':  PV('PCT1402-01:mA:fbk'),
    'ring_mode':  PV('SYSTEM:mode:fbk'),
    'ring_status':  PV('SRStatus:injecting'),
    #'storage_ring':  SimStorageRing('Simulated Storage Ring'),
    'storage_ring':  StorageRing('SYSTEM:mode:fbk', 'PCT1402-01:mA:fbk', 'SRStatus'),
    'psh1':  SimShutter('PSH1'),
    'ssh1':  SimShutter('SSH2'),
    'psh2':  SimShutter('PSH2'),
    'exposure_shutter': SimShutter('Fast Shutter'),
    'enclosures': Enclosures(poe='ACIS1608-5-B10-01:poe1:secure', soe='ACIS1608-5-B10-01:soe1:secure'),
    
    # Intensity monitors, shutter, attenuation, mca etc
    'i_0': SimCounter('I_0'),
    'i_1': SimCounter('I_1'),
    'i_2': SimCounter('I_2'),
    
    # Misc: Automounter, HC1 etc
    'automounter':  SimAutomounter(),
    'humidifier': HumidityController('HC1608-01'),
    'attenuator': SimPositioner('Attenuator', 0.0, '%'),
    'mca': SimMultiChannelAnalyzer('Simulated MCA'),
    'multi_mca' : SimMultiChannelAnalyzer('Simulated MCA'),

    #disk space monitor
    'disk_space' : DiskSpaceMonitor('Disk Space', '/users', warn=0.5, critical=0.25, freq=30),
}

# lims, dpm, imagesync and other services
SERVICES = {
    'lims': LIMSClient('https://opi2051-002.clsi.ca:9393'),
    #'lims': LIMSClient('https://cmcf.lightsource.ca'),
<<<<<<< HEAD
    'image_server': ImageSyncClient(),
=======
    'image_server': ImageSyncClient(include=['*.cbf'], mode='777'),
>>>>>>> 89f7fa68166e7ae437d2c24be78641daaf6fd44a
    #'image_server': ImageSyncClient('ccdc1608-004:8880'),

    'dpm': DPMClient(),
}

# Beamline shutters in the order in which they should be opened
BEAMLINE_SHUTTERS = ('ssh1', 'ssh1', 'psh1', 'psh2')  


