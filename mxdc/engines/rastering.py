import json
import os
import pwd
import re
import threading
import time
import functools

from gi.repository import GObject
from twisted.python.components import globalRegistry
from twisted.internet.defer import returnValue, inlineCallbacks
from mxdc.beamlines.interfaces import IBeamline
from mxdc.com import ca
from mxdc.engines.interfaces import IAnalyst
from mxdc.utils import datatools,  misc
from mxdc.utils.converter import energy_to_wavelength
from mxdc.utils.log import get_module_logger

from zope.interface import Interface, implementer, Attribute

logger = get_module_logger(__name__)


class IRasterCollector(Interface):
    """Raster Collector."""

    def configure(grid, parameters):
        """Configure the collector"""

    def start():
        """Run the acquisition asynchronously"""


@implementer(IRasterCollector)
class RasterCollector(GObject.GObject):
    __gsignals__ = {
        'new-image': (GObject.SIGNAL_RUN_LAST, None, (str,)),
        'result': (GObject.SIGNAL_RUN_LAST, None, (int, object)),
        'progress': (GObject.SIGNAL_RUN_LAST, None, (float, str)),
        'done': (GObject.SIGNAL_RUN_LAST, None, []),
        'paused': (GObject.SIGNAL_RUN_LAST, None, (bool, str)),
        'started': (GObject.SIGNAL_RUN_LAST, None, []),
        'stopped': (GObject.SIGNAL_RUN_LAST, None, []),
        'error': (GObject.SIGNAL_RUN_LAST, None, (str,))
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.collecting = False
        self.pending_results = set()
        self.runs = []
        self.results = {}
        self.config = {}
        self.total_frames = 0
        self.count = 0

        self.beamline = globalRegistry.lookup([], IBeamline)
        self.analyst = globalRegistry.lookup([], IAnalyst)
        self.frame_link = self.beamline.detector.connect('new-image', self.on_new_image)
        self.unwatch_frames()
        globalRegistry.register([], IRasterCollector, '', self)

    def configure(self, grid, parameters):
        self.config['grid'] = grid
        self.config['params'] = parameters
        self.config['frames'] = datatools.generate_grid_frames(grid, parameters)

    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Raster Collector')
        worker_thread.start()

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

        #switch to collect mode
        self.beamline.manager.collect(wait=True)

    def run(self):
        ca.threads_init()
        current_attenuation = self.beamline.attenuator.get()

        with self.beamline.lock:
            GObject.idle_add(self.emit, 'started')
            try:
                self.acquire()
                self.beamline.sample_stage.move_xyz(*self.config['params']['origin'], wait=True)
                self.beamline.omega.move_to(self.config['params']['angle'], wait=True)

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
            GObject.idle_add(self.emit, 'stopped')
        else:
            GObject.idle_add(self.emit, 'done')
        self.beamline.attenuator.set(current_attenuation)  # restore attenuation

        self.beamline.detector_cover.close()

    def acquire(self):
        self.paused = False
        self.stopped = False

        self.collecting = True
        is_first_frame = True
        self.count = 0
        self.prepare(self.config['params'])

        self.watch_frames()
        logger.debug('Acquiring {} rastering frames ... '.format(len(self.config['frames'])))
        for frame in self.config['frames']:
            if self.paused:
                GObject.idle_add(self.emit, 'paused', True, '')
                while self.paused and not self.stopped:
                    time.sleep(0.1)
                GObject.idle_add(self.emit, 'paused', False, '')

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

            # move to grid point
            self.beamline.sample_stage.move_xyz(*frame['point'])

            # prepare goniometer for scan
            self.beamline.goniometer.configure(
                time=frame['exposure'], delta=frame['delta'], angle=frame['start']
            )

            if self.stopped or self.paused: break
            self.beamline.detector.set_parameters(detector_parameters)
            self.beamline.detector.start(first=is_first_frame)
            self.beamline.goniometer.scan(wait=True, timeout=frame['exposure'] * 20)
            self.beamline.detector.save()

            self.count += 1
            self.notify_progress(self.count)

            is_first_frame = False
            time.sleep(0)

        GObject.timeout_add(5000, self.unwatch_frames)

        while self.pending_results:
            time.sleep(0.5)
        self.save_metadata()
        self.collecting = False

    def watch_frames(self):
        self.beamline.detector.handler_unblock(self.frame_link)

    def unwatch_frames(self):
        self.beamline.detector.handler_block(self.frame_link)

    def pause(self, message=''):
        if message:
            logger.warn(message)
        self.pause_message = message
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self, error=''):
        self.stopped = True
        self.paused = False
        if error:
            logger.error(error)
            GObject.idle_add(self.emit, 'error', error)

    def notify_progress(self, pos):
        fraction = float(pos) / self.total_frames
        msg = '{}: {} of {}'.format(self.config['params']['name'], pos, self.total_frames)
        GObject.idle_add(self.emit, 'progress', fraction, msg)

    def on_new_image(self, obj, file_path):
        GObject.idle_add(self.emit, 'new-image', file_path)
        self.analyse_frame(file_path)

    @inlineCallbacks
    def analyse_frame(self, file_path):
        frame = os.path.splitext(os.path.basename(file_path))[0]
        file_pattern = re.compile(r'^{}_(\d{{3,}})$'.format(self.config['params']['name']))
        m = file_pattern.match(frame)
        if m:
            params = self.config['params']
            self.pending_results.add(file_path)
            index = int(m.groups()[0])
            logger.info("Analyzing frame: {}:{}".format(index, frame))
            info = {
                'name': params['name'],
                'filename': file_path,
                'type': 'RASTER',
            }
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
        GObject.idle_add(self.emit, 'result', index, info)
        self.pending_results.remove(path)

    def result_fail(self, error, cell, file_path):
        self.results[cell] = error
        logger.error("Unable to process data for cell {}".format(cell))
        self.pending_results.remove(file_path)

    def save_metadata(self, upload=True):
        params = self.config['params']
        frames, count = datatools.get_disk_frameset(
            params['directory'], '{}_*.{}'.format(params['name'], self.beamline.detector.file_extension)
        )
        if count > 1:
            metadata = {
                'name': params['name'],
                'frames':  frames,
                'filename': '{}.{}'.format(
                    datatools.make_file_template(params['name']), self.beamline.detector.file_extension
                ),
                'container': params['container'],
                'port': params['port'],
                'type': 'RASTER',
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