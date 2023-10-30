from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime, timedelta

import mxio
import pytz
from gi.repository import GLib
from zope.interface import implementer
from mxio.formats import cbf


from mxdc import Registry, Signal, Engine
from mxdc.devices.detector import DetectorFeatures
from mxdc.devices.goniometer import GonioFeatures
from mxdc.engines.interfaces import IDataCollector, IAnalyst
from mxdc.utils import datatools, misc, decorators, scitools
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

        # self.beamline.synchrotron.connect('ready', self.on_beam_change)
        Registry.add_utility(IDataCollector, self)
        self.data_saver = ThreadPoolExecutor(max_workers=5)

    def save_dataset(self, dataset, analyse=True) -> tuple:
        timeout_time = datetime.utcnow() + timedelta(seconds=self.beamline.config.dataset.overhead)
        names = ",".join(details['name'] for details in dataset.get_details())

        logger.debug(f'Waiting for files to be transferred for datasets {names}...')
        #FIXME - check that all files have been transferred instead of waiting
        while datetime.utcnow() < timeout_time:
            time.sleep(0.001)

        logger.debug(f'Saving datasets {names}...')
        meta_data = [
            self.save(details) for details in dataset.get_details()
        ]
        logger.debug(f'Datasets {names} saved.')
        return analyse, meta_data, dataset.sample

    def analyse_dataset(self, future: Future):
        from mxio.formats import cbf
        analyse, meta_data, sample = future.result(timeout=5)

        for entry in meta_data:
            self.analyst.add_dataset(entry)
            self.results.append(entry)

        if analyse and meta_data:
            logger.debug(f'Running Analysis for saved dataset')
            data_type = meta_data[0]['type']
            self.analyse(*meta_data, sample=sample, kind=data_type)

    def configure(self, run_data, take_snapshots=True, analysis=None, anomalous=False):
        """
        Configure the data collection engine

        :param run_data: information about the data runs to collect
        :param take_snapshots: bool, whether to take sample snapshot images or not
        :param analysis: bool, whether to run analysis after acquiring frames
        :param anomalous: bool, enable analysis mode for data analysis
        """

        self.config['analysis'] = analysis
        self.config['anomalous'] = anomalous
        self.config['take_snapshot'] = take_snapshots
        self.config['runs'] = run_data[:] if isinstance(run_data, list) else [run_data]
        self.config['datasets'] = {
            run['uuid']: datatools.WedgeDispenser(
                run,
                distinct=(not self.beamline.detector.supports(DetectorFeatures.WEDGING))
            )
            for run in self.config['runs']
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

        self.beamline.attenuator.move_to(wedge['attenuation'], wait=True)
        logger.debug('Ready for acquisition.')

    def run(self):
        self.set_state(busy=True)
        self.total = sum([
            dataset.weight for dataset in self.config['datasets'].values()
        ])  # total raw time for all wedges

        current_attenuation = self.beamline.attenuator.get_position()
        self.results = []
        self.watch_frames()

        with self.beamline.lock:
            # Take snapshots and prepare end station mode
            if self.config['take_snapshot']:
                first_dset = next(iter(self.config['datasets'].values()))
                self.take_snapshot(first_dset.details)

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
                self.emit('done', {
                    uid: 1.0
                    for uid, dataset in self.config['datasets'].items()
                })

            self.beamline.attenuator.move_to(current_attenuation, wait=True)  # restore attenuation

        # Wait for Last image to be transferred
        for uid, dataset in self.config['datasets'].items():
            future = self.data_saver.submit(self.save_dataset, dataset, analyse=self.config['analysis'])
            future.add_done_callback(self.analyse_dataset)

        self.unwatch_frames()
        self.set_state(busy=False)
        return self.results

    def run_simple(self):
        is_first_frame = True
        owner = misc.get_project_name()
        group = misc.get_group_name()

        for wedge in datatools.interleave(*self.config['datasets'].values()):

            self.current_wedge = wedge
            if self.stopped or self.paused: break
            self.prepare_for_wedge(wedge)
            self.emit('started', wedge)
            # notify automounter that we will be busy for a while
            free_time = wedge['exposure'] * wedge['num_frames']
            self.beamline.automounter.standby(duration=free_time)

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
                    'num_triggers': 1,
                    'num_images': 1,
                    'start_angle': frame['start'],
                    'delta_angle': frame['delta'],
                    'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
                    'user': owner,
                    'group': group,
                }

                if self.stopped or self.paused:
                    break

                # perform scan
                self.beamline.detector.configure(**detector_parameters)
                success = self.beamline.detector.start(first=is_first_frame)
                if not success:
                    # Try one more time if it failed the first
                    success = self.beamline.detector.start()

                if not success:
                    logger.error('Detector did not start!')
                    self.emit('error', 'Detector failed to start. Acquisition aborted.')
                    self.stopped = True
                    continue

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
                wedge_progress = ((i + 1) / wedge['num_frames'])
                self.on_progress(None, wedge_progress, '')
                is_first_frame = False
                time.sleep(0)

    def run_shutterless(self):
        is_first_frame = True
        owner = misc.get_project_name()
        group = misc.get_group_name()
        # Perform scan
        for wedge in datatools.interleave(*self.config['datasets'].values()):
            self.current_wedge = wedge
            if self.stopped or self.paused:
                break
            self.prepare_for_wedge(wedge)
            energy = self.beamline.energy.get_position()
            self.emit('started', wedge)

            gonio_gating = self.beamline.goniometer.supports(GonioFeatures.GATING)
            #gonio_gating = True  # self.beamline.goniometer.supports(GonioFeatures.GATING)

            if gonio_gating:
                extras = {'num_images': 1, 'num_triggers': wedge['num_frames']}
            else:
                extras = {'num_images': wedge['num_frames'], 'num_triggers': 1}

            detector_parameters = {
                'file_prefix': wedge['name'],
                'start_frame': wedge['first'],
                'directory': wedge['directory'],
                'wavelength': energy_to_wavelength(energy),
                'energy': energy,
                'distance': round(self.beamline.distance.get_position(), 1),
                'two_theta': wedge['two_theta'],
                'exposure_time': wedge['exposure'],
                'start_angle': wedge['start'],
                'delta_angle': wedge['delta'],
                'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
                'user': owner,
                'group': group,
                **extras
            }

            if self.stopped or self.paused:
                break

            # Perform scan
            logger.info("Collecting Shutterless {} frames for dataset {}...".format(wedge['num_frames'], wedge['name']))
            logger.debug('Configuring detector for acquisition ...')
            self.beamline.detector.configure(**detector_parameters)
            success = self.beamline.detector.start(first=is_first_frame)

            if not success:
                # Try one more time if it failed the first
                success = self.beamline.detector.start()

            if not success:
                logger.error('Detector did not start')
                self.emit('error', 'Detector failed to start. Acquisition aborted.')
                self.stopped = True
                continue

            # notify automounter that we will be busy for a while
            free_time = wedge['exposure'] * wedge['num_frames']
            self.beamline.automounter.standby(duration=free_time)

            logger.debug('Starting scan ...')
            self.beamline.goniometer.scan(
                kind='shutterless',
                time=wedge['exposure']*wedge['num_frames'],
                range=wedge['delta']*wedge['num_frames'],
                angle=wedge['start'],
                frames=extras['num_triggers'],
                wait=True,
                start_pos=wedge.get('p0'),
                end_pos=wedge.get('p1'),
            )
            self.beamline.detector.save()
            is_first_frame = False
            time.sleep(0)

    def take_snapshot(self, params):
        # setup folder
        self.beamline.dss.setup_folder(params['directory'], misc.get_project_name())

        # take snapshot
        snapshot_file = os.path.join(params['directory'], f"{params['name']}.png")
        if os.path.exists(params['directory']):
            logger.info('Taking snapshot ...')
            self.beamline.sample_camera.save_frame(snapshot_file)
            logger.debug('Snapshot saved...')

    def prepare_for_saving(self, params):
        if params['name'] not in params['combine']:
            first = params['first']
            name = params['name']
            start = params['start']
            delta = params['delta']
            template = f'{name}_{{:05d}}.cbf'

            # Converting multiple sub-datasets to single CBF formatted dataset
            frame_numbers = []
            for part_name in params['combine']:
                self.beamline.detector.wait_for_files(params['directory'], part_name)
                reference = self.beamline.detector.get_template(part_name).format(1)
                dset = mxio.DataSet.new_from_file(os.path.join(params['directory'], reference))
                for frame in dset.frames():
                    index = int(round(first + (frame.start_angle - start)/delta))
                    frame_numbers.append(index)
                    cbf_file = template.format(index)
                    cbf.CBFDataSet.save_frame(os.path.join(params['directory'], cbf_file), frame)
            frame_set = datatools.summarize_list(frame_numbers)
        else:
            self.beamline.detector.wait_for_files(params['directory'], params['name'])
            template = self.beamline.detector.get_template(params['name'])
            reference = template.format(params['first'])

            try:
                info = datatools.dataset_from_reference(os.path.join(params['directory'], reference))
                frame_set = info['frames']
            except OSError:
                logger.warning(f'Unable to find files on disk: {reference}')
                frame_set = ""
        return template, frame_set

    def save(self, params):
        template, frame_set = self.prepare_for_saving(params)
        beam_fwhm = self.beamline.config.beam_shape

        # Estimate flux from current beamline/dataset settings
        beam_flux = self.beamline.beam_tuner.get_state("flux")
        beam_flux *= scitools.gaussian_fraction(self.beamline.aperture.get_position()/2, *beam_fwhm)

        metadata = {
            'name': params['name'],
            'frames': frame_set,
            'filename': template,
            'group': params['group'],
            'container': params['container'],
            'start_time': self.config['start_time'].isoformat(),
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
            'beam_flux': round(beam_flux),
            'beam_fwhm': beam_fwhm,
            'resolution': dist_to_resol(params['distance'], self.beamline.detector.mm_size, params['energy']),
            'detector_size': min(self.beamline.detector.size),
            'start_angle': params['start'],
            'delta_angle': params['delta'],
            'comments': params['notes']
        }
        filename = os.path.join(metadata['directory'], '{}.meta'.format(metadata['name']))
        misc.save_metadata(metadata, filename)
        reply = self.beamline.lims.upload_data(self.beamline.name, filename)
        return reply

    def analyse(self, *metadata, sample=None, kind='SCREEN', first=False):
        if self.config['analysis'] is None:
            return

        flags = () if not self.config.get('anomalous') else ('anomalous',)
        if (self.config['analysis'] == 'screen') or (self.config['analysis'] == 'default' and kind == 'SCREEN'):
            self.analyst.screen_dataset(*metadata, flags=flags, sample=sample)
        elif (self.config['analysis'] == 'process') or (self.config['analysis'] == 'default' and kind == 'DATA'):
            self.analyst.process_dataset(*metadata, flags=flags, sample=sample)
        elif (self.config['analysis'] == 'powder') or (self.config['analysis'] == 'default' and kind == 'XRD'):
            flags = ('calibrate',) if first else ()
            self.analyst.process_powder(*metadata, flags=flags, sample=sample)

    def on_progress(self, obj, fraction, message):
        self.config['datasets'][self.current_wedge['uuid']].set_progress(fraction)

        overall = sum([
            dataset.progress * dataset.weight for dataset in self.config['datasets'].values()
        ]) / self.total

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

    @decorators.async_call
    def pause(self, reason=''):
        super().pause(reason)
        self.beamline.detector.stop()
        self.beamline.goniometer.stop()

    @decorators.async_call
    def stop(self):
        super().stop()
        self.beamline.detector.stop()
        self.beamline.goniometer.stop()

    def watch_frames(self):
        self.beamline.detector.handler_unblock(self.progress_link)

    def unwatch_frames(self):
        self.beamline.detector.handler_block(self.progress_link)
