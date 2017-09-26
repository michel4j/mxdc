# BCM GLOBAL Settings for 08B1-1 Beamline
from mxdc.com import ca
from mxdc.devices import motor, goniometer, cryojet, boss, detector, automounter, humidity, video, misc, mca, counter
from mxdc.services import clients

CONFIG = {
    'name': 'CMCF-BM',
    'type': 'mx',
    'admin_groups': [1000, 2000],
    'energy_range': (5.0, 18.0),
    'default_attenuation': 90.0,
    'default_exposure': 5.0,
    'default_delta': 0.5,
    'default_beamstop': 60.0,
    'safe_beamstop': 80.0,
    'safe_distance': 400.0,
    'xrf_beamstop': 100.0,
    'xrf_fwhm': 0.1,
    'xrf_energy_offset': 2.0,
    'shutter_sequence': ('ssh1', 'psh1', 'psh2', 'ssh3'),
    'orientation': 2,
    'centering_backlight': 65,
    'bug_report': ['michel.fodje@lightsource.ca']
}

# maps names to devices objects
DEVICES = {
    # Energy, DCM devices, MOSTAB, Optimizers
    'energy':   motor.PseudoMotor('DCM1608-4-B10-01:energy:KeV'),
    'bragg_energy': motor.BraggEnergyMotor('SMTR1608-4-B10-17:deg', motor_type="vmeenc"),
    'dcm_pitch':  motor.ENCMotor('SMTR1608-4-B10-15:deg'),
    'beam_tuner': boss.BOSSTuner('BL08B1:PicoControl'),
    
    # Goniometer/goniometer head devices
    'goniometer': goniometer.MD2Goniometer('BL08B1:MD2'),
    'omega':    motor.PseudoMotor('PSMTR1608-5-B10-06:pm:deg'),
    'phi': motor.PseudoMotor('PSMTR1608-5-B10-12:pm:deg'),
    'chi': motor.PseudoMotor('PSMTR1608-5-B10-13:pm:deg'),
    'kappa': motor.PseudoMotor('PSMTR1608-5-B10-11:pm:deg'),
    'sample_x':  motor.PseudoMotor('PSMTR1608-5-B10-02:pm:mm', precision=3),
    #'sample_y':  motor.PseudoMotor('PSMTR1608-5-B10-07:pm:mm', precision=3),
    'sample_y1':  motor.PseudoMotor('PSMTR1608-5-B10-05:pm:mm', precision=3),
    'sample_y2':  motor.PseudoMotor('PSMTR1608-5-B10-04:pm:mm', precision=3),
    
    # Beam position & Size
    'aperture': misc.ChoicePositioner('BL08B1:MD2:S:SelectedAperture', choices=[200, 150, 100, 50, 20], units='um'),
    'beam_x':   motor.VMEMotor('SMTR1608-5-B10-08:mm'),
    'beam_y':   motor.VMEMotor('SMTR1608-5-B10-06:mm'),
    'beam_w':   motor.VMEMotor('SMTR1608-5-B10-07:mm'),
    'beam_h':   motor.VMEMotor('SMTR1608-5-B10-05:mm'),
    
    # Detector, distance & two_theta
    'distance': motor.PseudoMotor('BL08B1:det:dist:mm', precision=2),
    'detector_z':  motor.ENCMotor('SMTR1608-5-B10-14:mm', precision=2),
    'two_theta':  motor.PseudoMotor('BL08B1:det:2theta:deg'),
    'detector': detector.ADRayonixImager('CCDC1608-B1-01:cam1', 4096, 'MX300HE'),

    
    # Sample environment, beam stop, cameras, zoom, lighting
    'beamstop_z':  motor.PseudoMotor('PSMTR1608-5-B10-08:pm:mm'),  
    'sample_zoom':  misc.Positioner('BL08B1:MD2:S:ZoomLevel', 'BL08B1:MD2:G:ZoomLevel'),
    #'cryojet':  Cryojet('CSC1608-5-01', 'CSCLVM1608-5-01', 'CSC1608-5-B10-01'),
    'cryojet':  cryojet.CryoJet5('CSC1608-5-03', 'CSC1608-5-B10-01'),
    'sample_camera': video.AxisCamera('V2E1608-400', 1),
    'sample_backlight': misc.SampleLight('BL08B1:MD2:S:BlightLevel', 'BL08B1:MD2:G:BlightLevel', 'BL08B1:MD2:S:BlightOnOff', 100.0),
    'sample_frontlight': misc.SampleLight('BL08B1:MD2:S:FlightLevel', 'BL08B1:MD2:G:FlightLevel', 'BL08B1:MD2:S:FlightOnOff',100.0),
    'hutch_video':  video.AxisPTZCamera('ccd1608-500'),
    
    # Facility, storage-ring, shutters, etc
    'ring_current':  ca.PV('PCT1402-01:mA:fbk'),
    'ring_mode':  ca.PV('SYSTEM:mode:fbk'),
    'ring_status':  ca.PV('SRStatus:injecting'),
    'storage_ring':  misc.StorageRing('SYSTEM:mode:fbk', 'PCT1402-01:mA:fbk', 'SRStatus'),
    'psh1': misc.Shutter('PSH1408-B10-01'),
    'psh2': misc.Shutter('PSH1408-B10-02'),
    'ssh1': misc.Shutter('SSH1408-B10-01'),
    'ssh3': misc.Shutter('SSH1608-4-B10-01'),
    'enclosures': misc.Enclosures(poe='ACIS1608-5-B10-01:poe1:secure', soe='ACIS1608-5-B10-01:soe1:secure'),
    'exposure_shutter': misc.BasicShutter('BL08B1:MD2:S:OpenFastShutter','BL08B1:MD2:S:CloseFastShutter','BL08B1:MD2:G:ShutterIsOpen'),
    
    # Intensity monitors,
    'i_0': counter.Counter('BPM08B1-05:I0:fbk'),
    #'i_1': Counter('BPM08B1-04:I0:fbk'),
    'i_1': counter.Counter('BPM08B1-02:I0:fbk'),
    'i_bst':  counter.Counter('BL08B1:MD2:G:ExternalPhotoDiode'),
    'i_scn':  counter.Counter('BL08B1:MD2:G:InternalPhotoDiode'),
    
    # Misc: Automounter, HC1 etc
    'automounter':  automounter.Automounter('ROB16085B', 'ROB1608-500'),
    'humidifier': humidity.Humidifier('HC1608-01'),
    'attenuator': misc.Attenuator2('PFIL1608-5-B10-01', 'DCM1608-4-B10-01:energy:KeV:fbk'),
    'mca_nozzle': misc.Positioner('BL08B1:MD2:S:MoveFluoDetFront'),
    'mca': mca.XFlashMCA('XFD1608-501'),
    'multi_mca': mca.VortexMCA('dxp1608-004'),
    'deicer': misc.OnOffToggle('DIC1608-5-B10-01:spray:on'),

    #disk space monitor
    'disk_space' : misc.DiskSpaceMonitor('Disk Space', '/users'),
}

