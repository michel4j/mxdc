import os
import time
from datetime import datetime
import numpy
import pytz
from twisted.internet.defer import returnValue, inlineCallbacks
from zope.interface import Interface, implementer

from mxdc import Registry, Signal, Engine
from mxdc.engines.interfaces import IAnalyst
from mxdc.utils import datatools, misc
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

    def __init__(self):
        super().__init__()
        self.collecting = False
        self.pending_results = set()
        self.runs = []
        self.results = {}
        self.config = {}
        self.total_frames = 0
        self.count = 0

        self.analyst = Registry.get_utility(IAnalyst)
        Registry.add_utility(IRasterCollector, self)

    def configure(self, grid, parameters):
        self.config['params'] = parameters
        self.config['grid'] = grid
        self.config['frames'] = datatools.generate_grid_frames(grid, parameters)

    def prepare(self, params):
        self.beamline.detector_cover.open(wait=True)
        self.total_frames = len(self.config['frames'])
        self.pending_results = set()
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
        current_attenuation = self.beamline.attenuator.get()
        with self.beamline.lock:
            self.emit('started', None)
            try:
                self.config['start_time'] = datetime.now(tz=pytz.utc)
                self.acquire()
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

        self.config['end_time'] = datetime.now(tz=pytz.utc)
        if self.stopped:
            self.emit('stopped', None)
        else:
            self.emit('done', None)
            self.save_metadata()
        self.beamline.attenuator.set(current_attenuation)  # restore attenuation
        self.beamline.detector_cover.close()

    def acquire(self):
        self.paused = False
        self.stopped = False

        self.collecting = True
        is_first_frame = True
        self.count = 0
        self.prepare(self.config['params'])

        logger.debug('Acquiring {} rastering frames ... '.format(len(self.config['frames'])))
        template = self.beamline.detector.get_template(self.config['params']['name'])
        for frame in self.config['frames']:
            if self.paused:
                self.emit('paused', True, '')
                while self.paused and not self.stopped:
                    time.sleep(0.1)
                self.emit('paused', False, '')

            if self.stopped: break

            # Prepare image header
            detector_parameters = {
                'file_prefix': frame['dataset'],
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
            self.beamline.detector.start(first=is_first_frame)
            self.beamline.goniometer.scan(
                time=frame['exposure'],
                delta=frame['delta'],
                angle=frame['start'],
                start_pos=frame['point'],
                wait=True,
                timeout=frame['exposure'] * 20
            )
            self.beamline.detector.save()

            self.count += 1
            msg = '{}: {} of {}'.format(self.config['params']['name'], self.count, self.total_frames)
            self.emit('progress', self.count / self.total_frames, msg)
            is_first_frame = False
            time.sleep(0)
            file_path = os.path.join(frame['directory'], template.format(frame['first']))
            self.analyse_frame(file_path, frame['first'])

        while self.pending_results:
            time.sleep(0.5)

        self.collecting = False

    @inlineCallbacks
    def analyse_frame(self, file_path, index):
        frame = os.path.splitext(os.path.basename(file_path))[0]
        self.pending_results.add(file_path)
        logger.info("Analyzing frame: {}".format(frame))
        try:
            report = yield self.beamline.dps.analyse_frame(file_path, misc.get_project_name())
        except Exception as e:
            self.result_fail(e, index, file_path)
            returnValue({})
        else:
            self.result_ready(report, index, file_path)
            returnValue(report)

    def result_ready(self, result, index=None, path=None):
        info = result
        info['filename'] = path
        self.results[index] = info
        self.emit('result', index, info)
        self.pending_results.remove(path)

    def result_fail(self, error, cell, file_path):
        self.results[cell] = error
        logger.error("Unable to process data for cell {}".format(cell))
        self.pending_results.remove(file_path)

    def save_metadata(self, upload=True):
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
                'grid_points': self.config['grid'].tolist(),
            }
            filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
            misc.save_metadata(metadata, filename)
            if upload:
                self.beamline.lims.upload_data(self.beamline.name, filename)
            return metadata
