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
        'admin_groups': [2000],
        'energy_range': (6.0, 18.0),
        'zoom_levels': (1, 4, 6),
        'distance_limits': (100.0, 1000.0),
        'default_attenuation': 90.0,
        'default_exposure': 0.5,
        'default_delta': 0.5,
        'default_energy': 12.658,
        'default_distance': 200,
        'default_beamstop': 25.0,
        'safe_beamstop': 25.0,
        'safe_distance': 700.0,
        'xrf_beamstop': 50.0,
        'xrf_fwhm': 0.1,
        'xrf_energy_offset': 2.0,
        'shutter_sequence': [],
        'orientation': 1,
        'centering_backlight': 65,
    }

    def setup(self):
        # create sample_video Zoomable camera
        if not "camera_scale" in self.registry:
            self.registry['camera_scale'] = misc.CamScaleFromZoom(self.sample_zoom, width=self.sample_camera.size[0])

        self.registry['sample_video'] = video.ZoomableCamera(self.sample_camera, self.sample_zoom)

        # Setup Bealine shutters
        _shutter_list = []
        for nm in self.config['shutter_sequence']:
            _shutter_list.append(self.registry[nm])
        self.registry['all_shutters'] = mxdc.devices.shutter.ShutterGroup(*tuple(_shutter_list), close_last=True)

        # Setup coordination between Beam tuner and energy changes
        if 'beam_tuner' in self.registry:

            def on_bt_pause(obj, *args):
                self.beam_tuner.pause()

            def on_bt_resume(obj, *args):
                self.beam_tuner.resume()

            self.energy.connect('starting', on_bt_pause)
            self.energy.connect('done', on_bt_resume)

        # default detector cover
        if not 'detector_cover' in self.registry:
            self.registry['detector_cover'] = mxdc.devices.shutter.SimShutter('Dummy Detector Cover')

        # detector max resolution
        self.registry['maxres'] = motor.ResolutionMotor(self.energy, self.distance, self.detector.mm_size)

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