# lims, dpm, imagesync and other services
SERVICES = {
    'image_server': clients.ImageSyncClient(),
    'lims': clients.MxLIVEClient('http://opi2051-003.clsi.ca:8000'),
    'dpm': clients.DPMClient(),
}

# Devices only available in the console
CONSOLE = {
    'vcm_y': motor.PseudoMotor('SCM1608-4-B10-01:ht:mm'),
    'vcm_pitch': motor.PseudoMotor('SCM1608-4-B10-01:pitch:mrad'),
    'vcm_x': motor.PseudoMotor('SMTR1608-4-B10-08:mm'),
    'vcm_yaw': motor.ENCMotor('SMTR1608-4-B10-09:deg'),
    'vcm_bend': motor.PseudoMotor('SCM1608-4-B10-01:bnd:m'),
    'tfm_bend': motor.PseudoMotor('TDM1608-4-B10-01:bnd:m'),
    'tfm_y': motor.PseudoMotor('TDM1608-4-B10-01:ht:mm'),
    'tfm_yaw': motor.ENCMotor('SMTR1608-4-B10-26:deg'),
    'tfm_pitch': motor.PseudoMotor('TDM1608-4-B10-01:pitch:mrad'),
    'tfm_roll':  motor.PseudoMotor('TDM1608-4-B10-01:roll:mrad'),
    'tfm_x': motor.ENCMotor('SMTR1608-4-B10-25:mm'),
    'dcm_roll1': motor.ENCMotor('SMTR1608-4-B10-16:deg'),
    'dcm_roll2': motor.ENCMotor('SMTR1608-4-B10-12:deg'),
    'dcm_yaw': motor.ENCMotor('SMTR1608-4-B10-13:deg'),
    'dcm_y': motor.VMEMotor('SMTR1608-4-B10-18:mm'),
    'dcm_y2': motor.ENCMotor('SMTR1608-4-B10-14:mm'),
    'dcm_x': motor.VMEMotor('SMTR1608-4-B10-19:mm'),
    'wbs_hgap': motor.PseudoMotor('PSL1608-4-B10-02:gap:mm'),
    'wbs_vgap': motor.PseudoMotor('PSL1608-4-B10-01:gap:mm'),
    'wbs_x': motor.PseudoMotor('PSL1608-4-B10-02:cntr:mm'),
    'wbs_y': motor.PseudoMotor('PSL1608-4-B10-01:cntr:mm'),
    'wbs_top': motor.ENCMotor('SMTR1608-4-B10-01:mm'),
    'wbs_bot': motor.ENCMotor('SMTR1608-4-B10-02:mm'),
    'wbs_out': motor.ENCMotor('SMTR1608-4-B10-04:mm'),
    'wbs_in': motor.ENCMotor('SMTR1608-4-B10-03:mm'),
    'mbs_top': motor.ENCMotor('SMTR1608-4-B10-20:mm'),
    'mbs_bot': motor.ENCMotor('SMTR1608-4-B10-21:mm'),
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
    'gt_y': motor.PseudoMotor('TBL1608-5-B10-01:ht:mm'),
    'gt_pitch': motor.PseudoMotor('TBL1608-5-B10-01:pitch:mrad'),
    'gt_yaw': motor.PseudoMotor('TBL1608-5-B10-01:yaw:mrad'),
    'gt_roll': motor.PseudoMotor('TBL1608-5-B10-01:roll:mrad'),
    'gt_x': motor.PseudoMotor('TBL1608-5-B10-01:htrans:mm'),
    'gt_x1': motor.ENCMotor('SMTR1608-5-B10-12:mm'),
    'gt_x2': motor.ENCMotor('SMTR1608-5-B10-13:mm'),
}
