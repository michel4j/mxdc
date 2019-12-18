# BCM GLOBAL Settings for SIM Beamline

from mxdc.com import ca
from mxdc.devices import motor, goniometer, cryojet, boss, detector, synchrotron
from mxdc.devices import humidity, video, misc, mca, counter, manager
from mxdc.devices.automounter import sim, isara
from mxdc.services import clients


CONFIG = {
    'name': 'SIM-2',
    'facility': 'CLS',
    'mono': 'Si 111',
    'mono_unit_cell': 5.4297575,
    'source': 'CLS Sim SGU',
    'type': 'mx',
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

    # Goniometer/goniometer head devices
    'manager': manager.MD2Manager('MD1608-301'),
    'goniometer': goniometer.MD2Gonio('MD1608-301'),
    'omega':    motor.PseudoMotor('PMTR1608-301:omega:deg'),
    'sample_x':  motor.PseudoMotor('PMTR1608-301:gonX:mm'),
    'sample_y1':  motor.PseudoMotor('PMTR1608-301:smplY:mm'),
    'sample_y2':  motor.PseudoMotor('PMTR1608-301:smplZ:mm'),

    # Beam position & Size
    'aperture': misc.ChoicePositioner('MD1608-301:CurrentApertureDiameterIndex', choices=[50, 30, 20, 10, 5], units='um'),

    # Detector, distance & two_theta
    'distance': tmp1,
    'detector_z': tmp1,
    'two_theta': motor.SimMotor('Detector Two Theta', 0.0, 'deg', speed=5.0),
    'detector': detector.SimDetector('Simulated CCD Detector', size=4096, pixel_size=0.07243),
    #'detector': detector.ADSCDetector('13ADCS1:cam1', size=4096, pixel_size=0.07243),

    # Sample environment, beam stop, cameras, zoom, lighting
    'beamstop_z':  motor.PseudoMotor('PMTR1608-301:bstZ:mm'),
    'sample_zoom':  motor.PseudoMotor('PMTR1608-301:zoom:pos'),
    'cryojet': cryojet.SimCryoJet('Simulated Cryojet'),
    # 'sample_camera': SimCamera(),
    'camera_scale': misc.Positioner('MD1608-301:CoaxCamScaleX', 'MD1608-301:CoaxCamScaleX'),
    #'sample_camera': video.REDISCamera('v2e1608-301.clsi.ca', mac='000F31031D82', zoom_slave=True),
    #'sample_camera': video.MJPGCamera('http://10.52.7.219:1313/bzoom'),
    'sample_camera': video.REDISCamera('v2e1608-501.clsi.ca', mac='bzoom', size=(1280,1024), zoom_slave=False),

    'sample_backlight': misc.SampleLight('MD1608-301:BackLightLevel', 'MD1608-301:BackLightLevel', 'MD1608-301:BackLightIsOn', 100.0),
    'sample_frontlight': misc.SampleLight('MD1608-301:FrontLightLevel', 'MD1608-301:FrontLightLevel', 'MD1608-301:FrontLightIsOn',100.0),

    #'sample_backlight': misc.SimLight('Back light', 45.0, '%'),
    #'sample_frontlight': misc.SimLight('Front light', 55.0, '%'),
    #'sample_uvlight': misc.SimLight('UV light', 25.0, '%'),
    'sample_uvlight': misc.SampleLight('BL08ID1:UVLight', 'BL08ID1:UVLight:fbk', 'BL08ID1:UVLight:OnOff', 100.0),

    # 'hutch_video':  SimPTZCamera(),
    'hutch_video': video.AxisPTZCamera('ccd1608-302.clsi.ca'),

    # Facility, storage-ring, shutters, etc
    'synchrotron': synchrotron.SimStorageRing('Simulated Storage Ring'),
    #'synchrotron':  synchrotron.StorageRing('SYSTEM:mode:fbk', 'PCT1402-01:mA:fbk', 'SRStatus'),
    'psh1': misc.SimShutter('PSH1'),
    'ssh1': misc.SimShutter('SSH2'),
    'psh2': misc.SimShutter('PSH2'),
    #'fast_shutter': misc.SimShutter('Fast Shutter'),
    'fast_shutter': misc.ToggleShutter('MD1608-301:FastShutterIsOpen'),
    'enclosures': misc.Enclosures(poe='ACIS1608-5-B10-01:poe1:secure', soe='ACIS1608-5-B10-01:soe1:secure'),

    # Intensity monitors, shutter, attenuation, mca etc
    'i_0': counter.SimCounter('I_0', zero=26931),
    'i_1': counter.SimCounter('I_1', zero=35019),
    'i_2': counter.SimCounter('I_2', zero=65228),

    # Misc: Automounter, HC1 etc
    'automounter': sim.SimSAM(),
    #'automounter': isara.AuntISARA('ISARA1608-301'),
    #'automounter': automounter.ISARAMounter('BOT1608-I01'),
    'humidifier': humidity.SimHumidifier(),
    'attenuator': misc.SimPositioner('Attenuator', 0.0, '%'),
    'mca': mca.SimMultiChannelAnalyzer('Simulated MCA', energy=tmp2),
    'multi_mca': mca.SimMultiChannelAnalyzer('Simulated MCA', energy=tmp2),

    # disk space monitor
    'disk_space': misc.DiskSpaceMonitor('Disk Space', '/users', warn=0.2, critical=0.1, freq=30),
}

# lims, dpm, imagesync and other services
SERVICES = {
    'dss': clients.DSSClient(),
    #'lims': clients.MxLIVEClient('https://mxlive.lightsource.ca'),
    'lims': clients.MxLIVEClient('http://127.0.0.1:8000'),
    'dps': clients.DPSClient('hpc1608-001.clsi.ca:9991'),
    'messenger': clients.Messenger('cmcf.lightsource.ca', realm=CONFIG['name'])
}
