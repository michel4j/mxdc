# BCM GLOBAL Settings for 08B1-1 Beamline
from mxdc.devices import motor, goniometer, cryojet, boss, detector, synchrotron
from mxdc.devices import humidity, video, misc, mca, counter, manager
from mxdc.devices.automounter import sam
from mxdc.services import clients

CONFIG = {
    'name': 'CMCF-BM',
    'facility': 'CLS',
    'mono': 'Si 111',
    'mono_unit_cell': 5.4310209,
    'source': 'Bend Magnet',
    'type': 'mx',
    'subnet': '10.52.4.0/22',
    'admin_groups': [1000, 1046, 1172, 1150, 1014, 1023, 2000, 4054, 33670],
    'distance_limits': (110.0, 800.0),
    'energy_range': (5.0, 20.5),
    'zoom_levels': (2, 5, 8),
    'default_attenuation': 90.0,
    'default_exposure': 2.5,
    'default_delta': 0.5,
    'default_beamstop': 60.0,
    'safe_beamstop': 80.0,
    'safe_distance': 400.0,
    'xrf_beamstop': 100.0,
    'xrf_fwhm': 0.1,
    'xrf_energy_offset': 2.0,
    'shutter_sequence': ('ssh1', 'psh1', 'psh2', 'ssh3'),
    'orientation': 'left',
    'centering_backlight': 20,
    'bug_report': ['michel.fodje@lightsource.ca']
}

