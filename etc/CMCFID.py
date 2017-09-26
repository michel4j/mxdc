# BCM GLOBAL Settings for 08B1-1 Beamline
from mxdc.com import ca
from mxdc.devices import motor, goniometer, cryojet, boss, detector, automounter, video, misc, mca, counter
from mxdc.services import clients

CONFIG = {
    'name': 'CMCF-ID',
    'type': 'mx',
    'admin_groups': [1000, 2000],
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
    'orientation': 3,
    'centering_backlight': 37,
    'bug_report': ['michel.fodje@lightsource.ca']
}

# maps names to devices objects
DEVICES = {
    # Energy, DCM devices, MOSTAB, Optimizers
    'energy': motor.EnergyMotor('BL08ID1:energy', 'SMTR16082I1005:deg'),
    'bragg_energy': motor.BraggEnergyMotor('SMTR16082I1005:deg', motor_type="vme"),
    'dcm_pitch': motor.VMEMotor('SMTR16082I1010:deg'),
    'beam_tuner': boss.MOSTABTuner('MOS16082I1001', 'AH501-01:QEM', reference='LUT1608-ID-IONC:control'),

    # Goniometer/goniometer head devices
    'goniometer': goniometer.Goniometer('GV6K1608-001', 'BL08ID1:mode'),
    'omega': motor.VMEMotor('GV6K1608-001:deg'),
    'sample_x': motor.VMEMotor('SMTR16083I1008:mm'),
    'sample_y2': motor.VMEMotor('SMTR16083I1012:mm'),  # if no sample_y, it will be determined from
    'sample_y1': motor.VMEMotor('SMTR16083I1013:mm'),  # orthogonal sample_y1 AND sample_y2

    # Beam position & Size
    'aperture': misc.SimChoicePositioner('Aperture', 50, choices=[50], units='um'),
    'beam_x': motor.VMEMotor('SMTR16083I1002:mm'),
    'beam_y': motor.VMEMotor('SMTR16083I1004:mm'),
    'beam_w': motor.VMEMotor('SMTR16083I1001:mm'),
    'beam_h': motor.VMEMotor('SMTR16083I1003:mm'),

    # Detector, distance & two_theta
    'distance': motor.PseudoMotor('BL08ID1:2Theta:D:mm'),
    'detector_z': motor.ENCMotor('SMTR16083I1018:mm'),
    'two_theta': motor.PseudoMotor('BL08ID1:2Theta:deg'),
    'detector': detector.PIL6MImager('DEC1608-01:cam1'),
    'detector_cover': misc.Shutter('MSHD1608-3-I10-01'),

    # Sample environment, beam stop, cameras, zoom, lighting
    'beamstop_z': motor.VMEMotor('SMTR16083I1016:mm'),
    'sample_zoom': motor.VMEMotor('SMTR16083I1025:mm'),
    'cryojet': cryojet.CryoJet('cryoCtlr', 'cryoLVM', 'CSC1608-3-I10-01'),
    'sample_camera': video.AxisCamera('V2E1608-001', 4),
    'sample_backlight': misc.SampleLight('ILC1608-3-I10-02:sp', 'ILC1608-3-I10-02:fbk', 'ILC1608-3-I10-02:on', 100.0),
    'sample_frontlight': misc.SampleLight('ILC1608-3-I10-01:sp', 'ILC1608-3-I10-01:fbk', 'ILC1608-3-I10-01:on', 100.0),
    'sample_uvlight': misc.SampleLight('BL08ID1:UVLight', 'BL08ID1:UVLight:fbk', 'BL08ID1:UVLight:OnOff', 100.0),
    'hutch_video': video.AxisPTZCamera('CCD1608-301'),

    # Facility, storage-ring, shutters, etc
    'ring_current': ca.PV('PCT1402-01:mA:fbk'),
    'ring_mode': ca.PV('SYSTEM:mode:fbk'),
    'ring_status': ca.PV('SRStatus:injecting'),
    'storage_ring': misc.StorageRing('SYSTEM:mode:fbk', 'PCT1402-01:mA:fbk', 'SRStatus'),
    'psh1': misc.Shutter('PSH1408-I00-01'),
    'psh2': misc.Shutter('PSH1408-I00-02'),
    'ssh1': misc.Shutter('SSH1408-I00-01'),
    'ssh2': misc.Shutter('SSH1608-2-I10-01'),
    'enclosures': misc.Enclosures(
        poe1='ACIS1608-3-I10-01:poe1:secure', poe2='ACIS1608-3-I10-01:poe2:secure', soe='ACIS1608-3-I10-01:soe1:secure'
    ),
    'exposure_shutter': misc.Shutter('PSH16083I1001'),

    # Intensity monitors,
    'i_0': counter.Counter('AH501-03:QEM:SumAll:MeanValue_RBV'),
    'i_1': counter.Counter('AH501-04:QEM:SumAll:MeanValue_RBV'),
    'i_2': counter.Counter('AH501-01:QEM:SumAll:MeanValue_RBV'),
    'i_4': counter.Counter('A1608-3-06:A:fbk'),

    # Misc: Automounter, HC1 etc
    'automounter': automounter.Automounter('ROB16083I', 'ROB1608-300'),
    # 'humidifier': Humidifier('HC1608-01'),
    'attenuator': misc.Attenuator('PFIL1608-3-I10-01', 'BL08ID1:energy'),
    'mca': mca.XFlashMCA('XFD1608-101'),

    # disk space monitor
    'disk_space': misc.DiskSpaceMonitor('Disk Space', '/users'),
}

