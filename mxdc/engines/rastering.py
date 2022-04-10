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
        complete = Signal('complete', arg_types=(object,))

    def __init__(self):
        super().__init__()
        self.runs = []
        self.results = {}
        self.config = {}
        self.total_frames = 0
        self.count = 0
        self.complete = False
        Registry.add_utility(IRasterCollector, self)

    def is_complete(self):
        return self.complete

    def configure(self, params):
        self.config['params'] = params

        # calculate grid from dimensions
        grid, index = misc.grid_from_size(
            (params['hsteps'], params['vsteps']), params['aperture'] * 1e-3, (0, 0), **self.beamline.goniometer.grid_settings()
        )
        ox, oy, oz = self.beamline.goniometer.stage.get_xyz()
        gx, gy, gz = self.beamline.goniometer.stage.xvw_to_xyz(
            grid[:, 0], grid[:, 1], numpy.radians(params['angle'])
        )
        grid_xyz = numpy.dstack([gx + ox, gy + oy, gz + oz])[0]
        self.config['params']['grid'] = grid_xyz

        # update for microscope display
        shape = (params['hsteps'], params['vsteps'])
        self.config['properties'] = {
            'grid_xyz': grid_xyz,
            'grid_bbox': [],
            'grid_index': index,
            'grid_scores': -numpy.ones(shape[::-1]),
            'grid_params': {
                'origin': (ox, oy, oz),
                'directory': params['directory'],
                'width': shape[0]*params['aperture'],
                'height': shape[1]*params['aperture'],
                'angle': params['angle'],
                'shape': shape,
            },
        }

    def get_grid(self):
        return self.config['properties']

    def get_parameters(self):
        return self.config['params']

    def prepare(self, params):
        self.count = 0
        self.total_frames = self.config['params']['hsteps'] * self.config['params']['vsteps']
        self.config['params']['framesets'] = datatools.summarize_list(
            [i + 1 for i in range(self.total_frames)]
        )
        self.results = {}

        # setup folder for
        self.beamline.dss.setup_folder(params['directory'], misc.get_project_name())

        # make sure shutter is closed before starting
        self.beamline.fast_shutter.close()

        if abs(self.beamline.distance.get_position() - params['distance']) >= 0.1:
            self.beamline.distance.move_to(params['distance'], wait=True)

        # switch to collect mode
        self.beamline.manager.collect(wait=True)

    def run(self, centering=False):
        self.complete = False
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
            res.connect('update', self.on_raster_update, os.path.join(self.config['params']['directory'], template, ))
            res.connect('failed', self.on_raster_failed)
            res.connect('done', self.on_raster_done)

            try:
                # raster scan proper
                if self.beamline.goniometer.supports(GonioFeatures.RASTER4D, GonioFeatures.TRIGGERING):
                    self.acquire_slew()
                else:
                    self.acquire_step()
                self.beamline.goniometer.stage.move_xyz(*self.config['params']['origin'], wait=True)
                self.beamline.goniometer.omega.move_to(self.config['params']['angle'], wait=True)
                time.sleep(1)
            finally:
                self.beamline.fast_shutter.close()
                if not centering:
                    self.beamline.manager.center(wait=True)
                    self.beamline.attenuator.move_to(current_attenuation)  # restore attenuation

        if self.stopped:
            self.emit('stopped', None)
        else:
            self.emit('done', None)

    def acquire_step(self):
        logger.debug('Rastering ... ')
        for i, frame in enumerate(datatools.grid_frames(self.config['params'])):
            if self.stopped: break

            # Prepare image header
            template = self.beamline.detector.get_template(self.config['params']['name'])
            owner = misc.get_project_name()
            group = misc.get_group_name()
            detector_parameters = {
                'file_prefix': frame['name'],
                'start_frame': frame['first'],
                'directory': frame['directory'],
                'wavelength': energy_to_wavelength(frame['energy']),
                'energy': frame['energy'],
                'distance': frame['distance'],
                'exposure_time': frame['exposure'],
                'frame_size': 1,
                'num_frames': 1,
                'start_angle': frame['start'],
                'delta_angle': frame['delta'],
                'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
                'user': owner,
                'group': group,
            }

            # perform scan
            if self.stopped: break
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
        owner = misc.get_project_name()
        group = misc.get_group_name()
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
            'user': owner,
            'group': group,
        }

        self.beamline.detector.configure(**detector_parameters)
        self.beamline.detector.start()

        logger.debug('Performing raster scan ...')
        self.beamline.goniometer.scan(
            kind='raster',
            time=params['exposure'],  # per frame
            range=params['delta'], # per frame
            angle=params['angle'],
            hsteps=params['hsteps'],
            vsteps=params['vsteps'],
            width=params['width'],
            height=params['height'],
            start_pos=params['grid'][0],
            wait=True,
            timeout=max(60, params['exposure'] * self.total_frames * 10),
        )
        self.beamline.detector.save()
        time.sleep(0)

    def on_raster_update(self, result, info, template):
        score = misc.frame_score(info)
        index = info['frame_number'] - 1
        ij = self.config['properties']['grid_index'][index]

        info['filename'] = template.format(info['frame_number'])
        self.results[info['frame_number']] = info
        self.config['properties']['grid_scores'][ij] = score

        self.emit('result', info['frame_number'], info)
        self.count += 1

        fraction = self.count / self.total_frames
        msg = 'Analysis {}: {} of {} complete'.format(self.config['params']['name'], self.count, self.total_frames)
        self.emit('progress', fraction, msg)

    def on_raster_done(self, result, data):
        self.save_metadata()
        self.complete = True
        self.emit('complete', None)

    def on_raster_failed(self, result, error):
        logger.error(f"Unable to process data: {error}")
        self.save_metadata()
        self.emit('error', error)

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
        metadata = {
            'name': params['name'],
            'frames': params['framesets'],
            'filename': template,
            'group': params['group'],
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
            'grid_origin': params['origin'],
        }
        filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
        misc.save_metadata(metadata, filename)
        self.beamline.lims.upload_data(self.beamline.name, filename)
        return metadata
