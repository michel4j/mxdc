import mxdc.devices.shutter
from mxdc.beamlines import Beamline
from mxdc.devices import misc, diagnostics, motor, video
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class MXBeamline(Beamline):
    REQUIRED = [
        'energy', 'bragg_energy', 'beam_tuner', 'manager',
        'goniometer',  'aperture', 'distance', 'two_theta',

        'detector', 'beamstop_z', 'sample_zoom',
        'cryojet', 'sample_camera', 'sample_backlight', 'sample_frontlight',
        'hutch_video', 'synchrotron', 'fast_shutter', 'enclosures',
        'automounter', 'attenuator', 'mca', 'i0',
        'disk_space',

        # services
        'dss', 'lims', 'dps', 'messenger'
    ]
    DEFAULTS = {
        'name': 'SIM-1',
        'mono.type': 'Si 111',
        'mono.cell': 5.4297575,
        'admins': [],
        'energy_range': (6.0, 18.0),
        'beam_shape': (100., 100.),
        'distance_limits': (100.0, 1000.0),

        'safe.beamstop': 25.0,
        'safe.distance': 700.0,

        'xrf.beamstop': 50.0,
        'xrf.attenuation': 90,
        'xrf.exposure': 0.5,

        'raster.max_freq': 100,
        'raster.max_speed': 0.5,
        'raster.exposure': 0.5,

        'dataset.overhead': 5,
        'dataset.exposure': 0.5,
        'dataset.distance': 200,
        'dataset.energy': 12.658,
        'dataset.beamstop': 30,
        'dataset.delta': 0.5,
        'centering.show_bbox': False,
        'dataset.attenuation': 0.0,
        'automation.unattended': False,
        'minimum_exposure': 0.1,

        'zoom.levels': (1, 4, 6),
        'zoom.centering': 2,

        'shutter_sequence': [],
        'orientation': 1,
    }

    def setup(self):
        # create sample_video Zoomable camera
        if "camera_scale" not in self.registry:
            self.registry['camera_scale'] = misc.CamScaleFromZoom(self.sample_zoom, width=self.sample_camera.size[0])
            self.registry['camera_scale'].set_label('camera_scale')

        self.registry['sample_video'] = video.ZoomableCamera(self.sample_camera, self.sample_zoom)

        # Setup Bealine shutters
        _shutter_list = []
        for nm in self.config['shutter_sequence']:
            _shutter_list.append(self.registry[nm])

        self.registry['all_shutters'] = mxdc.devices.shutter.ShutterGroup(*tuple(_shutter_list), close_last=True)
        self.registry['all_shutters'].set_label('all_shutters')

        # default detector cover
        if 'detector_cover' not in self.registry:
            self.registry['detector_cover'] = mxdc.devices.shutter.SimShutter('Dummy Detector Cover')
            self.registry['detector_cover'].set_label('detector_cover')

        # detector max resolution
        self.registry['maxres'] = motor.ResolutionMotor(self.energy, self.distance, self.detector.mm_size)
        self.registry['maxres'].set_label('maxres')

        # Setup diagnostics on some devices
        device_list = [
            'automounter', 'goniometer', 'detector', 'cryojet', 'mca',
            'enclosures', 'all_shutters', 'synchrotron'
        ]
        self.diagnostics = []
        for name in device_list:
            self.diagnostics.append(diagnostics.DeviceDiag(self.registry[name]))

        for name in ['dss', 'dps', 'lims', ]:
            self.diagnostics.append(diagnostics.ServiceDiag(self.registry[name]))

        self.diagnostics.append(diagnostics.DeviceDiag(self.registry['disk_space']))
        self.emit('ready', True)


class DummyBeamline(Beamline):

    def setup(self):
        self.emit('ready', True)


__all__ = ['MXBeamline']
