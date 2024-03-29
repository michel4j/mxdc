import os
import time
from datetime import datetime

import numpy
import pytz
from scipy.stats import gmean
from queue import Queue
from collections import defaultdict
from threading import Thread
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


def logistic(x, x0=0.0, weight=1.0, scale=1.0):
    return weight / (1 + numpy.exp(-scale * (x - x0)))

def score_signal(results):
    return results['bragg_spots']
    # return gmean([
    #     results['bragg_spots'],
    #     results['signal_avg'],
    # ])


@implementer(IRasterCollector)
class RasterCollector(Engine):
    class Signals:
        result = Signal('result', arg_types=(int, object))
        complete = Signal('complete', arg_types=(object,))

    def __init__(self):
        super().__init__()
        self.runs = []
        self.results = {}
        self.config = {}
        self.total_frames = 0
        self.count = 0
        self.complete = False
        self.series = defaultdict(int)
        self.result_queue = Queue()
        self.results_active = False

        Registry.add_utility(IRasterCollector, self)

    def is_complete(self):
        return self.complete

    def configure(self, params):
        name_tag = datetime.now().strftime('%j%H%M')
        self.series[name_tag] += 1

        det_exp_limit = 1 / self.beamline.config.raster.max_freq
        mtr_exp_limit = params['aperture'] * 1e-3 / self.beamline.config.raster.max_speed
        params['exposure'] = max(params['exposure'], det_exp_limit, mtr_exp_limit)

        params['name'] = f'R{name_tag}{self.series[name_tag]:02d}'
        self.config['params'] = params

        # calculate grid from dimensions
        grid, index, frames = misc.grid_from_size(
            (params['hsteps'], params['vsteps']), params['aperture'] * 1e-3, (0, 0),
            **self.beamline.goniometer.grid_settings()
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
            'grid_frames': frames,
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
        self.config['params'].update(self.config['properties']['grid_params'])

    def result_processor(self):
        self.results_active = True
        try:
            while True:
                if not self.result_queue.empty():
                    score, info = self.result_queue.get()
                    # on buggy gonios multiple cells may represent the same frame
                    for index in numpy.where(self.config['properties']['grid_frames'] == info['frame_number'])[0]:
                        ij = self.config['properties']['grid_index'][index]
                        self.config['properties']['grid_scores'][ij] = score
                        self.emit('result', index, info)

                time.sleep(0.01)
        finally:
            self.results_active = False

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

        if params.get('low_dose'):
            self.beamline.low_dose.on()

    def start_signal_strength(self):
        # prepare for analysis
        template = self.beamline.detector.get_template(self.config['params']['name'])
        params = {
            'name': self.config['params']['name'],
            'template': template,
            'type': 'file',
            'directory': self.config['params']['directory'],
            'first': 1,
            'num_frames': self.total_frames,
            'timeout': max(20, min(self.config['params']['exposure'] * 5, 120))
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

    def run(self, switch_to_center=True):
        """
        Run the rastering engine
        :param switch_to_center: if True, return to centering mode after the scan is complete
        """
        self.complete = False
        if not self.results_active:
            Thread(target=self.result_processor, daemon=True).start()  # Start result thread

        with self.beamline.lock:
            self.config['start_time'] = datetime.now(tz=pytz.utc)
            self.emit('started', self.config['params'])
            self.prepare(self.config['params'])

            try:
                # raster scan proper
                if self.beamline.goniometer.supports(GonioFeatures.RASTER4D, GonioFeatures.TRIGGERING):
                    self.acquire_slew()
                else:
                    self.acquire_step()

                time.sleep(1)

            finally:
                self.beamline.fast_shutter.close()
                self.beamline.detector.stop()
                self.beamline.low_dose.off()
                if switch_to_center:
                    self.beamline.manager.center(wait=True)

        if self.stopped:
            self.emit('stopped', None)
        else:
            self.emit('done', None)

    def acquire_step(self):
        logger.debug('Rastering ... ')
        self.start_signal_strength()
        for i, frame in enumerate(datatools.grid_frames(self.config['params'])):
            if self.stopped: break

            # Prepare image header
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
                'num_images': 1,
                'num_triggers': 1,
                'start_angle': frame['start'],
                'delta_angle': frame['delta'],
                'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
                'user': owner,
                'group': group,
            }

            # perform scan
            if self.stopped: break
            self.beamline.detector.configure(**detector_parameters)
            if self.beamline.detector.start():
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
            else:
                logger.error('Detector did not start ...')
            time.sleep(0)

    def acquire_slew(self):
        logger.debug('Setting up detector for rastering ... ')

        # Prepare detector
        owner = misc.get_project_name()
        group = misc.get_group_name()
        params = self.config['params']
        gonio_gating = self.beamline.goniometer.supports(GonioFeatures.GATING)
        if gonio_gating:
            extras = {'num_images': 1, 'num_triggers': params['hsteps']*params['vsteps']}
        else:
            if params['hsteps'] == 1 and params['vsteps'] > 1:
                extras = {'num_images': params['vsteps'],'num_triggers': params['hsteps']}
            else:
                extras = {'num_images': params['hsteps'],'num_triggers': params['vsteps']}

        detector_parameters = {
            'file_prefix': params['name'],
            'start_frame': 1,
            'directory': params['directory'],
            'wavelength': energy_to_wavelength(params['energy']),
            'energy': params['energy'],
            'distance': params['distance'],
            'exposure_time': params['exposure'],
            'start_angle': params['angle'],
            'delta_angle': params['delta'],
            'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
            'user': owner,
            'group': group,
            **extras
        }

        self.beamline.detector.configure(**detector_parameters)
        self.start_signal_strength()
        if self.beamline.detector.start():
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
                timeout=max(60, params['exposure'] * self.total_frames * 3),
                gating=gonio_gating
            )
            self.beamline.detector.save()
        else:
            logger.error('Detector did not start ...')
        time.sleep(0)

    def on_raster_update(self, result, info, template):

        info['filename'] = template.format(info['frame_number'])
        self.results[info['frame_number']] = info
        score = info['score']
        self.result_queue.put((score, info))

        self.count += 1
        fraction = self.count / self.total_frames
        msg = 'Analysis {}: {} of {} complete'.format(self.config['params']['name'], self.count, self.total_frames)
        self.emit('progress', fraction, msg)

    def on_raster_done(self, result, data):
        self.config['properties']['grid_scores'][self.config['properties']['grid_scores'] < 0] = 0.0
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
            'resolution': round(params['resolution'], 3),
            'detector_size': min(self.beamline.detector.size),
            'start_angle': round(params['angle'], 3),
            'delta_angle': round(params['delta'], 3),
            'grid_origin': params['origin'],
            'grid_size': (params['hsteps'], params['vsteps'])
        }
        filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
        misc.save_metadata(metadata, filename)
        self.beamline.lims.upload_data(self.beamline.name, filename)
        grid_file = os.path.join(metadata['directory'], '{}.grid'.format(metadata['name']))
        self.config['params']['template'] = template
        misc.save_pickle((self.config['params'], self.config['properties']), grid_file)
        return metadata
