# BCM GLOBAL Settings for 08B1-1 Beamline

from mxdc.devices import motor, goniometer, cryojet, boss, detector, synchrotron
from mxdc.devices import video, misc, mca, counter, manager
from mxdc.devices.automounter import isara
from mxdc.services import clients

CONFIG = {
    'name': 'CMCF-ID',
    'facility': 'CLS',
    'mono': 'Si 111',
    'mono_unit_cell': 5.4297575,
    'source': 'Small-Gap Undulator',
    'type': 'mx',
    'subnet': '10.52.28.0/22',

    'admin_groups': [1000, 1046, 1172, 1150, 1014, 1023, 2000, 4054, 33670],
    'distance_limits': (100.0, 900.0),
    'energy_range': (6.0, 18.0),
    'default_attenuation': 90.0,
    'default_exposure': 0.2,
    'default_delta': 0.2,
    'default_beamstop': 30.0,
    'safe_beamstop': 47.0,
    'safe_distance': 400.0,
    'xrf_beamstop': 100.0,
    'xrf_fwhm': 0.1,
    'xrf_energy_offset': 2.0,
    'shutter_sequence': ('ssh1', 'psh1', 'psh2', 'ssh2'),
    'orientation': 'right',
    'linked_sample_stage': False,
    'centering_backlight': 40,
    'zoom_levels': (2, 6, 9),
    'bug_report': ['michel.fodje@lightsource.ca']
}

# maps names to devices objects
DEVICES = {
    # Energy, DCM devices, MOSTAB, Optimizers
    'energy': motor.PseudoMotor("PMTR1608-002:energy:keV"),
    'bragg_energy': motor.BraggEnergyMotor(
        'SMTR16082I1005:deg', mono_unit_cell=CONFIG['mono_unit_cell']
    ),
    'dcm_pitch': motor.VMEMotor('SMTR16082I1010:deg'),
    'beam_tuner': boss.MOSTABTuner('MOS16082I1001',  'AH501-01:QEM', 'PCT1402-01:mA:fbk', reference='LUT1608-ID-IONC:target'),

    # Goniometer/goniometer head devices
    'manager': manager.ModeManager('MODE1608-ID'),
    'goniometer': goniometer.ParkerGonio('GV6K1608-001'),
    'omega': motor.VMEMotor('GV6K1608-001:deg'),
    'sample_x': motor.VMEMotor('SMTR16083I1008:mm'),
    'sample_y1': motor.VMEMotor('SMTR16083I1012:mm'),  # if no sample_y, it will be determined from
    'sample_y2': motor.VMEMotor('SMTR16083I1013:mm'),  # orthogonal sample_y1 AND sample_y2

    # Beam position & Size
    'aperture': misc.SimChoicePositioner('Aperture', 50, choices=[50], units='um'),
    'beam_x': motor.VMEMotor('SMTR16083I1002:mm'),
    'beam_y': motor.VMEMotor('SMTR16083I1004:mm'),
    'beam_w': motor.VMEMotor('SMTR16083I1001:mm'),
    'beam_h': motor.VMEMotor('SMTR16083I1003:mm'),

    # Detector, distance & two_theta
    'distance': motor.PseudoMotor('BL08ID1:2Theta:D:mm'),
    'detector_z': motor.VMEMotor('SMTR16083I1018:mm', encoded=True),
    'two_theta': motor.PseudoMotor('BL08ID1:2Theta:deg'),
    'detector': detector.PilatusDetector('DEC1608-01:cam1'),
    #'detector': detector.SimCCDImager('Simulated CCD Detector', 4096, 0.07243),
    'detector_cover': misc.Shutter('MSHD1608-3-I10-01'),

    # Sample environment, beam stop, cameras, zoom, lighting
    'beamstop_z': motor.VMEMotor('SMTR16083I1016:mm'),
    'sample_zoom': motor.VMEMotor('SMTR16083I1025:mm'),

    'cryojet': cryojet.CryoJet('cryoCtlr', 'cryoLVM', 'CSC1608-3-I10-01'),
    'sample_camera': video.REDISCamera('v2e1608-301.clsi.ca', mac='000F31031D82', zoom_slave=True),

    'sample_backlight': misc.SampleLight('ILC1608-3-I10-02:sp', 'ILC1608-3-I10-02:fbk', 'ILC1608-3-I10-02:on', 100.0),
    'sample_frontlight': misc.SampleLight('ILC1608-3-I10-01:sp', 'ILC1608-3-I10-01:fbk', 'ILC1608-3-I10-01:on', 100.0),
    'sample_uvlight': misc.SampleLight('BL08ID1:UVLight', 'BL08ID1:UVLight:fbk', 'BL08ID1:UVLight:OnOff', 100.0),
    'hutch_video': video.AxisPTZCamera('CCD1608-302.clsi.ca'),

    # Facility, storage-ring, shutters, etc
    'synchrotron': synchrotron.StorageRing('PCT1402-01:mA:fbk', 'SYSTEM:mode:fbk', 'SRStatus'),
    'psh1': misc.Shutter('PSH1408-I00-01'),
    'psh2': misc.Shutter('PSH1408-I00-02'),
    'ssh1': misc.Shutter('SSH1408-I00-01'),
    'ssh2': misc.Shutter('SSH1608-2-I10-01'),
    'enclosures': misc.Enclosures(
        poe1='ACIS1608-3-I10-01:poe1:secure', poe2='ACIS1608-3-I10-01:poe2:secure', soe='ACIS1608-3-I10-01:soe1:secure'
    ),
    'fast_shutter': misc.Shutter('PSH16083I1001'),

    # Intensity monitors,
    'i_0': counter.Counter('AH501-03:QEM:SumAll:MeanValue_RBV'),
    'i_1': counter.Counter('AH501-04:QEM:SumAll:MeanValue_RBV'),
    'i_2': counter.Counter('AH501-01:QEM:SumAll:MeanValue_RBV'),

    # Misc: Automounter, HC1 etc
    #'automounter': isara.ISARA('BOT1608-I01'),
    'automounter': isara.AuntISARA('ISARA1608-301'),
    'attenuator': misc.Attenuator('PFIL1608-3-I10-01', 'BL08ID1:energy'),
    'mca': mca.XFlashMCA('XFD1608-101'),

    # disk space monitor
    'disk_space': misc.DiskSpaceMonitor('Disk Space', '/users'),
}

