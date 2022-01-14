import os
import time
from datetime import datetime

import numpy
import pytz
from zope.interface import Interface, implementer

from mxdc import Registry, Signal, Engine
from mxdc.devices.goniometer import GonioFeatures
from mxdc.utils import datatools, misc, decorators
from mxdc.utils.converter import energy_to_wavelength
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class IRasterCollector(Interface):
    """Raster Collector."""

    def configure(grid, parameters):
        """Configure the collector"""

    def start():
        """Run the acquisition asynchronously"""


@implementer(IRasterCollector)
class RasterCollector(Engine):
    class Signals:
        result = Signal('result', arg_types=(int, object))
        grid = Signal('grid', arg_types=(object,))

    def __init__(self):
        super().__init__()
        self.runs = []
        self.results = {}
        self.config = {}
        self.total_frames = 0
        self.count = 0
        Registry.add_utility(IRasterCollector, self)

    def configure(self, params):
        self.config['params'] = params

        # calculate grid from dimensions
        grid = misc.grid_from_size(
            (params['frames'], params['lines']), params['aperture'] * 1e-3, (0, 0), tight=False, snake=True
        )
        ox, oy, oz = self.beamline.goniometer.stage.get_xyz()
        gx, gy, gz = self.beamline.goniometer.stage.xvw_to_xyz(
            grid[:, 0], grid[:, 1], numpy.radians(params['angle'])
        )
        grid_xyz = numpy.dstack([gx + ox, gy + oy, gz + oz])[0]

        # update microscope display
        self.config['params']['grid'] = grid_xyz

    def get_grid(self):
        return self.config['params'].get('grid')

    def prepare(self, params):
        self.count = 0
        self.total_frames = self.config['params']['frames'] * self.config['params']['lines']
        self.results = {}

        # setup folder for
        self.beamline.dss.setup_folder(params['directory'], misc.get_project_name())

        # make sure shutter is closed before starting
        self.beamline.fast_shutter.close()

        if abs(self.beamline.distance.get_position() - params['distance']) >= 0.1:
            self.beamline.distance.move_to(params['distance'], wait=True)

        # switch to collect mode
        self.beamline.manager.collect(wait=True)

    def run(self):
        current_attenuation = self.beamline.attenuator.get_position()
        with self.beamline.lock:
            self.config['start_time'] = datetime.now(tz=pytz.utc)
            self.emit('started', self.config['params'])

            self.prepare(self.config['params'])

            # prepare for analysis
            template = self.beamline.detector.get_template(self.config['params']['name'])
            params = {
                'template': template,
                'type': 'file',
                'directory': self.config['params']['directory'],
                'first': 1,
                'num_frames': self.total_frames,
                'timeout': max(self.config['params']['exposure'] * self.total_frames * 10, 180)
            }
            if self.beamline.detector.monitor_type == 'stream':
                params.update({
                    'type': self.beamline.detector.monitor_type,
                    'address': self.beamline.detector.monitor_address,
                })
            res = self.beamline.dps.signal_strength(**params, user_name=misc.get_project_name())
            res.connect('update', self.on_raster_update, os.path.join(self.config['params']['directory'], template,))
            res.connect('failed', self.on_raster_failed)

            try:
                # raster scan proper
                if self.beamline.goniometer.supports(GonioFeatures.RASTER4D, GonioFeatures.TRIGGERING):
                    self.acquire_slew()
                else:
                    self.acquire_step()
                self.beamline.goniometer.stage.move_xyz(*self.config['params']['origin'], wait=True)
                self.beamline.goniometer.omega.move_to(self.config['params']['angle'], wait=True)

                # take snapshot
                self.beamline.manager.center(wait=True)
                logger.info('Taking snapshot ...')
                img = self.beamline.sample_camera.get_frame()
                img.save(
                    os.path.join(self.config['params']['directory'], '{}.png'.format(self.config['params']['name']))
                )
            finally:
                self.beamline.fast_shutter.close()

        if self.stopped:
            self.emit('stopped', None)
        else:
            self.emit('done', None)
        self.beamline.attenuator.move_to(current_attenuation)  # restore attenuation

    def acquire_step(self):
        logger.debug('Rastering ... ')
        for i, frame in enumerate(datatools.grid_frames(self.config['params'])):
            if self.paused:
                self.emit('paused', True, '')
                while self.paused and not self.stopped:
                    time.sleep(0.1)
                self.emit('paused', False, '')

            if self.stopped: break

            # Prepare image header
            template = self.beamline.detector.get_template(self.config['params']['name'])
            detector_parameters = {
                'file_prefix': frame['name'],
                'start_frame': frame['first'],
                'directory': frame['directory'],
                'wavelength': energy_to_wavelength(frame['energy']),
                'energy': frame['energy'],
                'distance': frame['distance'],
                'exposure_time': frame['exposure'],
                'num_frames': 1,
                'start_angle': frame['start'],
                'delta_angle': frame['delta'],
                'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
            }

            # perform scan
            if self.stopped or self.paused: break
            self.beamline.detector.configure(**detector_parameters)
            self.beamline.detector.start()
            self.beamline.goniometer.scan(
                time=frame['exposure'],
                range=frame['delta'],
                frames=1,
                angle=frame['start'],
                start_pos=frame['p0'],
                wait=True,
                timeout=frame['exposure'] * 20
            )
            self.beamline.detector.save()
            time.sleep(0)

    def acquire_slew(self):
        logger.debug('Setting up detector for rastering ... ')

        # Prepare detector
        params = self.config['params']
        detector_parameters = {
            'file_prefix': params['name'],
            'start_frame': 1,
            'directory': params['directory'],
            'wavelength': energy_to_wavelength(params['energy']),
            'energy': params['energy'],
            'distance': params['distance'],
            'exposure_time': params['exposure'],
            'num_frames': self.total_frames,
            'start_angle': params['angle'],
            'delta_angle': params['delta'],
            'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
        }

        self.beamline.detector.configure(**detector_parameters)
        self.beamline.detector.start()

        logger.debug('Starting raster scan ...')
        self.beamline.goniometer.scan(
            kind='raster',
            time=params['exposure'] * params['frames'],
            range=params['delta'] * params['frames'],
            angle=params['angle'],
            frames=params['frames'],
            lines=params['lines'],
            width=params['width'],
            height=params['height'],
            start_pos=params['grid'][0],
            wait=True,
            timeout=params['exposure'] * self.total_frames * 10,
        )
        self.beamline.detector.save()
        time.sleep(0)

    def on_raster_update(self, result, info, template):
        self.results[info['frame_number']] = info
        info['filename'] = template.format(info['frame_number'])
        self.emit('result', info['frame_number'], info)
        self.count += 1

        fraction = self.count/self.total_frames
        msg = '{}: {} of {}'.format(self.config['params']['name'], self.count, self.total_frames)
        self.emit('progress', fraction, msg)

    def on_raster_done(self, result, data):
        if not self.stopped:
            self.emit('progress', 1.0, 'Rastering analysis completed')
            self.save_metadata()

    def on_raster_failed(self, result, error):
        logger.error(f"Unable to process data: {error}")
        if not self.stopped:
            self.emit('progress', 1.0, 'Rastering analysis failed')
            self.save_metadata()

    @decorators.async_call
    def pause(self, reason=''):
        super().pause(reason)
        if self.beamline.goniometer.supports(GonioFeatures.RASTER4D, GonioFeatures.TRIGGERING):
            self.beamline.detector.stop()
            self.beamline.goniometer.stop()

    @decorators.async_call
    def stop(self):
        super().stop()
        if self.beamline.goniometer.supports(GonioFeatures.RASTER4D, GonioFeatures.TRIGGERING):
            self.beamline.detector.stop()
            self.beamline.goniometer.stop()

    def save_metadata(self, upload=True):
        self.config['end_time'] = datetime.now(tz=pytz.utc)
        params = self.config['params']
        template = self.beamline.detector.get_template(params['name'])
        wild_card = datatools.template_to_glob(template)

        try:
            info = datatools.dataset_from_files(params['directory'], wild_card)
        except OSError as e:
            logger.error('Unable to find files on disk')
            return

        if info['num_frames'] > 1:
            metadata = {
                'name': params['name'],
                'frames': info['frames'],
                'filename': self.beamline.detector.get_template(params['name']),
                'container': params['container'],
                'port': params['port'],
                'type': 'RASTER',
                'start_time': self.config['start_time'].isoformat(),
                'end_time': self.config['end_time'].isoformat(),
                'sample_id': params['sample_id'],
                'uuid': params['uuid'],
                'directory': params['directory'],

                'energy': params['energy'],
                'attenuation': params['attenuation'],
                'exposure': params['exposure'],

                'detector_type': self.beamline.detector.detector_type,
                'beam_size': self.beamline.aperture.get_position(),
                'beam_x': self.beamline.detector.get_origin()[0],
                'beam_y': self.beamline.detector.get_origin()[1],
                'pixel_size': self.beamline.detector.resolution,
                'resolution': params['resolution'],
                'detector_size': min(self.beamline.detector.size),
                'start_angle': params['angle'],
                'delta_angle': params['delta'],
                'inverse_beam': params.get('inverse', False),
                'grid_origin': params['origin'],
                'grid_points': params['grid'].tolist(),
            }
            filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
            misc.save_metadata(metadata, filename)
            if upload:
                self.beamline.lims.upload_data(self.beamline.name, filename)
            return metadata