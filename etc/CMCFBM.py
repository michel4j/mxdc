# BCM GLOBAL Settings for 08B1-1 Beamline
from mxdc.settings import *
import os
import numpy

BEAMLINE_NAME = '08B1-1'
BEAMLINE_TYPE = 'MX'
BEAMLINE_ENERGY_RANGE = (4.0, 18.5)
BEAMLINE_GONIO_POSITION = 2             # Goniometer orientation (XREC) 1,2,3
ADMIN_GROUPS = [2000]

DEFAULT_EXPOSURE    = 5.0
DEFAULT_ATTENUATION = 90.0               # attenuation in %
DEFAULT_BEAMSTOP    = 60.0
SAFE_DISTANCE       = 400.0
SAFE_BEAMSTOP       = 80.0
XRF_BEAMSTOP        = 100.0
XRF_ENERGY_OFFSET   = 1.0              # KeV

CENTERING_BACKLIGHT = 65.0

LIMS_API_KEY    = "3B7FF046-2726-4195-AC8A-9AE09B207765"

# miscellaneous settings
MISC_SETTINGS = {
    'max_omega_velocity': 120.0,  # deg/sec
}

# maps names to device objects
DEVICES = {
    # Energy, DCM devices, MOSTAB, Optimizers
    'energy':   PseudoMotor('DCM1608-4-B10-01:energy:KeV'),
    'bragg_energy': BraggEnergyMotor('SMTR1608-4-B10-17:deg', motor_type="vmeenc"),
    'dcm_pitch':  ENCMotor('SMTR1608-4-B10-15:deg'),
    'beam_tuner': BOSSTuner('BL08B1:PicoControl'),
    
    # Goniometer/goniometer head devices
    'goniometer': MD2Goniometer('BL08B1:MD2'),
    'omega':    PseudoMotor('PSMTR1608-5-B10-06:pm:deg'),
    'phi': PseudoMotor('PSMTR1608-5-B10-12:pm:deg'),
    'chi': PseudoMotor('PSMTR1608-5-B10-13:pm:deg'),
    'kappa': PseudoMotor('PSMTR1608-5-B10-11:pm:deg'),
    'sample_x':  PseudoMotor('PSMTR1608-5-B10-02:pm:mm', precision=3),
    'sample_y':  PseudoMotor('PSMTR1608-5-B10-07:pm:mm', precision=3),
    
    
    # Beam position & Size
    'aperture': ChoicePositioner('BL08B1:MD2:S:SelectedAperture', choices=[200, 150, 100, 50, 20], units='um'),
    'beam_x':   VMEMotor('SMTR1608-5-B10-08:mm'),
    'beam_y':   VMEMotor('SMTR1608-5-B10-06:mm'),
    'beam_w':   VMEMotor('SMTR1608-5-B10-07:mm'),
    'beam_h':   VMEMotor('SMTR1608-5-B10-05:mm'),
    
    # Detector, distance & two_theta
    'distance': PseudoMotor('BL08B1:det:dist:mm', precision=2),
    'detector_z':  ENCMotor('SMTR1608-5-B10-14:mm', precision=2),
    'two_theta':  PseudoMotor('BL08B1:det:2theta:deg'),
    'detector': ADRayonixImager('CCDC1608-B1-01:cam1', 4096, 'MX300HE'),

    
    # Sample environment, beam stop, cameras, zoom, lighting
    'beamstop_z':  PseudoMotor('PSMTR1608-5-B10-08:pm:mm'),  
    'sample_zoom':  Positioner('BL08B1:MD2:S:ZoomLevel', 'BL08B1:MD2:G:ZoomLevel'),
    #'cryojet':  Cryojet('CSC1608-5-01', 'CSCLVM1608-5-01', 'CSC1608-5-B10-01'),
    'cryojet':  Cryojet5('CSC1608-5-03', 'CSC1608-5-B10-01'),
    'sample_camera': AxisCamera('V2E1608-400', 1),
    'sample_backlight': SampleLight('BL08B1:MD2:S:BlightLevel', 'BL08B1:MD2:G:BlightLevel', 'BL08B1:MD2:S:BlightOnOff', 100.0),
    'sample_frontlight': SampleLight('BL08B1:MD2:S:FlightLevel', 'BL08B1:MD2:G:FlightLevel', 'BL08B1:MD2:S:FlightOnOff',100.0),    
    'hutch_video':  AxisPTZCamera('ccd1608-500'),
    
    # Facility, storage-ring, shutters, etc
    'ring_current':  PV('PCT1402-01:mA:fbk'),
    'ring_mode':  PV('SYSTEM:mode:fbk'),
    'ring_status':  PV('SRStatus:injecting'),
    'storage_ring':  StorageRing('SYSTEM:mode:fbk', 'PCT1402-01:mA:fbk', 'SRStatus'),
    'psh1': Shutter('PSH1408-B10-01'),
    'psh2': Shutter('PSH1408-B10-02'),
    'ssh1': Shutter('SSH1408-B10-01'),
    'ssh3': Shutter('SSH1608-4-B10-01'),
    'enclosures': Enclosures(poe='ACIS1608-5-B10-01:poe1:secure', soe='ACIS1608-5-B10-01:soe1:secure'),
    'exposure_shutter': BasicShutter('BL08B1:MD2:S:OpenFastShutter','BL08B1:MD2:S:CloseFastShutter','BL08B1:MD2:G:ShutterIsOpen'),
    
    # Intensity monitors,
    'i_0': Counter('BPM08B1-05:I0:fbk'),
    #'i_1': Counter('BPM08B1-04:I0:fbk'),
    'i_1': Counter('BPM08B1-02:I0:fbk'),
    'i_bst':  Counter('BL08B1:MD2:G:ExternalPhotoDiode'),
    'i_scn':  Counter('BL08B1:MD2:G:InternalPhotoDiode'),
    
    # Misc: Automounter, HC1 etc
    'automounter':  Automounter('ROB16085B', 'ROB1608-500'),
    'humidifier': Humidifier('HC1608-01'),
    'attenuator': Attenuator2('PFIL1608-5-B10-01', 'DCM1608-4-B10-01:energy:KeV:fbk'),
    'mca_nozzle': Positioner('BL08B1:MD2:S:MoveFluoDetFront'),
    'mca': XFlashMCA('XFD1608-501'),
    'multi_mca': VortexMCA('dxp1608-004'),
    'deicer': OnOffToggle('DIC1608-5-B10-01:spray:on'),

    #disk space monitor
    'disk_space' : DiskSpaceMonitor('Disk Space', '/users'), 
}

