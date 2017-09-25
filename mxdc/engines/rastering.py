import json
import os
import pwd
import re
import threading
import time

from gi.repository import GObject
from twisted.python.components import globalRegistry

from mxdc.beamline.interfaces import IBeamline
from mxdc.com import ca
from mxdc.engines.interfaces import IAnalyst
from mxdc.utils import datatools
from mxdc.utils.converter import energy_to_wavelength
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


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

    def configure(self, grid, parameters):
        self.config['grid'] = grid
        self.config['params'] = parameters
        self.config['frames'] = datatools.generate_grid_frames(grid, parameters)
        self.beamline.image_server.set_user(pwd.getpwuid(os.geteuid())[0], os.geteuid(), os.getegid())

    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Raster Collector')
        worker_thread.start()

    def prepare(self, params):
        # setup folder for wedge
        self.beamline.image_server.setup_folder(params['directory'])

        # make sure shutter is closed before starting
        self.beamline.exposure_shutter.close()

        if abs(self.beamline.distance.get_position() - params['distance']) >= 0.1:
            self.beamline.distance.move_to(params['distance'], wait=True)
        self.beamline.omega.move_to(params['angle'], wait=True)

    def run(self):
        self.paused = False
        self.stopped = False
        ca.threads_init()
        self.collecting = True
        self.beamline.detector_cover.open(wait=True)
        self.total_frames = len(self.config['frames'])
        self.pending_results = set()
        self.results = {}
        current_attenuation = self.beamline.attenuator.get()

        with self.beamline.lock:
            # Prepare endstation mode
            self.beamline.goniometer.set_mode('COLLECT', wait=True)
            GObject.idle_add(self.emit, 'started')
            try:
                self.acquire()
            finally:
                self.beamline.exposure_shutter.close()

        # Wait for Last image to be transferred (only if dataset is to be uploaded to MxLIVE)
        time.sleep(2.0)

        # self.results = self.save(self.config['datasets'])
        # self.beamline.lims.upload_datasets(self.beamline, self.results)
        if not self.stopped:
            GObject.idle_add(self.emit, 'done')
        else:
            GObject.idle_add(self.emit, 'stopped')
        self.beamline.attenuator.set(current_attenuation)  # restore attenuation
        self.collecting = False
        self.beamline.detector_cover.close()

    def acquire(self):
        is_first_frame = True
        self.count = 0
        self.prepare(self.config['params'])
        self.watch_frames()
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
            self.beamline.goniometer.scan(wait=True, timeout=frame['exposure'] * 4)
            self.beamline.detector.save()

            self.count += 1
            self.notify_progress(self.count)

            is_first_frame = False
            time.sleep(0)

        self.beamline.sample_stage.move_xyz(*self.config['params']['origin'])
        self.beamline.omega.move_to(self.config['params']['angle'], wait=True)
        GObject.timeout_add(5000, self.unwatch_frames)

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
        self.analyse_image(file_path)

    def analyse_image(self, file_path):
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
                'activity': 'proc-raster',
                'filename': file_path
            }
            info = datatools.update_for_sample(info, params['sample'])
            d = self.analyst.process_raster(info)
            d.addCallbacks(
                self.result_ready, callbackArgs=[index, file_path],
                errback=self.result_fail, errbackArgs=[index, file_path]
            )


    def result_ready(self, result, cell, file_path):
        self.pending_results.remove(file_path)
        GObject.idle_add(self.emit, 'result', cell, result)
        self.results[cell] = result
        if not self.pending_results:
            self.save_metadata()

    def result_fail(self, error, cell, file_path):
        self.pending_results.remove(file_path)
        self.results[cell] = error
        logger.error("Unable to process data for cell {}".format(cell))
        if not self.pending_results:
            self.save_metadata()

    def save_metadata(self):
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
                'beam_x': self.beamline.detector.get_origin()[0],
                'beam_y': self.beamline.detector.get_origin()[1],
                'pixel_size': self.beamline.detector.resolution,
                'resolution': params['resolution'],
                'detector_size': min(self.beamline.detector.size),
                'start_angle': params['angle'],
                'delta_angle': params['delta'],
                'inverse_beam': params.get('inverse', False),
                'grid_origin': params['origin'],
                'grid_points': self.config['grid'].tolist()
            }
            filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
            if os.path.exists(filename):
                with open(filename, 'r') as handle:
                    old_meta = json.load(handle)
                    metadata['id'] = old_meta.get('id')

            with open(filename, 'w') as handle:
                json.dump(metadata, handle, indent=2, separators=(',',':'), sort_keys=True)
                logger.info("Meta-Data Saved: {}".format(filename))

            return metadata