# maps names to devices objects
DEVICES = {
    # Energy, DCM devices, MOSTAB, Optimizers
    'energy':   motor.PseudoMotor('DCM1608-4-B10-01:energy:KeV'),
    'bragg_energy': motor.BraggEnergyMotor(
        'SMTR1608-4-B10-17:deg', encoded=True, mono_unit_cell=CONFIG['mono_unit_cell']
    ),
    'beam_tuner': boss.BOSSTuner('BL08B1:PicoControl', 'AH1608-05:QEM:SumAll:MeanValue_RBV', 'PCT1402-01:mA:fbk', reference='LUT1608-BM-IONC:target', control='DCM1608-4-B10-01:energy:enabled'),
    
    # Goniometer/goniometer head devices
    #'manager': manager.MD2Manager('MD1608-05'),
    'manager': manager.ModeManager('MODE1608-BM'),
    'goniometer': goniometer.MD2Gonio('MD1608-05'),
    'omega':    motor.PseudoMotor('PMTR1608-001:omega:deg'),
    'phi': motor.PseudoMotor('PMTR1608-001:phi:deg'),
    'chi': motor.PseudoMotor('PMTR1608-001:chi:deg'),
    'kappa': motor.PseudoMotor('PMTR1608-001:kappa:deg'),
    'sample_x':  motor.PseudoMotor('PMTR1608-001:gonX:mm'),
    'sample_y1':  motor.PseudoMotor('PMTR1608-001:smplY:mm'),
    'sample_y2':  motor.PseudoMotor('PMTR1608-001:smplZ:mm'),
    
    # Beam position & Size
    'aperture': misc.ChoicePositioner('MD1608-05:CurrentApertureDiameterIndex', choices=[200, 150, 100, 50, 20], units='um'),
    'beam_x':   motor.VMEMotor('SMTR1608-5-B10-08:mm'),
    'beam_y':   motor.VMEMotor('SMTR1608-5-B10-06:mm'),
    'beam_w':   motor.VMEMotor('SMTR1608-5-B10-07:mm'),
    'beam_h':   motor.VMEMotor('SMTR1608-5-B10-05:mm'),
    
    # Detector, distance & two_theta
    'distance': motor.PseudoMotor('BL08B1:det:dist:mm', precision=2),
    'detector_z':  motor.VMEMotor('SMTR1608-5-B10-14:mm', precision=2, encoded=True),
    'two_theta':  motor.PseudoMotor('BL08B1:det:2theta:deg'),
    'detector': detector.RayonixDetector('CCDC1608-B1-01:cam1', 4096, 'MX300HE'),

    # Sample environment, beam stop, cameras, zoom, lighting
    'beamstop_z':  motor.PseudoMotor('PMTR1608-001:bstZ:mm'),
    'sample_zoom':  motor.PseudoMotor('PMTR1608-001:zoom:pos'),
    'camera_scale': misc.Positioner('MD1608-05:CoaxCamScaleX', 'MD1608-05:CoaxCamScaleX'),
    'cryojet':  cryojet.CryoJet5('CSC1608-5-03', 'CSC1608-5-B10-01'),


    'sample_camera': video.REDISCamera('V2E1608-501.clsi.ca', mac='000F31030CAA', zoom_slave=True),
    'sample_backlight': misc.SampleLight('MD1608-05:BackLightLevel', 'MD1608-05:BackLightLevel', 'MD1608-05:BackLightIsOn', 100.0),
    'sample_frontlight': misc.SampleLight('MD1608-05:FrontLightLevel', 'MD1608-05:FrontLightLevel', 'MD1608-05:FrontLightIsOn',100.0),
    'hutch_video':  video.AxisPTZCamera('ccd1608-501.clsi.ca'),
    
    # Facility, storage-ring, shutters, etc
    'synchrotron':  synchrotron.StorageRing('PCT1402-01:mA:fbk', 'SYSTEM:mode:fbk', 'SRStatus'),
    'psh1': misc.Shutter('PSH1408-B10-01'),
    'psh2': misc.Shutter('PSH1408-B10-02'),
    'ssh1': misc.Shutter('SSH1408-B10-01'),
    'ssh3': misc.Shutter('SSH1608-4-B10-01'),
    'enclosures': misc.Enclosures(poe='ACIS1608-5-B10-01:poe1:secure', soe='ACIS1608-5-B10-01:soe1:secure'),
    'fast_shutter': misc.ToggleShutter('MD1608-05:FastShutterIsOpen'),
    
    # Intensity monitors,
    'i_0': counter.Counter('AH1608-05:QEM:SumAll:MeanValue_RBV'),
    'i_1': counter.Counter('AH1608-02:QEM:SumAll:MeanValue_RBV'),


    
    # Misc: Automounter, HC1 etc
    'automounter':  sam.UncleSAM('SAM1608-501'),
    'humidifier': humidity.Humidifier('HC1608-01'),
    'attenuator': misc.Attenuator2('PFIL1608-5-B10-01', 'DCM1608-4-B10-01:energy:KeV:fbk'),
    'mca': mca.XFlashMCA('XFD1608-501', nozzle=misc.OnOffToggle('MD1608-05:FluoDetectorIsBack', values=(0, 1))),
    'multi_mca': mca.VortexMCA('dxp1608-004'),
    'deicer': misc.OnOffToggle('DIC1608-5-B10-01:spray:on'),

    #disk space monitor
    'disk_space' : misc.DiskSpaceMonitor('Disk Space', '/users'),
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
    'i_2': counter.Counter('VCMBVBPM:I'),

    'wbs_hgap': motor.PseudoMotor('PSL1608-4-B10-02:gap:mm'),
    'wbs_vgap': motor.PseudoMotor('PSL1608-4-B10-01:gap:mm'),
    'wbs_x': motor.PseudoMotor('PSL1608-4-B10-02:cntr:mm'),
    'wbs_y': motor.PseudoMotor('PSL1608-4-B10-01:cntr:mm'),
    'wbs_top': motor.VMEMotor('SMTR1608-4-B10-01:mm', encoded=True),
    'wbs_bot': motor.VMEMotor('SMTR1608-4-B10-02:mm', encoded=True),
    'wbs_out': motor.VMEMotor('SMTR1608-4-B10-04:mm', encoded=True),
    'wbs_in': motor.VMEMotor('SMTR1608-4-B10-03:mm', encoded=True),

    'vcm_y': motor.PseudoMotor('SCM1608-4-B10-01:ht:mm'),
    'vcm_pitch': motor.PseudoMotor('SCM1608-4-B10-01:pitch:mrad'),
    'vcm_x': motor.PseudoMotor('SMTR1608-4-B10-08:mm'),
    'vcm_yaw': motor.VMEMotor('SMTR1608-4-B10-09:deg', encoded=True),
    'vcm_bend': motor.PseudoMotor('SCM1608-4-B10-01:bnd:m'),

    'tfm_bend': motor.PseudoMotor('TDM1608-4-B10-01:bnd:m'),
    'tfm_y': motor.PseudoMotor('TDM1608-4-B10-01:ht:mm'),
    'tfm_yaw': motor.VMEMotor('SMTR1608-4-B10-26:deg', encoded=True),
    'tfm_pitch': motor.PseudoMotor('TDM1608-4-B10-01:pitch:mrad'),
    'tfm_roll':  motor.PseudoMotor('TDM1608-4-B10-01:roll:mrad'),
    'tfm_x': motor.VMEMotor('SMTR1608-4-B10-25:mm', encoded=True),

    'dcm_pitch': motor.VMEMotor('SMTR1608-4-B10-15:deg', encoded=True),
    'dcm_roll': motor.VMEMotor('SMTR1608-4-B10-12:deg', encoded=True),
    'dcm_y': motor.VMEMotor('SMTR1608-4-B10-18:mm', encoded=True),
    'dcm_y2': motor.VMEMotor('SMTR1608-4-B10-14:mm', encoded=True),
    'dcm_x': motor.VMEMotor('SMTR1608-4-B10-19:mm'),


    'mbs_top': motor.VMEMotor('SMTR1608-4-B10-20:mm', encoded=True),
    'mbs_bot': motor.VMEMotor('SMTR1608-4-B10-21:mm', encoded=True),
    'mbs_vgap': motor.PseudoMotor('PSL1608-4-B10-03:gap:mm'),
    'mbs_y': motor.PseudoMotor('PSL1608-4-B10-03:cntr:mm'),

    'es1_vgap': motor.VMEMotor('SMTR1608-5-B10-01:mm'),
    'es1_hgap': motor.VMEMotor('SMTR1608-5-B10-03:mm'),
    'es1_x': motor.VMEMotor('SMTR1608-5-B10-04:mm'),
    'es1_y': motor.VMEMotor('SMTR1608-5-B10-02:mm'),

    'es2_vgap': motor.VMEMotor('SMTR1608-5-B10-05:mm'),
    'es2_hgap': motor.VMEMotor('SMTR1608-5-B10-07:mm'),
    'es2_x': motor.VMEMotor('SMTR1608-5-B10-08:mm'),
    'es2_y': motor.VMEMotor('SMTR1608-5-B10-06:mm'),

    'table_y': motor.PseudoMotor('TBL1608-5-B10-01:ht:mm'),
    'table_pitch': motor.PseudoMotor('TBL1608-5-B10-01:pitch:mrad'),
    'table_yaw': motor.PseudoMotor('TBL1608-5-B10-01:yaw:mrad'),
    'table_roll': motor.PseudoMotor('TBL1608-5-B10-01:roll:mrad'),
    'table_x': motor.PseudoMotor('TBL1608-5-B10-01:htrans:mm'),
    'table_x1': motor.VMEMotor('SMTR1608-5-B10-12:mm', encoded=True),
    'table_x2': motor.VMEMotor('SMTR1608-5-B10-13:mm', encoded=True),

    'i_3': counter.Counter('AH1608-04:QEM:SumAll:MeanValue_RBV'),
}
