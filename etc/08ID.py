# BCM GLOBAL Settings for 08B1-1 Beamline
from bcm.settings import *  # @UnusedWildImport

BEAMLINE_NAME = '08ID-1'
BEAMLINE_TYPE = 'MX'
BEAMLINE_ENERGY_RANGE = (6.0, 18.5)
BEAMLINE_GONIO_POSITION = 3             # Goniometer orientation (XREC) 1,2,3
ADMIN_GROUP = 2000

DEFAULT_EXPOSURE    = 1.0
DEFAULT_ATTENUATION = 90.0              # attenuation in %
DEFAULT_BEAMSTOP    = 30.0
SAFE_BEAMSTOP       = 50.0
SAFE_DISTANCE       = 400.0
XRF_BEAMSTOP        = 30.0
XRF_ENERGY_OFFSET   = +2.0              # KeV

CENTERING_BACKLIGHT = 37.0


# miscellaneous settings
MISC_SETTINGS = {
    'aperture_in_position': 3.63,
    'aperture_out_position': 26.5,
    'max_omega_velocity': 30.0,  # deg/sec
}

LIMS_API_KEY    = "DE5C410E-6D59-4DE8-AFFC-3FF5F367359E"

# maps names to device objects
DEVICES = {
    # Energy, DCM devices, MOSTAB, Optimizers
    'energy':   EnergyMotor('BL08ID1:energy', 'SMTR16082I1005:deg'),
    'bragg_energy': BraggEnergyMotor('SMTR16082I1005:deg', motor_type="vme"),
    'dcm_pitch':  VMEMotor('SMTR16082I1010:deg'),
    'mostab': MostabPIDController('MOS16082I1001'),
    
    # Goniometer/goniometer head devices
    'goniometer': Goniometer('GV6K1608-001', 'OAV1608-3-I10-01', 'ROB16083I', 'PM1608-3-I10-02:pm:mm'),
    'omega':    VMEMotor('GV6K1608-001:deg'),
    #'sample_x':  VMEMotor('SMTR16083I1011:mm'),
    'sample_x': VMEMotor('SMTR16083I1008:mm'),
    'sample_y2':  VMEMotor('SMTR16083I1012:mm'), # if no sample_y, it will be determined from
    'sample_y1':  VMEMotor('SMTR16083I1013:mm'), # orthogonal sample_y1 AND sample_y2
    
    # Beam position & Size
    'aperture': SimPositioner('Aperture', 50.0, 'um', active=False),
    'beam_x':   VMEMotor('SMTR16083I1002:mm'),
    'beam_y':   VMEMotor('SMTR16083I1004:mm'),
    'beam_w':   VMEMotor('SMTR16083I1001:mm'),
    'beam_h':   VMEMotor('SMTR16083I1003:mm'),
    
    # Detector, distance & two_theta
    'distance': PseudoMotor('BL08ID1:2Theta:D:mm'),
    'detector_z':  ENCMotor('SMTR16083I1018:mm'),
    'two_theta':  PseudoMotor('BL08ID1:2Theta:deg'),
    'detector': MXCCDImager('BL08ID1:CCD', 4096, 0.07243, 'MX300'),
    
    # Sample environment, beam stop, cameras, zoom, lighting
    'beamstop_z':  VMEMotor('SMTR16083I1016:mm'),  
    'sample_zoom':  VMEMotor('SMTR16083I1025:mm'),
    'camera_center_x':  Positioner('BL08ID1:video:sample:x'),
    'camera_center_y':  Positioner('BL08ID1:video:sample:y'),
    'cryojet':  Cryojet('cryoCtlr', 'cryoLVM', 'CSC1608-3-I10-01'),
    'sample_camera': AxisCamera('V2E1608-001', 4),
    'sample_backlight': SampleLight('ILC1608-3-I10-02:sp', 'ILC1608-3-I10-02:fbk','ILC1608-3-I10-02:on', 100.0),
    'sample_frontlight': SampleLight('ILC1608-3-I10-01:sp', 'ILC1608-3-I10-01:fbk','ILC1608-3-I10-01:on', 100.0),    
    'hutch_video':  AxisPTZCamera('CCD1608-301'),
    
    # Facility, storage-ring, shutters, etc
    'ring_current':  PV('PCT1402-01:mA:fbk'),
    'ring_mode':  PV('SYSTEM:mode:fbk'),
    'ring_status':  PV('SRStatus:injecting'),
    'storage_ring':  StorageRing('SYSTEM:mode:fbk', 'PCT1402-01:mA:fbk', 'SRStatus'),
    'psh1': Shutter('PSH1408-I00-01'),
    'psh2': Shutter('PSH1408-I00-02'),
    'ssh1': Shutter('SSH1408-I00-01'),
    'ssh2': Shutter('SSH1608-2-I10-01'),
    #'ssh2': StateLessShutter('SSH1608-2-I10-01:opr:open', 'SSH1608-2-I10-01:opr:close'),
    'exposure_shutter': Shutter('PSH16083I1001'),
    
    # Intensity monitors,
    'i_0': Counter('BPM08ID1-03:I0:fbk'),
    'i_1': Counter('BPM08ID1-02:I0:fbk'),
    'i_2': Counter('BPM08ID1-01:I0:fbk'),
    'i_4': Counter('A1608-3-06:A:fbk'),
      
    # Misc: Automounter, HC1 etc
    'automounter':  Automounter('ROB16083I', 'ROB1608-300'),
    #'humidifier': HumidityController('HC1608-01'),
    'attenuator': Attenuator('PFIL1608-3-I10-01', 'BL08ID1:energy'),
    'mca': XFlashMCA('XFD1608-101'),
    
    #disk space monitor
    'disk_space' : DiskSpaceMonitor('Disk Space', '/users'), 
}