# lims, dpm, imagesync and other services
SERVICES = {
    'image_server': ImageSyncClient(),
    'lims': LIMSClient('https://cmcf.lightsource.ca'),
    'dpm': DPMClient(),
}

# Beamline shutters in the order in which they should be opened
BEAMLINE_SHUTTERS = ('ssh1', 'psh1', 'psh2', 'ssh3')  

# Devices only available in the console
CONSOLE_DEVICES = {
    'vcm_y': PseudoMotor('SCM1608-4-B10-01:ht:mm'),
    'vcm_pitch': PseudoMotor('SCM1608-4-B10-01:pitch:mrad'),
    'vcm_x': PseudoMotor('SMTR1608-4-B10-08:mm'),
    'vcm_yaw': ENCMotor('SMTR1608-4-B10-09:deg'),
    'vcm_bend': PseudoMotor('SCM1608-4-B10-01:bnd:m'),
    'tfm_bend': PseudoMotor('TDM1608-4-B10-01:bnd:m'),
    'tfm_y': PseudoMotor('TDM1608-4-B10-01:ht:mm'),
    'tfm_yaw': ENCMotor('SMTR1608-4-B10-26:deg'),
    'tfm_pitch': PseudoMotor('TDM1608-4-B10-01:pitch:mrad'),
    'tfm_roll':  PseudoMotor('TDM1608-4-B10-01:roll:mrad'),
    'tfm_x': ENCMotor('SMTR1608-4-B10-25:mm'),
    'dcm_roll1': ENCMotor('SMTR1608-4-B10-16:deg'),
    'dcm_roll2': ENCMotor('SMTR1608-4-B10-12:deg'),
    'dcm_yaw': ENCMotor('SMTR1608-4-B10-13:deg'),
    'dcm_y': VMEMotor('SMTR1608-4-B10-18:mm'),
    'dcm_y2': ENCMotor('SMTR1608-4-B10-14:mm'),
    'dcm_x': VMEMotor('SMTR1608-4-B10-19:mm'),
    'wbs_hgap': PseudoMotor('PSL1608-4-B10-02:gap:mm'),
    'wbs_vgap': PseudoMotor('PSL1608-4-B10-01:gap:mm'),
    'wbs_x': PseudoMotor('PSL1608-4-B10-02:cntr:mm'),
    'wbs_y': PseudoMotor('PSL1608-4-B10-01:cntr:mm'),
    'wbs_top': ENCMotor('SMTR1608-4-B10-01:mm'),
    'wbs_bot': ENCMotor('SMTR1608-4-B10-02:mm'),
    'wbs_out': ENCMotor('SMTR1608-4-B10-04:mm'),
    'wbs_in': ENCMotor('SMTR1608-4-B10-03:mm'),
    'mbs_top': ENCMotor('SMTR1608-4-B10-20:mm'),
    'mbs_bot': ENCMotor('SMTR1608-4-B10-21:mm'),
    'mbs_vgap': PseudoMotor('PSL1608-4-B10-03:gap:mm'),
    'mbs_y': PseudoMotor('PSL1608-4-B10-03:cntr:mm'),
    'es1_vgap': VMEMotor('SMTR1608-5-B10-01:mm'),
    'es1_hgap': VMEMotor('SMTR1608-5-B10-03:mm'),
    'es1_x': VMEMotor('SMTR1608-5-B10-04:mm'),
    'es1_y': VMEMotor('SMTR1608-5-B10-02:mm'),
    'es2_vgap': VMEMotor('SMTR1608-5-B10-05:mm'),
    'es2_hgap': VMEMotor('SMTR1608-5-B10-07:mm'),
    'es2_x': VMEMotor('SMTR1608-5-B10-08:mm'),
    'es2_y': VMEMotor('SMTR1608-5-B10-06:mm'),
    'gt_y': PseudoMotor('TBL1608-5-B10-01:ht:mm'),
    'gt_pitch': PseudoMotor('TBL1608-5-B10-01:pitch:mrad'),
    'gt_yaw': PseudoMotor('TBL1608-5-B10-01:yaw:mrad'),
    'gt_roll': PseudoMotor('TBL1608-5-B10-01:roll:mrad'),
    'gt_x': PseudoMotor('TBL1608-5-B10-01:htrans:mm'),
    'gt_x1': ENCMotor('SMTR1608-5-B10-12:mm'),
    'gt_x2': ENCMotor('SMTR1608-5-B10-13:mm'),
}
