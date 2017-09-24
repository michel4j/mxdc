import os
import pwd
import threading
import time

from gi.repository import GObject
from twisted.python.components import globalRegistry
from zope.interface import implements

from mxdc.beamline.interfaces import IBeamline
from mxdc.com import ca
from mxdc.engines import snapshot
from mxdc.engines.interfaces import IDataCollector, IAnalyst
from mxdc.utils import json, datatools
from mxdc.utils.converter import energy_to_wavelength, dist_to_resol
from mxdc.utils.datatools import StrategyType
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class DataCollector(GObject.GObject):
    implements(IDataCollector)
    __gsignals__ = {
        'new-image': (GObject.SIGNAL_RUN_LAST, None, (str,)),
        'progress': (GObject.SIGNAL_RUN_LAST, None, (float,)),
        'done': (GObject.SIGNAL_RUN_LAST, None, []),
        'paused': (GObject.SIGNAL_RUN_LAST, None, (bool, object)),
        'started': (GObject.SIGNAL_RUN_LAST, None, []),
        'stopped': (GObject.SIGNAL_RUN_LAST, None, []),
        'error': (GObject.SIGNAL_RUN_LAST, None, (str,))
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.collecting = False
        self.run_list = []
        self.runs = []
        self.results = []
        self.config = {}
        self.total_frames = 0
        self.count = 0
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.analyst = globalRegistry.lookup([], IAnalyst)
        self.frame_link = self.beamline.detector.connect('new-image', self.on_new_image)
        self.unwatch_frames()
        self.beamline.storage_ring.connect('beam', self.on_beam_change)
        globalRegistry.register([], IDataCollector, '', self)

    def configure(self, run_data, take_snapshots=True):
        self.config['take_snapshots'] = take_snapshots
        self.config['runs'] = run_data[:] if isinstance(run_data, list) else [run_data]
        datasets, wedges = datatools.generate_wedges(self.config['runs'])
        self.config['wedges'] = wedges
        self.config['datasets'] = datasets
        self.beamline.image_server.set_user(pwd.getpwuid(os.geteuid())[0], os.geteuid(), os.getegid())

        # delete existing frames
        for wedge in wedges:
            frame_list = [wedge['frame_template'].format(i + wedge['first']) for i in range(wedge['num_frames'])]
            self.beamline.detector.delete(wedge['directory'], *frame_list)

    def start(self):
        worker = threading.Thread(target=self.run)
        worker.setDaemon(True)
        worker.setName('Data Collector')
        worker.start()

    def run(self):
        self.paused = False
        self.stopped = False
        ca.threads_init()
        self.collecting = True
        self.beamline.detector_cover.open(wait=True)
        self.total_frames = sum([wedge['num_frames'] for wedge in self.config['wedges']])
        current_attenuation = self.beamline.attenuator.get()
        self.watch_frames()
        self.results = []

        with self.beamline.lock:
            # Take snapshots and prepare endstation mode
            self.take_snapshots()
            self.beamline.goniometer.set_mode('COLLECT', wait=True)
            GObject.idle_add(self.emit, 'started')
            try:
                if self.beamline.detector.shutterless:
                    self.run_shutterless()
                else:
                    self.run_default()
            finally:
                self.beamline.exposure_shutter.close()

        # Wait for Last image to be transferred (only if dataset is to be uploaded to MxLIVE)
        time.sleep(2.0)

        for dataset in self.config['datasets']:
            metadata = self.save_metadata(dataset)
            self.results.append(metadata)
            if metadata:
                self.analyse(metadata, dataset['strategy'], dataset['sample'])

        self.beamline.lims.upload_datasets(self.beamline.name, self.results)
        if not (self.stopped or self.paused):
            GObject.idle_add(self.emit, 'done')

        self.beamline.attenuator.set(current_attenuation)  # restore attenuation
        self.collecting = False
        self.beamline.detector_cover.close()
        GObject.timeout_add(5000, self.unwatch_frames)
        return self.results

    def run_default(self):
        is_first_frame = True
        self.count = 0
        for wedge in self.config['wedges']:
            if self.stopped or self.paused: break
            self.prepare_for_wedge(wedge)

            for frame in datatools.generate_frames(wedge):
                if self.stopped or self.paused: break
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

                # prepare goniometer for scan
                self.beamline.goniometer.configure(
                    time=frame['exposure'], delta=frame['delta'], angle=frame['start']
                )

                if self.stopped or self.paused: break
                self.beamline.detector.set_parameters(detector_parameters)
                self.beamline.detector.start(first=is_first_frame)
                self.beamline.goniometer.scan(wait=True, timeout=frame['exposure'] * 4)
                self.beamline.detector.save()

                is_first_frame = False
                time.sleep(0)

    def run_shutterless(self):
        is_first_frame = True
        self.count = 0
        for wedge in self.config['wedges']:
            if self.stopped or self.paused: break
            self.prepare_for_wedge(wedge)
            detector_parameters = {
                'file_prefix': wedge['dataset'],
                'start_frame': wedge['first'],
                'directory': wedge['directory'],
                'wavelength': energy_to_wavelength(wedge['energy']),
                'energy': wedge['energy'],
                'distance': wedge['distance'],
                'two_theta': wedge['two_theta'],
                'exposure_time': wedge['exposure'],
                'num_frames': wedge['num_frames'],
                'start_angle': wedge['start'],
                'delta_angle': wedge['delta'],
                'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
            }

            # prepare goniometer for scan
            logger.info("Collecting {} images starting at: {}".format(
                wedge['num_frames'], wedge['frame_template'].format(wedge['start_frame']))
            )
            self.beamline.goniometer.configure(
                time=wedge['exposure'] * wedge['num_frames'],
                delta=wedge['delta'] * wedge['num_frames'],
                angle=wedge['start']
            )

            if self.stopped or self.paused: break
            # Perform scan
            self.beamline.detector.set_parameters(detector_parameters)
            self.beamline.detector.start(first=is_first_frame)
            self.beamline.goniometer.scan(wait=True, timeout=wedge['exposure'] * wedge['num_frames'] * 2)

            is_first_frame = False
            time.sleep(0)

    def take_snapshots(self):
        if self.config['take_snapshots']:
            wedges = self.config['wedges']
            name = os.path.commonprefix([wedge['dataset'] for wedge in wedges])
            wedge = wedges[0]
            prefix = '{}-pic'.format(name)
            a1 = wedge['start']
            a2 = (a1 + 90.0) % 360.0

            # setup folder for wedge
            self.beamline.image_server.setup_folder(wedge['directory'])
            if not os.path.exists(os.path.join(wedge['directory'], '{}_{:0.0f}.png'.format(prefix, a1))):
                logger.info('Taking snapshots of crystal at {:0.0f} and {:0.0f}'.format(a1, a2))
                snapshot.take_sample_snapshots(
                    prefix, os.path.join(wedge['directory']), [a2, a1], decorate=True
                )

    def prepare_for_wedge(self, wedge):
        # setup folder for wedge
        self.beamline.image_server.setup_folder(wedge['directory'])

        # make sure shutter is closed before starting
        self.beamline.exposure_shutter.close()

        # setup devices
        if abs(self.beamline.energy.get_position() - wedge['energy']) >= 0.0005:
            self.beamline.energy.move_to(wedge['energy'], wait=True)

        if abs(self.beamline.distance.get_position() - wedge['distance']) >= 0.1:
            self.beamline.distance.move_to(wedge['distance'], wait=True)

        if abs(self.beamline.attenuator.get() - wedge['attenuation']) >= 25:
            self.beamline.attenuator.set(wedge['attenuation'], wait=True)

        if wedge.get('point'):
            x, y, z  = wedge['point']
            self.beamline.sample_stage.move_xyz(x, y, z)

    def save_metadata(self, params):
        frames, count = datatools.get_disk_frameset(
            params['directory'], '{}_*.{}'.format(params['name'], self.beamline.detector.file_extension)
        )
        if count < 2 or params['strategy'] == datatools.StrategyType.SINGLE:
            return

        metadata = {
            'name': params['name'],
            'frames':  frames,
            'filename': '{}.{}'.format(
                datatools.make_file_template(params['name']), self.beamline.detector.file_extension
            ),
            'group': params['group'],
            'container': params['container'],
            'port': params['port'],
            'type': datatools.StrategyDataType.get(params['strategy']),
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
            'resolution': dist_to_resol(params['distance'], self.beamline.detector.mm_size, params['energy']),
            'detector_size': min(self.beamline.detector.size),
            'start_angle': params['start'],
            'delta_angle': params['delta'],
            'inverse_beam': params.get('inverse', False),
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

    def analyse(self, metadata, strategy, sample):
        numbers = datatools.frameset_to_list(metadata['frames'])
        filename = os.path.join(metadata['directory'], metadata['filename'].format(numbers[0]))

        params = {
            'sample_id': metadata['sample_id'],
            'name': metadata['name'],
            'activity': datatools.StrategyProcType.get(strategy, 'proc-noname'),
            'file_names': [filename]
        }

        params = datatools.update_for_sample(params, sample)

        if strategy in [StrategyType.SCREEN_2, StrategyType.SCREEN_3, StrategyType.SCREEN_4]:
            self.analyst.process_dataset(params, screen=True).addCallbacks(self.result_ready, errback=self.result_fail)
        elif strategy == StrategyType.FULL:
            self.analyst.process_dataset(params).addCallbacks(self.result_ready, errback=self.result_fail)
        elif strategy == StrategyType.POWDER:
            self.analyst.process_powder(params).addCallbacks(self.result_ready, errback=self.result_fail)

    def result_ready(self, result):
        pass

    def result_fail(self, result):
        pass

    def on_new_image(self, obj, file_path):
        self.count += 1
        fraction = float(self.count) / max(1, self.total_frames)
        GObject.idle_add(self.emit, 'new-image', file_path)
        if not (self.paused or self.stopped):
            GObject.idle_add(self.emit, 'progress', fraction)

    def on_beam_change(self, obj, available):
        if not (self.stopped or self.paused) and self.collecting and not available:
            info = {
                'reason': 'No Beam! Data Collection Paused.',
                'details': (
                    "Data collection has been paused because there is no beam. It will "
                    "resume automatically once the beam becomes available."
                )
            }
            self.pause(info)
        elif self.paused and available:
            # FIXME: restore beam fully before resuming
            self.resume()

    def resume(self):
        logger.info("Resuming Collection ...")
        if self.paused:
            GObject.idle_add(self.emit, 'paused', False, {})
            self.paused = False
            frame_list = datatools.generate_run_list(self.config['runs'])
            existing, bad = datatools.check_frame_list(
                frame_list, self.beamline.detector.file_extension, detect_bad=False
            )
            for run in self.config['runs']:
                run['skip'] = datatools.merge_framesets(existing.get(run['name'], ''), run.get('skip', ''),
                                                        bad.get(run['name'], ''))
            self.configure(self.config['runs'], take_snapshots=False)
            self.start()

    def pause(self, info={}):
        logger.info("Pausing Collection ...")
        self.paused = True
        self.beamline.detector.stop()
        self.beamline.goniometer.stop()
        GObject.idle_add(self.emit, 'paused', True, info)

    def stop(self):
        logger.info("Stopping Collection ...")
        self.stopped = True
        self.paused = False
        self.beamline.detector.stop()
        self.beamline.goniometer.stop()
        while self.collecting:
            time.sleep(0.1)
        GObject.idle_add(self.emit, 'stopped')

    def watch_frames(self):
        self.beamline.detector.handler_unblock(self.frame_link)

    def unwatch_frames(self):
        self.beamline.detector.handler_block(self.frame_link)
