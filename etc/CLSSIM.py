# BCM GLOBAL Settings for SIM Beamline
from mxdc.com import ca
from mxdc.devices import motor, goniometer, cryojet, boss, detector, automounter, humidity, video, misc, mca, counter
from mxdc.services import clients

BEAMLINE_NAME = 'SIM-1'
BEAMLINE_TYPE = 'MX'
BEAMLINE_ENERGY_RANGE = (5.0, 18)
BEAMLINE_GONIO_POSITION = 2             # Goniometer orientation (XREC) 1,2,3
ADMIN_GROUPS = [2000]

DEFAULT_EXPOSURE    = 2.0
DEFAULT_ATTENUATION = 50.0              # attenuation in %
DEFAULT_BEAMSTOP    = 30.0
SAFE_DISTANCE       = 400.0
SAFE_BEAMSTOP       = 50.0
XRF_BEAMSTOP        = 90.0
CENTERING_BACKLIGHT = 50
XRF_ENERGY_OFFSET   = +1.5              # KeV

# maps names to devices objects
_tmp1 = motor.SimMotor('Detector Distance', 150.0, 'mm', speed=50.0) # use the same motor for distance and z
_tmp2 = motor.SimMotor('Energy', 12.5, 'keV', speed=0.2, precision=4)
DEVICES = {
    # Energy, DCM devices, MOSTAB, Optimizers
    'energy':   _tmp2,
    'bragg_energy': _tmp2,
    'dcm_pitch':  motor.SimMotor('DCM Pitch', 0.0, 'deg'),
    'beam_tuner': boss.SimTuner('Simulated Beam Tuner'),
    
    # Goniometer/goniometer head devices
    'goniometer': goniometer.SimGoniometer(),
    'omega':    motor.SimMotor('Omega', 0.0, 'deg', speed=120.0, precision=3),
    'sample_x':  motor.SimMotor('Sample X', 0.0, units='mm', speed=0.2),
    'sample_y1':  motor.SimMotor('Sample Y', 0.0, units='mm', speed=0.2),
    'sample_y2': motor.SimMotor('Sample Y', 0.0, units='mm', speed=0.2),
    
    # Beam position & Size
    'aperture': misc.SimChoicePositioner('Beam Size', 50, choices=[200, 150, 100, 50, 25], units='um'),
    
    # Detector, distance & two_theta
    'distance': _tmp1,
    'detector_z':  _tmp1,
    'two_theta':  motor.SimMotor('Detector Two Theta', 0.0, 'deg', speed=5.0),
    'detector': detector.SimCCDImager('Simulated CCD Detector', 4096, 0.07243),
    
    # Sample environment, beam stop, cameras, zoom, lighting
    'beamstop_x':  motor.SimMotor('Beamstop X', 0.0, 'mm'),
    'beamstop_y':  motor.SimMotor('Beamstop Y', 0.0, 'mm'),
    'beamstop_z':  motor.SimMotor('Beamstop Z', 30.0, 'mm'),
    'sample_zoom':  motor.SimMotor('Sample Zoom', 2.0, speed=8),
    'cryojet':  cryojet.SimCryoJet('Simulated Cryojet'),
    #'sample_camera': SimCamera(),
    #'sample_camera': AxisCamera('V2E1608-400.clsi.ca', 1),
    #'sample_camera': AxisPTZCamera('ccd1608-301.clsi.ca'),
    #'sample_camera': MJPGCamera('http://opi2051-002.clsi.ca:9999/video.mjpg', size=(1360, 1024)),
    #'sample_camera': JPGCamera('http://opi2051-002.clsi.ca:9999/image.jpg', size=(1360, 1024)),
    'sample_camera': video.REDISCamera('opi1608-101.clsi.ca', size=(1360, 1024), key='CAM1608:000F31031D82:JPG'),

    'sample_backlight': misc.SimLight('Back light', 45.0, '%'),
    'sample_frontlight': misc.SimLight('Front light', 55.0, '%'),
    'sample_uvlight': misc.SimLight('UV light', 25.0, '%'),

    #'hutch_video':  SimPTZCamera(),
    'hutch_video':  video.AxisPTZCamera('ccd1608-301.clsi.ca'),

    
    # Facility, storage-ring, shutters, etc
    'ring_current':  ca.PV('PCT1402-01:mA:fbk'),
    'ring_mode':  ca.PV('SYSTEM:mode:fbk'),
    'ring_status':  ca.PV('SRStatus:injecting'),
    'storage_ring':  misc.SimStorageRing('Simulated Storage Ring'),
    #'storage_ring':  StorageRing('SYSTEM:mode:fbk', 'PCT1402-01:mA:fbk', 'SRStatus'),
    'psh1':  misc.SimShutter('PSH1'),
    'ssh1':  misc.SimShutter('SSH2'),
    'psh2':  misc.SimShutter('PSH2'),
    'exposure_shutter': misc.SimShutter('Fast Shutter'),
    'enclosures': misc.Enclosures(poe='ACIS1608-5-B10-01:poe1:secure', soe='ACIS1608-5-B10-01:soe1:secure'),
    
    # Intensity monitors, shutter, attenuation, mca etc
    'i_0': counter.SimCounter('I_0', zero=26931),
    'i_1': counter.SimCounter('I_1', zero=35019),
    'i_2': counter.SimCounter('I_2', zero=65228),
    
    # Misc: Automounter, HC1 etc
    'automounter':  automounter.SimAutomounter(),
    'humidifier': humidity.SimHumidifier(),
    'attenuator': misc.SimPositioner('Attenuator', 0.0, '%'),
    'mca': mca.SimMultiChannelAnalyzer('Simulated MCA', energy=_tmp2),
    'multi_mca' : mca.SimMultiChannelAnalyzer('Simulated MCA', energy=_tmp2),

    #disk space monitor
    'disk_space' : misc.DiskSpaceMonitor('Disk Space', '/users', warn=0.2, critical=0.1, freq=30),
}

# lims, dpm, imagesync and other services
SERVICES = {
    'image_server': clients.LocalImageSyncClient(),
    'lims': clients.MxLIVEClient('http://opi2051-003.clsi.ca:8000'),
    'dpm': clients.DPMClient(),
}

# Beamline shutters in the order in which they should be opened
BEAMLINE_SHUTTERS = ('ssh1', 'psh1', 'psh2')


