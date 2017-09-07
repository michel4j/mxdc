import os
import pwd
import threading
import time

from gi.repository import GObject
from twisted.python.components import globalRegistry
from zope.interface import implements

from mxdc.com import ca
from mxdc.engine import centering, snapshot, auto
from mxdc.interface.beamlines import IBeamline
from mxdc.interface.engines import IDataCollector
from mxdc.utils import json, runlists
from mxdc.utils import misc
from mxdc.utils.config import settings
from mxdc.utils.converter import energy_to_wavelength, dist_to_resol
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

DEFAULT_PARAMETERS = {
    'name': 'test',
    'directory': '/tmp',
    'distance': 250.0,
    'delta_angle': 1.0,
    'exposure_time': 1.0,
    'start_angle': 0,
    'total_angle': 1.0,
    'first_frame': 1,
    'num_frames': 1,
    'inverse_beam': False,
    'wedge': 360.0,
    'energy_label': ['E0'],
    'number': 1,
    'two_theta': 0.0,
}


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

    STATE_PENDING, STATE_RUNNING, STATE_DONE, STATE_SKIPPED = range(4)

    def __init__(self):
        GObject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.collecting = False
        self.run_list = []
        self.runs = []
        self.results = {}
        self.config = {}
        self.total_frames = 0
        self.count = 0
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.beamline.detector.connect('new-image', self.on_new_image)
        self.beamline.storage_ring.connect('beam', self.on_beam_change)
        globalRegistry.register([], IDataCollector, '', self)

    def configure(self, run_data, take_snapshots=True):
        self.config['take_snapshots'] = take_snapshots
        self.config['runs'] = run_data[:] if isinstance(run_data, list) else [run_data]
        datasets, wedges = runlists.generate_wedges(self.config['runs'])
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

        self.results = self.save_summary(self.config['datasets'])
        self.beamline.lims.upload_datasets(self.beamline, self.results)
        if not (self.stopped or self.paused):
            GObject.idle_add(self.emit, 'done')
        self.beamline.attenuator.set(current_attenuation)  # restore attenuation
        self.collecting = False
        self.beamline.detector_cover.close()
        return self.results

    def run_default(self):
        is_first_frame = True
        self.count = 0
        for wedge in self.config['wedges']:
            if self.stopped or self.paused: break
            self.prepare_for_wedge(wedge)

            for frame in runlists.generate_frames(wedge):
                if self.stopped or self.paused: break
                # Prepare image header
                detector_parameters = {
                    'file_prefix': frame['dataset'],
                    'delta_angle': frame['delta'],
                    'directory': frame['directory'],
                    'distance': frame['distance'],
                    'exposure_time': frame['exposure'],
                    'start_frame': frame['first'],
                    'wavelength': energy_to_wavelength(frame['energy']),
                    'energy': frame['energy'],
                    'frame_name': frame['frame_name'],
                    'start_angle': frame['start'],
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
            _logger.info("Collecting {} images starting at: {}".format(
                wedge['num_frames'], wedge['frame_template'].format(wedge['start_frame']))
            )
            self.beamline.goniometer.configure(
                time=wedge['exposure'] * wedge['num_frames'],
                delta=wedge['delta'] * wedge['num_frames'],
                angle=wedge['start']
            )

            # Perform scan
            self.beamline.detector.set_parameters(detector_parameters)
            if self.stopped or self.paused: break
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
                _logger.info('Taking snapshots of crystal at {:0.0f} and {:0.0f}'.format(a1, a2))
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

    def save_summary(self, data_list):
        results = []
        for d in data_list:
            data = d.copy()

            data['id'] = None
            data['frame_sets'], data['num_frames'] = runlists.get_disk_frameset(
                data['directory'],
                '{}_*.{}'.format(data['name'], self.beamline.detector.file_extension),
            )

            if data['num_frames'] < 2:
                continue

            data['wavelength'] = energy_to_wavelength(data['energy'])
            data['resolution'] = dist_to_resol(
                data['distance'], self.beamline.detector.mm_size, data['energy']
            )
            data['beamline_name'] = self.beamline.name
            data['detector_size'] = min(self.beamline.detector.size)
            data['pixel_size'] = self.beamline.detector.resolution
            data['beam_x'], data['beam_y'] = self.beamline.detector.get_origin()
            data['detector'] = self.beamline.detector.detector_type
            filename = os.path.join(data['directory'], '{}.SUMMARY'.format(data['name']))
            if os.path.exists(filename):
                with open(filename, 'r') as handle:
                    old_data = json.load(handle)
                data['id'] = data['id'] if not old_data.get('id') else old_data['id']
                data['crystal_id'] = (
                    data.get('crystal_id') if not old_data.get('crystal_id')
                    else old_data['crystal_id']
                )
                data['experiment_id'] = (
                    data.get('experiment_id') if not old_data.get('experiment_id')
                    else old_data['experiment_id']
                )

            with open(filename, 'w') as fobj:
                json.dump(data, fobj, indent=4)
            results.append(data)
        return results

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
        _logger.info("Resuming Collection ...")
        if self.paused:
            GObject.idle_add(self.emit, 'paused', False, {})
            self.paused = False
            frame_list = runlists.generate_run_list(self.config['runs'])
            existing, bad = runlists.check_frame_list(
                frame_list, self.beamline.detector.file_extension, detect_bad=False
            )
            for run in self.config['runs']:
                run['skip'] = runlists.merge_framesets(existing.get(run['name'], ''), run.get('skip', ''),
                                                       bad.get(run['name'], ''))
            self.configure(self.config['runs'], take_snapshots=False)
            self.start()

    def pause(self, info={}):
        _logger.info("Pausing Collection ...")
        self.paused = True
        self.beamline.detector.stop()
        self.beamline.goniometer.stop()
        GObject.idle_add(self.emit, 'paused', True, info)

    def stop(self):
        _logger.info("Stopping Collection ...")
        self.stopped = True
        self.paused = False
        self.beamline.detector.stop()
        self.beamline.goniometer.stop()
        while self.collecting:
            time.sleep(0.1)
        GObject.idle_add(self.emit, 'stopped')


class Automator(GObject.GObject):
    class Task:
        (MOUNT, CENTER, PAUSE, ACQUIRE, ANALYSE, DISMOUNT) = range(6)

    TaskNames = ('Mount', 'Center', 'Pause', 'Acquire', 'Analyse', 'Dismount')

    __gsignals__ = {
        'analysis-request': (GObject.SIGNAL_RUN_LAST, None, (object,)),
        'progress': (GObject.SIGNAL_RUN_LAST, None, (float, str)),
        'sample-done': (GObject.SIGNAL_RUN_LAST, None, (str,)),
        'sample-started': (GObject.SIGNAL_RUN_LAST, None, (str,)),
        'done': (GObject.SIGNAL_RUN_LAST, None, []),
        'paused': (GObject.SIGNAL_RUN_LAST, None, (bool, str)),
        'started': (GObject.SIGNAL_RUN_LAST, None, []),
        'stopped': (GObject.SIGNAL_RUN_LAST, None, []),
        'error': (GObject.SIGNAL_RUN_LAST, None, (str,)),
    }

    def __init__(self):
        super(Automator, self).__init__()
        self.paused = False
        self.pause_message = ''
        self.stopped = True
        self.total = 1
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.collector = globalRegistry.lookup([], IDataCollector)

    def configure(self, samples, tasks):
        self.samples = samples
        self.tasks = tasks
        self.total = len(tasks) * len(samples)

    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Automator')
        self.paused = False
        self.stopped = False
        worker_thread.start()

    def notify_progress(self, pos, task, sample):
        fraction = float(pos) / self.total
        msg = '{}: {}/{}'.format(self.TaskNames[task['type']], sample['group'], sample['name'])
        GObject.idle_add(self.emit, 'progress', fraction, msg)

    def run(self):
        ca.threads_init()
        GObject.idle_add(self.emit, 'started')
        pos = 0
        self.pause_message = ''
        for sample in self.samples:
            if self.stopped: break
            GObject.idle_add(self.emit, 'sample-started', sample['uuid'])
            for task in self.tasks:
                if self.paused:
                    GObject.idle_add(self.emit, 'paused', True, self.pause_message)
                    while self.paused and not self.stopped:
                        time.sleep(0.1)
                    GObject.idle_add(self.emit, 'paused', False, '')

                if self.stopped: break
                pos += 1
                self.notify_progress(pos, task, sample)
                _logger.info(
                    'Sample: {}/{}, Task: {}'.format(sample['group'], sample['name'], self.TaskNames[task['type']])
                )
                time.sleep(5)

                if task['type'] == self.Task.PAUSE:
                    self.pause(
                        'As requested, automation has been paused for manual intervention. '
                        'Please resume after intervening to continue the sequence. '
                    )
                elif task['type'] == self.Task.CENTER:
                    if self.beamline.automounter.is_mounted(sample['port']):
                        method = task['options'].get('method')
                        quality = centering.auto_center(method=method)
                        if quality < 70:
                            self.pause('Error attempting auto {} centering {}'.format(method, sample['name']))
                    else:
                        self.stop(error='Sample not mounted. Unable to continue automation!')

                elif task['type'] == self.Task.MOUNT:
                    success = auto.auto_mount_manual(self.beamline, sample['port'])
                    mounted_info = self.beamline.automounter.mounted_state
                    if not success or mounted_info is None:
                        self.stop(error='Mouting Failed. Unable to continue automation!')
                    else:
                        port, barcode = mounted_info
                        if port != sample['port']:
                            GObject.idle_add(
                                self.emit, 'mismatch',
                                'Port mismatch. Expected {}.'.format(
                                    sample['port']
                                )
                            )
                        elif sample['barcode'] and barcode and barcode != sample['barcode']:
                            GObject.idle_add(
                                self.emit, 'mismatch',
                                'Barcode mismatch. Expected {}.'.format(
                                    sample['barcode']
                                )
                            )
                elif task['type'] == self.Task.ACQUIRE:
                    if self.beamline.automounter.is_mounted(sample['port']):
                        params = {}
                        params.update(task['options'])
                        params = runlists.prepare_run(params, sample)
                        _logger.debug('Acquiring frames for sample {}, in directory {}.'.format(
                            params['name'], params['directory']
                        ))
                        self.collector.configure(params, take_snapshots=True)
                        sample['results'] = self.collector.run()
                    else:
                        self.stop(error='Sample not mounted. Unable to continue automation!')

                elif task['type'] == Automator.Task.ANALYSE:
                    if sample.get('results') is not None:
                        params = {
                            'method': task['options'].get('method'),
                            'sample': sample,
                        }
                        params = runlists.prepare_run(params, sample)
                        GObject.idle_add(self.emit, 'analysis-request', params)
                    else:
                        self.stop(error='Data not available. Unable to continue automation!')
            GObject.idle_add(self.emit, 'sample-done', sample['uuid'])

        if self.stopped:
            GObject.idle_add(self.emit, 'stopped')
            _logger.info('Automation stopped')

        if not self.stopped:
            if self.beamline.automounter.is_mounted():
                port, barcode = self.beamline.automounter.mounted_state
                auto.auto_dismount_manual(self.beamline, port)
            GObject.idle_add(self.emit, 'done')
            _logger.info('Automation complete')

    def pause(self, message=''):
        if message:
            _logger.warn(message)
        self.pause_message = message
        self.paused = True

    def resume(self):
        self.paused = False
        self.pause_message = ''
        self.collector.resume()

    def stop(self, error=''):
        self.collector.stop()
        self.stopped = True
        self.paused = False
        if error:
            _logger.error(error)
            GObject.idle_add(self.emit, 'error', error)