# lims, dpm, imagesync and other services
SERVICES = {
    'image_server': ImageSyncClient(),
    'lims': LIMSClient('https://cmcf.lightsource.ca/json/'),
    'dpm': DPMClient('srv-cmcf-dp2:8881'),
}

# Beamline shutters in the order in which they should be opened
BEAMLINE_SHUTTERS = ('ssh1', 'psh1', 'psh2', 'ssh2')

# Devices only available in the console
CONSOLE_DEVICES = {
    'vfm_bend': PseudoMotor2('BL08ID1:VFM:Focus:foc'),
    'vfm_y': PseudoMotor2('BL08ID1:VFMHeight:mm'),
    'vfm_yaw': PseudoMotor2('BL08ID1:VFMTrans:yaw:mm'),
    'vfm_pitch': PseudoMotor2('BL08ID1:VFMPitch:mrad'),
    'vfm_roll':  PseudoMotor2('BL08ID1:VFMRoll:mrad'),
    'vfm_x': PseudoMotor2('BL08ID1:VFMTrans:cm'),
    'dcm_roll1': VMEMotor('SMTR16082I1007:deg'),
    'dcm_roll2': VMEMotor('SMTR16082I1008:deg'),
    'dcm_pitch': VMEMotor('SMTR16082I1010:deg'),
    'dcm_yaw': VMEMotor('SMTR16082I1009:deg'),
    'dcm_y': VMEMotor('SMTR16082I1006:mm'),
    'dcm_t1': VMEMotor('SMTR16082I1011:mm'),
    'dcm_t2': VMEMotor('SMTR16082I1012:mm'),
    'dcm_bend': VMEMotor('BL08ID1:C2NewBndRad:mm'),
    'wbs_hgap': PseudoMotor2('PSL16082I1001:gap:mm'),
    'wbs_vgap': PseudoMotor2('PSL16082I1002:gap:mm'),
    'wbs_x': PseudoMotor2('PSL16082I1001:cntr:mm'),
    'wbs_y': PseudoMotor2('PSL16082I1002:cntr:mm'),
    'mbs_top': VMEMotor('SMTR16082I1017:mm'),
    'mbs_bot': VMEMotor('SMTR16082I1018:mm'),
    'es_vgap': VMEMotor('SMTR16083I1001:mm'),
    'es_hgap': VMEMotor('SMTR16083I1003:mm'),
    'es_x': VMEMotor('SMTR16083I1002:mm'),
    'es_y': VMEMotor('SMTR16083I1004:mm'),
    'gonio_y': VMEMotor('SMTR16083I1009:mm'),
    'gonio_x': VMEMotor('SMTR16083I1008:mm'),
    'exbox_pitch': VMEMotor('SMTR16083I1007:mm'),
    'exbox_x': VMEMotor('SMTR16083I1005:mm'),
    'exbox_y': VMEMotor('SMTR16083I1006:mm'),
    'beamstop_x':  VMEMotor('SMTR16083I1014:mm'),
    'beamstop_y':  VMEMotor('SMTR16083I1015:mm'),
}
