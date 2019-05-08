import os
import pwd
import threading
import time

from gi.repository import GObject
from twisted.python.components import globalRegistry
from zope.interface import implementer

from mxdc.beamlines.interfaces import IBeamline
from mxdc.com import ca
from mxdc.engines import snapshot
from mxdc.engines.interfaces import IDataCollector, IAnalyst
from mxdc.utils import json, datatools, misc
from mxdc.utils.converter import energy_to_wavelength, dist_to_resol
from mxdc.utils.datatools import StrategyType
from mxdc.utils.decorators import async_call
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


@implementer(IDataCollector)
class DataCollector(GObject.GObject):

    __gsignals__ = {
        'new-image': (GObject.SIGNAL_RUN_LAST, None, (str,)),
        'progress': (GObject.SIGNAL_RUN_LAST, None, (float,)),
        'done': (GObject.SIGNAL_RUN_LAST, None, []),
        'paused': (GObject.SIGNAL_RUN_LAST, None, (bool, str)),
        'started': (GObject.SIGNAL_RUN_LAST, None, []),
        'stopped': (GObject.SIGNAL_RUN_LAST, None, []),
        'error': (GObject.SIGNAL_RUN_LAST, None, (str,)),
        'message': (GObject.SIGNAL_RUN_LAST, None, (str,))
    }
    complete = GObject.Property(type=bool, default=False)
    name = 'Data Collector'

    def __init__(self):
        super(DataCollector, self).__init__()
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
        self.beamline.synchrotron.connect('ready', self.on_beam_change)
        globalRegistry.register([], IDataCollector, '', self)

    def configure(self, run_data, take_snapshots=True, existing=0, analysis=None, anomalous=False, first=False):
        self.config['analysis'] = analysis
        self.config['first'] = first
        self.config['anomalous'] = anomalous
        self.config['take_snapshots'] = take_snapshots
        self.config['runs'] = run_data[:] if isinstance(run_data, list) else [run_data]
        datasets, wedges = datatools.generate_wedges(self.config['runs'])
        self.config['wedges'] = wedges
        self.config['datasets'] = datasets
        self.config['existing'] = existing


        # delete existing frames
        for wedge in wedges:
            frame_list = [wedge['frame_template'].format(i + wedge['first']) for i in range(wedge['num_frames'])]
            self.beamline.detector.delete(wedge['directory'], *frame_list)

    def start(self):
        worker = threading.Thread(target=self.run)
        worker.setDaemon(True)
        worker.setName('Data Collector')
        worker.start()

    def is_busy(self):
        return self.collecting

    def run(self):
        self.props.complete = False
        self.paused = False
        self.stopped = False
        ca.threads_init()
        self.collecting = True
        self.beamline.detector_cover.open(wait=True)
        self.count = self.config['existing']
        self.total_frames = self.count + sum([wedge['num_frames'] for wedge in self.config['wedges']])
        current_attenuation = self.beamline.attenuator.get()
        self.watch_frames()
        self.results = []

        with self.beamline.lock:
            # Take snapshots and prepare endstation mode
            self.take_snapshots()
            self.beamline.manager.collect(wait=True)
            GObject.idle_add(self.emit, 'started')
            try:
                if self.beamline.detector.shutterless:
                    self.run_shutterless()
                else:
                    self.run_default()
            finally:
                self.beamline.fast_shutter.close()

        # Wait for Last image to be transferred (only if dataset is to be uploaded to MxLIVE)
        time.sleep(2.0)

        for dataset in self.config['datasets']:
            metadata = self.save(dataset)
            self.results.append(metadata)
            if metadata and self.config['analysis']:
                self.analyse(metadata, dataset['sample'], first=self.config.get('first', False))

        if not (self.stopped or self.paused):
            GObject.idle_add(self.emit, 'done')

        if self.stopped or not self.paused:
            self.props.complete = True
            GObject.idle_add(self.emit, 'done')

        self.beamline.attenuator.set(current_attenuation)  # restore attenuation
        self.collecting = False
        self.beamline.detector_cover.close()
        GObject.timeout_add(5000, self.unwatch_frames)
        return self.results

    def run_default(self):
        is_first_frame = True
        for wedge in self.config['wedges']:
            if self.stopped or self.paused: break
            self.prepare_for_wedge(wedge)

            for frame in datatools.generate_frames(wedge):
                if self.stopped or self.paused: break
                # Prepare image header
                energy = self.beamline.energy.get_position()
                detector_parameters = {
                    'file_prefix': frame['dataset'],
                    'start_frame': frame['first'],
                    'directory': frame['directory'],
                    'wavelength': energy_to_wavelength(energy),
                    'energy': energy,
                    'distance': round(self.beamline.distance.get_position(), 1),
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
                self.beamline.goniometer.scan(wait=True, timeout=frame['exposure'] * 20)
                self.beamline.detector.save()

                is_first_frame = False
                time.sleep(0)

    def run_shutterless(self):
        is_first_frame = True
        for wedge in self.config['wedges']:
            if self.stopped or self.paused: break
            self.prepare_for_wedge(wedge)
            energy = self.beamline.energy.get_position()
            detector_parameters = {
                'file_prefix': wedge['dataset'],
                'start_frame': wedge['first'],
                'directory': wedge['directory'],
                'wavelength': energy_to_wavelength(energy),
                'energy': energy,
                'distance': round(self.beamline.distance.get_position(), 1),
                'two_theta': wedge['two_theta'],
                'exposure_time': wedge['exposure'],
                'num_frames': wedge['num_frames'],
                'start_angle': wedge['start'],
                'delta_angle': wedge['delta'],
                'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
            }

            # prepare goniometer for scan
            logger.info("Collecting {} images starting at: {}".format(
                wedge['num_frames'], wedge['frame_template'].format(wedge['first']))
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
        if self.config['take_snapshots'] and self.config['wedges']:
            wedges = self.config['wedges']
            prefix = os.path.commonprefix([wedge['dataset'] for wedge in wedges]) or 'SNAPSHOT'
            wedge = wedges[0]

            # setup folder for wedge
            self.beamline.dss.setup_folder(wedge['directory'], misc.get_project_name())
            if not os.path.exists(os.path.join(wedge['directory'], '{}_{:0.0f}.png'.format(prefix, wedge['start']))):
                logger.info('Taking snapshots of sample at {:0.0f}'.format(wedge['start']))

                snapshot.take_sample_snapshots(
                    prefix, os.path.join(wedge['directory']), [wedge['start']], decorate=True
                )

    def prepare_for_wedge(self, wedge):
        # setup folder for wedge
        self.beamline.dss.setup_folder(wedge['directory'], misc.get_project_name())

        # make sure shutter is closed before starting
        self.beamline.fast_shutter.close()

        # setup devices
        if abs(self.beamline.energy.get_position() - wedge['energy']) >= 0.0005:
            self.beamline.energy.move_to(wedge['energy'], wait=True)

        if abs(self.beamline.distance.get_position() - wedge['distance']) >= 0.1:
            self.beamline.distance.move_to(wedge['distance'], wait=True)

        if abs(self.beamline.attenuator.get() - wedge['attenuation']) >= 25:
            self.beamline.attenuator.set(wedge['attenuation'], wait=True)

        if wedge.get('point') is not None:
            x, y, z  = wedge['point']
            self.beamline.sample_stage.move_xyz(x, y, z, wait=True)

    def save(self, params):
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
            'beam_size': self.beamline.aperture.get_position(),
            'resolution': dist_to_resol(params['distance'], self.beamline.detector.mm_size, params['energy']),
            'detector_size': min(self.beamline.detector.size),
            'start_angle': params['start'],
            'delta_angle': params['delta'],
        }
        filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
        misc.save_metadata(metadata, filename)
        reply = self.beamline.lims.upload_data(self.beamline.name, filename)
        return reply

    def analyse(self, metadata, sample, first=False):

        if self.config['analysis'] is None:
            return

        flags = () if not self.config.get('anomalous') else ('anomalous',)
        if (self.config['analysis'] == 'screen') or (self.config['analysis'] == 'default' and metadata['type'] == 'MX_SCREEN'):
            self.analyst.screen_dataset(metadata, flags=flags, sample=sample)
        elif (self.config['analysis'] == 'process') or (self.config['analysis'] == 'default' and metadata['type'] == 'MX_DATA'):
            self.analyst.process_dataset(metadata, flags=flags, sample=sample)
        elif (self.config['analysis'] == 'powder') or (self.config['analysis'] == 'default' and metadata['type'] == 'XRD_DATA'):
            flags = ('calibrate',) if first else ()
            self.analyst.process_powder(metadata, flags=flags, sample=sample)

    def on_new_image(self, obj, file_path):
        self.count += 1
        fraction = float(self.count) / max(1, self.total_frames)
        GObject.idle_add(self.emit, 'new-image', file_path)
        if not (self.paused or self.stopped):
            GObject.idle_add(self.emit, 'progress', fraction)

        GObject.idle_add(self.emit, "message", "Acquired frame {}/{}".format(self.count, self.total_frames))

    def on_beam_change(self, obj, available):
        if not (self.stopped or self.paused) and self.collecting and not available:
            message = (
                "Data acquisition has paused due to beam loss!\n"
                "It will resume automatically once the beam becomes available."
            )
            self.pause(message)
        elif self.paused and available:
            self.resume()

    def resume_sequence(self):
        self.paused = False
        collected = 0

        # reset 'existing' field
        for run in self.config['runs']:
            run['existing'] = ''
        frame_list = datatools.generate_run_list(self.config['runs'])
        existing, bad = datatools.check_frame_list(
            frame_list, self.beamline.detector.file_extension, detect_bad=False
        )

        for run in self.config['runs']:
            run['existing'] = existing.get(run['name'], '')
            collected += len(datatools.frameset_to_list(run['existing']))
        self.configure(self.config['runs'], existing=collected, take_snapshots=False)
        self.beamline.all_shutters.open()
        self.start()

    def resume(self):
        logger.info("Resuming Collection ...")
        if self.paused:
            # wait for 1 minute then open all shutters before resuming
            message = "Beam available! Resuming data acquisition in 30 seconds!"
            GObject.idle_add(self.emit, 'paused', False, message)
            GObject.timeout_add(30000, self.resume_sequence)

    def pause(self, message):
        logger.info("Pausing Collection ...")
        self.paused = True
        self.beamline.detector.stop()
        self.beamline.goniometer.stop()
        GObject.idle_add(self.emit, 'paused', True, message)

    def stop(self):
        logger.info("Stopping Collection ...")
        self.stopped = True
        self.paused = False
        self.beamline.detector.stop()
        self.beamline.goniometer.stop()
        while self.collecting:
            time.sleep(0.1)
        GObject.idle_add(self.emit, 'stopped')

    def message(self, text):
        GObject.idle_add(self.emit, 'message', text)

    def watch_frames(self):
        self.beamline.detector.handler_unblock(self.frame_link)

    def unwatch_frames(self):
        self.beamline.detector.handler_block(self.frame_link)