# lims, dpm, imagesync and other services
SERVICES = {
    'dss': clients.DSSClient(),
    'lims': clients.MxLIVEClient('https://mxlive.lightsource.ca'),
    'dps': clients.DPSClient('hpc1608-001.clsi.ca:9991'),
    'messenger': clients.Messenger('cmcf.lightsource.ca', realm=CONFIG['name'])
}

# Devices only available in the console
CONSOLE = {
    'vfm_bend': motor.PseudoMotor('BL08ID1:VFM:Focus:foc', version=1),
    'vfm_y': motor.PseudoMotor('BL08ID1:VFM:Height:mm', version=1),
    'vfm_pitch': motor.PseudoMotor('BL08ID1:VFM:Pitch:mrad', version=1),
    'vfm_roll': motor.PseudoMotor('BL08ID1:VFM:Roll:mrad', version=1),
    'dcm_roll1': motor.VMEMotor('SMTR16082I1007:deg'),
    'dcm_roll2': motor.VMEMotor('SMTR16082I1008:deg'),
    'dcm_pitch': motor.VMEMotor('SMTR16082I1010:deg'),
    'dcm_yaw': motor.VMEMotor('SMTR16082I1009:deg'),
    'dcm_y': motor.VMEMotor('SMTR16082I1006:mm'),
    'dcm_t1': motor.VMEMotor('SMTR16082I1011:mm'),
    'dcm_t2': motor.VMEMotor('SMTR16082I1012:mm'),
    'wbs_hgap': motor.PseudoMotor('PSL16082I1001:gap:mm', version=1),
    'wbs_vgap': motor.PseudoMotor('PSL16082I1002:gap:mm', version=1),
    'wbs_x': motor.PseudoMotor('PSL16082I1001:cntr:mm', version=1),
    'wbs_y': motor.PseudoMotor('PSL16082I1002:cntr:mm', version=1),
    'mbs_top': motor.VMEMotor('SMTR16082I1017:mm'),
    'mbs_bot': motor.VMEMotor('SMTR16082I1018:mm'),
    'es_x': motor.VMEMotor('SMTR16083I1002:mm'),
    'es_y': motor.VMEMotor('SMTR16083I1004:mm'),
    'gonio_y': motor.VMEMotor('SMTR16083I1009:mm'),
    'gonio_x': motor.VMEMotor('SMTR16083I1008:mm'),
    'exbox_pitch': motor.VMEMotor('SMTR16083I1007:mm'),
    'exbox_x': motor.VMEMotor('SMTR16083I1005:mm'),
    'exbox_y': motor.VMEMotor('SMTR16083I1006:mm'),
    'beamstop_x': motor.VMEMotor('SMTR16083I1014:mm'),
    'beamstop_y': motor.VMEMotor('SMTR16083I1015:mm'),
}