# lims, dpm, imagesync and other services
SERVICES = {
    'image_server': clients.ImageSyncClient(include=['*.cbf'], mode='777'),
    'lims': clients.MxLIVEClient('https://cmcf.lightsource.ca'),
    'dpm': clients.DPMClient(),
}

# Devices only available in the console
CONSOLE = {
    'vfm_bend': motor.PseudoMotor2('BL08ID1:VFM:Focus:foc'),
    'vfm_y': motor.PseudoMotor2('BL08ID1:VFMHeight:mm'),
    'vfm_yaw': motor.PseudoMotor2('BL08ID1:VFMTrans:yaw:mm'),
    'vfm_pitch': motor.PseudoMotor2('BL08ID1:VFMPitch:mrad'),
    'vfm_roll': motor.PseudoMotor2('BL08ID1:VFMRoll:mrad'),
    'vfm_x': motor.PseudoMotor2('BL08ID1:VFMTrans:cm'),
    'dcm_roll1': motor.VMEMotor('SMTR16082I1007:deg'),
    'dcm_roll2': motor.VMEMotor('SMTR16082I1008:deg'),
    'dcm_pitch': motor.VMEMotor('SMTR16082I1010:deg'),
    'dcm_yaw': motor.VMEMotor('SMTR16082I1009:deg'),
    'dcm_y': motor.VMEMotor('SMTR16082I1006:mm'),
    'dcm_t1': motor.VMEMotor('SMTR16082I1011:mm'),
    'dcm_t2': motor.VMEMotor('SMTR16082I1012:mm'),
    'dcm_bend': motor.VMEMotor('BL08ID1:C2NewBndRad:mm'),
    'wbs_hgap': motor.PseudoMotor2('PSL16082I1001:gap:mm'),
    'wbs_vgap': motor.PseudoMotor2('PSL16082I1002:gap:mm'),
    'wbs_x': motor.PseudoMotor2('PSL16082I1001:cntr:mm'),
    'wbs_y': motor.PseudoMotor2('PSL16082I1002:cntr:mm'),
    'mbs_top': motor.VMEMotor('SMTR16082I1017:mm'),
    'mbs_bot': motor.VMEMotor('SMTR16082I1018:mm'),
    'es_vgap': motor.VMEMotor('SMTR16083I1001:mm'),
    'es_hgap': motor.VMEMotor('SMTR16083I1003:mm'),
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
