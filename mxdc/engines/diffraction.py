import os
import time
from datetime import datetime

import pytz
from gi.repository import GLib
from zope.interface import implementer

from mxdc import Registry, Signal, Engine
from mxdc.devices.detector import DetectorFeatures
from mxdc.devices.goniometer import GonioFeatures
from mxdc.engines.interfaces import IDataCollector, IAnalyst
from mxdc.utils import datatools, misc
from mxdc.utils.converter import energy_to_wavelength, dist_to_resol
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


GRACE_PERIOD = 10  # Amount of time to wait after completion for frames to all appear.


@implementer(IDataCollector)
class DataCollector(Engine):
    """
    Diffraction data collection Engine

    Signals:
        - message: (str,) messages
    """

    class Signals:
        message = Signal('message', arg_types=(str,))

    # Properties:
    name = 'Data Collector'

    def __init__(self):
        super().__init__()

        self.run_list = []
        self.runs = []
        self.results = []
        self.config = {}
        self.total = 1
        self.current_wedge = None

        self.analyst = Registry.get_utility(IAnalyst)
        self.progress_link = self.beamline.detector.connect('progress', self.on_progress)
        self.unwatch_frames()

        #self.beamline.synchrotron.connect('ready', self.on_beam_change)
        Registry.add_utility(IDataCollector, self)

    def configure(self, run_data, take_snapshots=True, analysis=None, anomalous=False):
        """
        Configure the data collection engine

        :param run_data: information about the data runs to collect
        :param take_snapshots: bool, whether to take sample snapshot images or not
        :param analysis: bool, whether to run analysis after acquiring frames
        :param anomalous: bool, enable analysis mode for data analysis
        """

        print(run_data)
        self.config['analysis'] = analysis
        self.config['anomalous'] = anomalous
        self.config['take_snapshots'] = take_snapshots
        self.config['runs'] = run_data[:] if isinstance(run_data, list) else [run_data]
        self.config['datasets'] = {
            run['uuid']: datatools.WedgeDispenser(run) for run in self.config['runs']
        }

    def prepare_for_wedge(self, wedge):
        logger.debug('Preparing for new dataset wedge ...')
        # setup folder for wedge
        self.beamline.dss.setup_folder(wedge['directory'], misc.get_project_name())

        # delete existing frames
        frames = [i + wedge['first'] for i in range(wedge['num_frames'])]
        self.beamline.detector.delete(wedge['directory'], wedge['name'], frames)

        # make sure shutter is closed before starting
        self.beamline.fast_shutter.close()

        # setup devices
        if abs(self.beamline.energy.get_position() - wedge['energy']) >= 0.0005:
            self.beamline.energy.move_to(wedge['energy'], wait=True)

        if abs(self.beamline.distance.get_position() - wedge['distance']) >= 0.1:
            self.beamline.distance.move_to(wedge['distance'], wait=True)

        self.beamline.attenuator.set(wedge['attenuation'], wait=True)
        logger.debug('Ready for acquisition.')

    def run(self):
        self.set_state(busy=True)
        self.total = sum([
            dataset.weight for dataset in self.config['datasets'].values()
        ])  # total raw time for all wedges

        current_attenuation = self.beamline.attenuator.get()
        self.results = []
        self.watch_frames()

        with self.beamline.lock:
            # Take snapshots and prepare end station mode
            self.take_snapshots()
            self.beamline.manager.collect(wait=True)
            self.emit('started', None)
            self.config['start_time'] = datetime.now(tz=pytz.utc)
            use_shutterless = (
                self.beamline.detector.supports(DetectorFeatures.SHUTTERLESS, DetectorFeatures.TRIGGERING) and
                self.beamline.goniometer.supports(GonioFeatures.TRIGGERING)
            )
            try:
                if use_shutterless:
                    self.run_shutterless()
                else:
                    self.run_simple()
            finally:
                self.beamline.fast_shutter.close()
            self.config['end_time'] = datetime.now(tz=pytz.utc)

            if self.stopped or self.paused:
                completion = {
                    uid: dataset.progress
                    for uid, dataset in self.config['datasets'].items()
                }
                self.emit('stopped', completion)
            else:
                self.emit('done', None)

            self.beamline.attenuator.set(current_attenuation)  # restore attenuation

        # Wait for Last image to be transferred
        time.sleep(GRACE_PERIOD)

        for uid, dataset in self.config['datasets'].items():
            metadata = self.save(dataset)
            self.results.append(metadata)
            if metadata and self.config['analysis']:
                self.analyse(metadata, dataset.sample)

        self.unwatch_frames()
        self.set_state(busy=False)
        return self.results

    def run_simple(self):
        is_first_frame = True

        for wedge in datatools.interleave(*self.config['datasets'].values()):
            self.emit('started', wedge)
            self.current_wedge = wedge
            if self.stopped or self.paused: break
            self.prepare_for_wedge(wedge)

            for i, frame in enumerate(datatools.generate_frames(wedge)):
                if self.stopped or self.paused: break
                # Prepare image header
                energy = self.beamline.energy.get_position()
                detector_parameters = {
                    'file_prefix': frame['name'],
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

                if self.stopped or self.paused:
                    break

                # perform scan
                self.beamline.detector.configure(**detector_parameters)
                self.beamline.detector.start(first=is_first_frame)
                self.beamline.goniometer.scan(
                    kind='simple',
                    time=frame['exposure'],
                    range=frame['delta'],
                    angle=frame['start'],
                    num_frames=1,
                    wait=True,
                )
                self.beamline.detector.save()

                # calculate progress
                wedge_progress = ((i + 1)/wedge['num_frames'])
                self.on_progress(None, wedge_progress, '')
                is_first_frame = False
                time.sleep(0)

    def run_shutterless(self):
        is_first_frame = True

        # Perform scan
        for wedge in datatools.interleave(*self.config['datasets'].values()):
            self.emit('started', wedge)
            self.current_wedge = wedge
            if self.stopped or self.paused:
                break
            self.prepare_for_wedge(wedge)
            energy = self.beamline.energy.get_position()
            detector_parameters = {
                'file_prefix': wedge['name'],
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

            if self.stopped or self.paused:
                break

            # Perform scan
            logger.info("Collecting Shutterless {} frames for dataset {}...".format(wedge['num_frames'], wedge['name']))
            logger.debug('Configuring detector for acquisition ...')
            self.beamline.detector.configure(**detector_parameters)
            self.beamline.detector.start(first=is_first_frame)

            logger.debug('Starting scan ...')
            self.beamline.goniometer.scan(
                kind='shutterless',
                time=wedge['exposure'] * wedge['num_frames'],
                range=wedge['delta'] * wedge['num_frames'],
                angle=wedge['start'],
                frames=wedge['num_frames'],
                wait=True,
                start_pos=wedge.get('p0'),
                end_pos=wedge.get('p1'),
            )
            self.beamline.detector.save()
            is_first_frame = False
            time.sleep(0)

    def take_snapshots(self):
        if self.config['take_snapshots'] and self.config['datasets']:
            names = [dataset.details['name'] for dataset in self.config['datasets'].values()]
            prefix = os.path.commonprefix(names) or 'SNAPSHOT'
            dataset = list(self.config['datasets'].values())[0]

            # setup folder
            self.beamline.dss.setup_folder(dataset.details['directory'], misc.get_project_name())

            # take snapshot
            snapshot_file = os.path.join(dataset.details['directory'], f'{prefix}.png')
            if not os.path.exists(snapshot_file):
                logger.info('Taking snapshot ...')
                img = self.beamline.sample_camera.get_frame()
                img.save(snapshot_file)

    def save(self, dataset):
        params = dataset.details
        template = self.beamline.detector.get_template(params['name'])
        reference = template.format(params['first'])

        try:
            info = datatools.dataset_from_reference(params['directory'], reference)
        except OSError as e:
            logger.error('Unable to find files on disk')
            return

        metadata = {
            'name': params['name'],
            'frames':  info['frames'],
            'filename': template,
            'group': params['group'],
            'container': params['container'],
            'start_time': min(info['start_time'], self.config['start_time']).isoformat(),
            'end_time': self.config['end_time'].isoformat(),
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

        # do not upload fewer than 2 frames
        if info['num_frames'] > 2:
            reply = self.beamline.lims.upload_data(self.beamline.name, filename)
            return reply

    def analyse(self, metadata, sample, first=False):
        if self.config['analysis'] is None:
            return

        flags = () if not self.config.get('anomalous') else ('anomalous',)
        if (self.config['analysis'] == 'screen') or (self.config['analysis'] == 'default' and metadata['type'] == 'SCREEN'):
            self.analyst.screen_dataset(metadata, flags=flags, sample=sample)
        elif (self.config['analysis'] == 'process') or (self.config['analysis'] == 'default' and metadata['type'] == 'DATA'):
            self.analyst.process_dataset(metadata, flags=flags, sample=sample)
        elif (self.config['analysis'] == 'powder') or (self.config['analysis'] == 'default' and metadata['type'] == 'XRD'):
            flags = ('calibrate',) if first else ()
            self.analyst.process_powder(metadata, flags=flags, sample=sample)

    def on_progress(self, obj, fraction, message):
        self.config['datasets'][self.current_wedge['uuid']].set_progress(fraction)

        overall = sum([
            dataset.progress*dataset.weight for dataset in self.config['datasets'].values()
        ])/self.total

        if not (self.paused or self.stopped):
            self.set_state(progress=(overall, message))

    def on_beam_change(self, obj, available):
        if not (self.stopped or self.paused) and self.is_busy() and not available:
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
            existing, resumable = self.beamline.detector.check(run['directory'], run['name'], first=run['first'])
            run['existing'] = datatools.summarize_list(existing)
            collected += len(datatools.frameset_to_list(run['existing']))

        self.configure(self.config['runs'], take_snapshots=False)
        self.beamline.all_shutters.open()
        self.start()

    def resume(self):
        logger.info("Resuming Collection ...")
        if self.paused:
            # wait for 1 minute then open all shutters before resuming
            message = "Beam available! Resuming data acquisition in 30 seconds!"
            self.emit('paused', False, message)
            GLib.timeout_add(30000, self.resume_sequence)

    def pause(self, reason=''):
        super().pause(reason)
        self.beamline.detector.stop()
        self.beamline.goniometer.stop()

    def stop(self):
        super().stop()
        self.beamline.detector.stop()
        self.beamline.goniometer.stop()

    def watch_frames(self):
        self.beamline.detector.handler_unblock(self.progress_link)

    def unwatch_frames(self):
        self.beamline.detector.handler_block(self.progress_link)
