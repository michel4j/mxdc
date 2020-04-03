# Settings for SIM Beamline
# copy this file to a dedicated directory, and set the $MXDC_CONFIG environment variable
# to point to the directory before starting MxDC.  The directory can contain
# as many config files as desired, one per sub-net.
#
# Config files are read in pairs  XXXX.py, XXXX_local.py
#   * XXXX.py       - main config file, usually closely guarded
#   * XXXX_local.py - local config file, overrides entries in the main config file, customizations can be allowed


import mxdc.devices.shutter
from mxdc.devices import motor, goniometer, cryojet, boss, detector, synchrotron
from mxdc.devices import humidity, video, misc, mca, counter, manager
from mxdc.devices.automounter import sim
from mxdc.services import clients


CONFIG = {
    'name': 'SIM-1',
    'facility': 'CLS',
    'mono': 'Si 111',
    'mono_unit_cell': 5.4297575,
    'source': 'CLS Sim SGU',
    'type': 'mxdc.beamlines.mx.MXBeamline',
    'subnet': '0.0.0.0/32',

    'admin_groups': [1000, 1046, 1172, 1150, 1014, 1023, 2000],

    'energy_range': (5.0, 19.0),
    'zoom_levels': (2, 4, 6),
    'default_attenuation': 50.0,
    'default_exposure': 0.25,
    'default_delta': 0.25,
    'default_beamstop': 25.0,
    'safe_beamstop': 50.0,
    'safe_distance': 400.0,
    'xrf_beamstop': 50.0,
    'xrf_fwhm': 0.1,
    'xrf_energy_offset': 2.0,
    'shutter_sequence': ('ssh1', 'psh1', 'psh2'),
    'orientation': 'left',
    'centering_backlight': 50,
    'bug_report': ['michel.fodje@lightsource.ca']
}

# maps names to devices objects
tmp1 = motor.SimMotor('Detector Distance', 150.0, 'mm', speed=50.0)  # use the same motor for distance and z
tmp2 = motor.SimMotor('Energy', 12.5, 'keV', speed=0.2, precision=4)

DEVICES = {
    # Energy, DCM devices, MOSTAB, Optimizers
    'energy': tmp2,
    'bragg_energy': tmp2,
    'dcm_pitch': motor.SimMotor('DCM Pitch', 0.0, 'deg'),
    'beam_tuner': boss.SimTuner('Simulated Beam Tuner'),

    # BaseGoniometer/goniometer head devices
    'manager': manager.SimModeManager(),
    'goniometer': goniometer.SimGonio(),
    'omega': motor.SimMotor('Omega', 0.0, 'deg', speed=60.0, precision=3),
    'sample_x': motor.SimMotor('Sample X', 0.0, units='mm', speed=0.2),
    'sample_y1': motor.SimMotor('Sample Y', 0.0, units='mm', speed=0.2),
    'sample_y2': motor.SimMotor('Sample Y', 0.0, units='mm', speed=0.2),

    # Beam position & Size
    'aperture': misc.SimChoicePositioner('Beam Size', 100, choices=[200, 150, 100, 50, 25], units='um'),

    # Detector, distance & two_theta
    'distance': tmp1,
    'detector_z': tmp1,
    'two_theta': motor.SimMotor('Detector Two Theta', 0.0, 'deg', speed=5.0),
    'detector': detector.SimDetector('Simulated CCD Detector', size=4096, pixel_size=0.07243),
    'camera_scale': misc.SimPositioner('Camera Scale', pos=0.025, noise=0),

    # Sample environment, beam stop, cameras, zoom, lighting
    'beamstop_x': motor.SimMotor('Beamstop X', 0.0, 'mm'),
    'beamstop_y': motor.SimMotor('Beamstop Y', 0.0, 'mm'),
    'beamstop_z': motor.SimMotor('Beamstop Z', 30.0, 'mm'),
    'sample_zoom': motor.SimMotor('Sample Zoom', 2.0, speed=8),
    'cryojet': cryojet.SimCryoJet('Simulated Cryojet'),
    'sample_camera': video.SimCamera(),

    'sample_backlight': misc.SimLight('Back light', 45.0, '%'),
    'sample_frontlight': misc.SimLight('Front light', 55.0, '%'),
    'sample_uvlight': misc.SimLight('UV light', 25.0, '%'),

    # 'hutch_video':  SimPTZCamera(),
    'hutch_video': video.SimPTZCamera(),

    # Facility, storage-ring, shutters, etc
    'synchrotron': synchrotron.SimStorageRing('Simulated Storage Ring'),
    'psh1': mxdc.devices.shutter.SimShutter('PSH1'),
    'ssh1': mxdc.devices.shutter.SimShutter('SSH2'),
    'psh2': mxdc.devices.shutter.SimShutter('PSH2'),
    'fast_shutter': mxdc.devices.shutter.SimShutter('Fast Shutter'),
    'enclosures': misc.SimEnclosures('Beamline Enclusures'),

    # Intensity monitors, shutter, attenuation, mca etc
    'i0': counter.SimCounter('i0', zero=26931),
    'i1': counter.SimCounter('i1', zero=35019),
    'i2': counter.SimCounter('i2', zero=65228),

    # Misc: Automounter, HC1 etc
    'automounter': sim.SimSAM(),
    'humidifier': humidity.SimHumidifier(),
    'attenuator': misc.SimPositioner('Attenuator', 0.0, '%'),
    'mca': mca.SimMCA('Simulated MCA', energy=tmp2),
    'multi_mca': mca.SimMCA('Simulated MCA', energy=tmp2),

    # disk space monitor
    'disk_space': misc.DiskSpaceMonitor('Disk Space', '/home', warn=0.2, critical=0.1, freq=30),
}

# lims, dpm, imagesync and other services
SERVICES = {
    'dss': clients.LocalDSSClient(),
    'lims': clients.MxLIVEClient('http://localhost:8000'),
    'dps': clients.DPSClient('hpc1608-001.clsi.ca:9991'),
    'messenger': clients.Messenger('cmcf.lightsource.ca', realm=CONFIG['name'])
}
