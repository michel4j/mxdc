from bcm.beamline.interfaces import IBeamline
from bcm.engine import centering, snapshot, auto
from bcm.engine.interfaces import IDataCollector
from bcm.protocol import ca
from bcm.utils import json, runlists
from bcm.utils.converter import energy_to_wavelength, dist_to_resol
from bcm.utils.log import get_module_logger
from bcm.utils.misc import get_project_name
from twisted.python.components import globalRegistry
from zope.interface import implements
from Queue import Queue
import gobject
import os
import pwd
import threading
import time
import re
import subprocess

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


class DataCollector(gobject.GObject):
    implements(IDataCollector)
    __gsignals__ = {
        'new-image': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
        'progress': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)),
        'done': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'paused': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN, gobject.TYPE_PYOBJECT)),
        'started': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'stopped': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'error': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    }

    STATE_PENDING, STATE_RUNNING, STATE_DONE, STATE_SKIPPED = range(4)

    def __init__(self):
        gobject.GObject.__init__(self)
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
        self.new_image_handler_id = self.beamline.detector.connect('new-image', self.on_new_image)
        self.beamline.storage_ring.connect('beam', self.on_beam_change)
        self.beamline.detector.handler_block(self.new_image_handler_id)

    def configure(self, run_data, take_snapshots=True):
        self.config['take_snapshots'] = take_snapshots
        self.config['runs'] = run_data[:] if isinstance(run_data, list) else [run_data]
        datasets, wedges = runlists.generate_wedges(self.config['runs'])
        self.config['wedges'] = wedges
        self.config['datasets'] = datasets
        self.beamline.image_server.set_user(pwd.getpwuid(os.geteuid())[0], os.geteuid(), os.getegid())

        # delete existing frames
        for wedge in wedges:
            frame_list = [wedge['frame_template'].format(i + wedge['start_frame']) for i in range(wedge['num_frames'])]
            self.beamline.detector.delete(wedge['directory'], *frame_list)

    def start(self):
        if self.beamline is None:
            _logger.error('No Beamline found. Aborting data collection...')
            return False

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
        self.beamline.detector.handler_unblock(self.new_image_handler_id)
        self.total_frames = sum([wedge['num_frames'] for wedge in self.config['wedges']])
        current_attenuation = self.beamline.attenuator.get()

        with self.beamline.lock:
            # Take snapshots and prepare endstation mode
            self.take_snapshots()
            self.beamline.goniometer.set_mode('COLLECT', wait=True)
            gobject.idle_add(self.emit, 'started')
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
        if not (self.stopped or self.paused):
            gobject.idle_add(self.emit, 'done')
        self.beamline.attenuator.set(current_attenuation)  # restore attenuation
        self.collecting = False
        self.beamline.detector.handler_block(self.new_image_handler_id)
        self.beamline.detector_cover.close()
        return self.results

    def run_default(self):
        is_first_frame = True
        self.count = 0
        for wedge in self.config['wedges']:
            if self.stopped or self.paused: break
            self.prepare_for_wedge(wedge)

            for frame in runlists.generate_frame_list(wedge):
                if self.stopped or self.paused: break
                # Prepare image header
                detector_parameters = {
                    'file_prefix': frame['file_prefix'],
                    'delta_angle': frame['delta_angle'],
                    'directory': frame['directory'],
                    'distance': frame['distance'],
                    'exposure_time': frame['exposure_time'],
                    'start_frame': frame['start_frame'],
                    'wavelength': energy_to_wavelength(frame['energy']),
                    'energy': frame['energy'],
                    'frame_name': frame['frame_name'],
                    'start_angle': frame['start_angle'],
                }

                # prepare goniometer for scan
                self.beamline.goniometer.configure(
                    time=frame['exposure_time'], delta=frame['delta_angle'], angle=frame['start_angle']
                )
                if frame.get('dafs', False):
                    self.beamline.i_0.async_count(frame['exposure_time'])

                self.beamline.detector.set_parameters(detector_parameters)
                self.beamline.detector.start(first=is_first_frame)
                self.beamline.goniometer.scan(wait=True, timeout=frame['exposure_time'] * 4)
                self.beamline.detector.save()

                if frame.get('dafs', False):
                    _logger.info('DAFS I0  {}\t{}'.format(frame['frame_name'], self.beamline.i_0.avg_value))

                is_first_frame = False
                time.sleep(0)

    def run_shutterless(self):
        is_first_frame = True
        self.count = 0
        for wedge in self.config['wedges']:
            if self.stopped or self.paused: break
            self.prepare_for_wedge(wedge)
            detector_parameters = {
                'file_prefix': wedge['file_prefix'],
                'start_frame': wedge['start_frame'],
                'directory': wedge['directory'],
                'wavelength': energy_to_wavelength(wedge['energy']),
                'energy': wedge['energy'],
                'distance': wedge['distance'],
                'two_theta': wedge['two_theta'],
                'exposure_time': wedge['exposure_time'],
                'num_frames': wedge['num_frames'],
                'start_angle': wedge['start_angle'],
                'delta_angle': wedge['delta_angle'],
                'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
            }

            # prepare goniometer for scan
            _logger.info("Collecting {} images starting at: {}".format(
                wedge['num_frames'], wedge['frame_template'].format(wedge['start_frame']))
            )
            self.beamline.goniometer.configure(
                time=wedge['exposure_time'] * wedge['num_frames'],
                delta=wedge['delta_angle'] * wedge['num_frames'],
                angle=wedge['start_angle']
            )

            # Perform scan
            self.beamline.detector.set_parameters(detector_parameters)
            if self.stopped or self.paused: break
            self.beamline.detector.start(first=is_first_frame)
            self.beamline.goniometer.scan(wait=True, timeout=wedge['exposure_time'] * wedge['num_frames'] * 2)

            is_first_frame = False
            time.sleep(0)

    def take_snapshots(self):
        if self.config['take_snapshots']:
            datasets = self.config['datasets']
            name = os.path.commonprefix([dataset['name'] for dataset in datasets])
            prefix = '{}-pic'.format(name)
            a1 = datasets[0]['start_angle']
            a2 = (a1 + 90.0) % 360.0
            if not os.path.exists(os.path.join(datasets[0]['directory'], '{}_{:0.0f}.png'.format(prefix, a1))):
                _logger.info('Taking snapshots of crystal at {:0.0f} and {:0.0f}'.format(a1, a2))
                snapshot.take_sample_snapshots(
                    prefix, os.path.join(datasets[0]['directory']), [a2, a1], decorate=True
                )

    def prepare_for_wedge(self, wedge):
        # make sure shutter is closed before starting
        self.beamline.exposure_shutter.close()

        # setup folder for wedge
        self.beamline.image_server.setup_folder(wedge['directory'])

        # setup devices
        if abs(self.beamline.energy.get_position() - wedge['energy']) >= 0.0005:
            self.beamline.energy.move_to(wedge['energy'], wait=True)

        if abs(self.beamline.diffractometer.distance.get_position() - wedge['distance']) >= 0.1:
            self.beamline.diffractometer.distance.move_to(wedge['distance'], wait=True)

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
                data['distance'], self.beamline.detector.resolution, min(self.beamline.detector.size), data['energy']
            )
            data['beamline_name'] = self.beamline.name
            data['detector_size'] = min(self.beamline.detector.size)
            data['pixel_size'] = self.beamline.detector.resolution
            data['beam_x'], data['beam_y'] = self.beamline.detector.get_origin()
            data['detector'] = self.beamline.detector.detector_type
            filename = os.path.join(data['directory'], '{}.SUMMARY'.format(data['name']))
            if os.path.exists(filename):
                old_data = json.load(file(filename))
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
        gobject.idle_add(self.emit, 'new-image', file_path)
        if not (self.paused or self.stopped):
            gobject.idle_add(self.emit, 'progress', fraction)

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
            gobject.idle_add(self.emit, 'paused', False, {})
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
        gobject.idle_add(self.emit, 'paused', True, info)

    def stop(self):
        _logger.info("Stopping Collection ...")
        self.stopped = True
        self.paused = False
        self.beamline.detector.stop()
        self.beamline.goniometer.stop()
        gobject.idle_add(self.emit, 'stopped')


class Screener(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['progress'] = (
        gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT, gobject.TYPE_INT, gobject.TYPE_INT))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN, gobject.TYPE_PYOBJECT))
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['sync'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN, gobject.TYPE_STRING))
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['analyse-request'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,))
    __gsignals__['new-datasets'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,))
    __gsignals__['new-image'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))

    TASK_MOUNT, TASK_ALIGN, TASK_PAUSE, TASK_COLLECT, TASK_ANALYSE, TASK_DISMOUNT = range(6)
    TASK_STATE_PENDING, TASK_STATE_RUNNING, TASK_STATE_DONE, TASK_STATE_ERROR, TASK_STATE_SKIPPED = range(5)

    PAUSE_TASK, PAUSE_BEAM, PAUSE_ALIGN, PAUSE_MOUNT, PAUSE_UNRELIABLE = range(5)

    def __init__(self):
        gobject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.skip_collected = False
        self.data_collector = None
        self._collect_results = []
        self.last_pause = None
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.data_collector = DataCollector()
        self.data_collector.connect('new-image', self.on_new_image)

    def configure(self, run_list):
        self.run_list = run_list
        self.total_items = len(self.run_list)

    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Screener')
        self.paused = False
        self.stopped = False
        worker_thread.start()

    def notify_progress(self, status):
        # Notify progress
        if status == self.TASK_STATE_DONE:
            fraction = float(self.pos + 1) / self.total_items
        else:
            fraction = float(self.pos) / self.total_items
        gobject.idle_add(self.emit, 'progress', fraction, self.pos, status)

    def on_new_image(self, obj, file_path):
        gobject.idle_add(self.emit, 'new-image', file_path)

    def run(self):
        ca.threads_init()
        gobject.idle_add(self.emit, 'started')
        pause_info = {}

        for self.pos, task in enumerate(self.run_list):
            _logger.debug('TASK: "%s"' % str(task))

            if self.paused:
                gobject.idle_add(self.emit, 'paused', True, pause_info)
                self.last_pause = pause_info.get('type', None)
                pause_info = {}
                while self.paused and not self.stopped:
                    time.sleep(0.1)
                gobject.idle_add(self.emit, 'paused', False, pause_info)

            if self.stopped:
                gobject.idle_add(self.emit, 'stopped')
                break

            # Perform the screening task here
            if task.task_type == Screener.TASK_PAUSE:
                pause_info = {
                    'type': Screener.PAUSE_TASK,
                    'task': self.run_list[self.pos - 1].name,
                    'sample': self.run_list[self.pos]['sample']['name'],
                    'port': self.run_list[self.pos]['sample']['port']
                }
                self.pause()
                self.notify_progress(Screener.TASK_STATE_DONE)

            elif task.task_type == Screener.TASK_MOUNT:
                _logger.debug('TASK: Mount "%s"' % task['sample']['port'])
                self.notify_progress(Screener.TASK_STATE_RUNNING)
                success = auto.auto_mount_manual(self.beamline, task['sample']['port'])
                mounted_info = self.beamline.automounter.mounted_state
                if not success or mounted_info is None:
                    self.stop()
                    self.pause()
                    pause_info = {
                        'type': Screener.PAUSE_MOUNT,
                        'task': self.run_list[self.pos - 1].name,
                        'sample': self.run_list[self.pos]['sample']['name'],
                        'port': self.run_list[self.pos]['sample']['port']
                    }
                    self.notify_progress(Screener.TASK_STATE_ERROR)
                else:
                    port, barcode = mounted_info
                    if port != self.run_list[self.pos]['sample']['port']:
                        gobject.idle_add(
                            self.emit, 'sync', False,
                            'Port mismatch. Expected {}.'.format(
                                self.run_list[self.pos]['sample']['port']
                            )
                        )
                    elif barcode != self.run_list[self.pos]['sample']['barcode']:
                        gobject.idle_add(
                            self.emit, 'sync', False,
                            'Barcode mismatch. Expected {}.'.format(
                                self.run_list[self.pos]['sample']['barcode']
                            )
                        )
                    else:
                        gobject.idle_add(self.emit, 'sync', True, '')
                        self.notify_progress(Screener.TASK_STATE_DONE)

            elif task.task_type == Screener.TASK_DISMOUNT:
                _logger.warn('TASK: Dismounting Last Sample')
                if self.beamline.automounter.is_mounted():  # only attempt if any sample is mounted
                    self.notify_progress(Screener.TASK_STATE_RUNNING)
                    success = auto.auto_dismount_manual(self.beamline, task['sample']['port'])
                    self.notify_progress(Screener.TASK_STATE_DONE)

            elif task.task_type == Screener.TASK_ALIGN:
                _logger.warn('TASK: Align sample "%s"' % task['sample']['name'])

                if self.beamline.automounter.is_mounted(task['sample']['port']):
                    self.notify_progress(Screener.TASK_STATE_RUNNING)

                    for method in ['crystal', 'capillary', 'loop']:
                        if task.options.get(method):
                            break
                    if method == 'crystal':
                        _out = centering.auto_center_crystal()
                    elif method == 'capillary':
                        _out = centering.auto_center_capillary()
                    else:
                        _out = centering.auto_center_loop()

                    if not _out:
                        _logger.error('Error attempting auto loop centering "%s"' % task['sample']['name'])
                        pause_info = {'type': Screener.PAUSE_ALIGN,
                                      'task': self.run_list[self.pos - 1].name,
                                      'sample': self.run_list[self.pos]['sample']['name'],
                                      'port': self.run_list[self.pos]['sample']['port']}
                        self.pause()
                        self.notify_progress(Screener.TASK_STATE_ERROR)
                    elif _out < 70:
                        pause_info = {'type': Screener.PAUSE_UNRELIABLE,
                                      'task': self.run_list[self.pos - 1].name,
                                      'sample': self.run_list[self.pos]['sample']['name'],
                                      'port': self.run_list[self.pos]['sample']['port']}
                        self.pause()
                        self.notify_progress(Screener.TASK_STATE_ERROR)
                    else:
                        self.notify_progress(Screener.TASK_STATE_DONE)
                    directory = os.path.join(task['directory'], task['sample']['name'], 'test')
                    if not os.path.exists(directory):
                        os.makedirs(directory)  # make sure directories exist
                    prefix = '%s_test-pic' % (task['sample']['name'])
                    if not os.path.exists(os.path.join(directory, '%s_%0.1f.png' % (prefix, 0.0))):
                        _logger.info('Taking snapshots of crystal at %0.1f and %0.1f' % (0.0, 90.0))
                        snapshot.take_sample_snapshots(prefix, directory, [0.0, 90.0], decorate=True)
                else:
                    self.notify_progress(Screener.TASK_STATE_SKIPPED)
                    _logger.warn('Skipping task because given sample is not mounted')

            elif task.task_type == Screener.TASK_COLLECT:
                _logger.warn('TASK: Collect frames for "%s"' % task['sample']['name'])

                if self.beamline.automounter.is_mounted(task['sample']['port']):
                    self.notify_progress(Screener.TASK_STATE_RUNNING)
                    sample = task['sample']
                    params = DEFAULT_PARAMETERS.copy()
                    params['name'] = "%s_test" % sample['name']
                    params['two_theta'] = self.beamline.two_theta.get_position()
                    params['crystal_id'] = sample.get('id', None)
                    params['experiment_id'] = sample.get('experiment_id', None)
                    params['directory'] = os.path.join(task['directory'], sample['name'], 'test')
                    params['energy'] = [self.beamline.energy.get_position()]
                    for k in ['distance', 'delta_angle', 'exposure_time', 'start_angle', 'total_angle',
                              'first_frame', 'skip']:
                        params[k] = task.options[k]

                    _logger.debug('Collecting frames for crystal `%s`, in directory `%s`.' % (
                        params['name'], params['directory']))
                    if not os.path.exists(params['directory']):
                        os.makedirs(params['directory'])  # make sure directories exist
                    self.data_collector.configure(params, take_snapshots=False)
                    results = self.data_collector.run()
                    task.options['results'] = results
                    gobject.idle_add(self.emit, 'new-datasets', results)
                    self.notify_progress(Screener.TASK_STATE_DONE)
                else:
                    self.notify_progress(Screener.TASK_STATE_SKIPPED)
                    _logger.warn('Skipping task because given sample is not mounted')

            elif task.task_type == Screener.TASK_ANALYSE:
                collect_task = task.options.get('collect_task')
                if collect_task is not None:
                    collect_results = collect_task.options.get('results', [])
                    if len(collect_results) > 0:
                        images = runlists.get_disk_dataset(
                            collect_results[0]['directory'],
                            collect_results[0]['name']
                        )
                        _a_params = {
                            'directory': os.path.join(task['directory'], task['sample']['name'], 'scrn'),
                            'info': {'anomalous': False, 'file_names': images[:1]},
                            'type': 'SCRN',
                            'crystal': task.options['sample'],
                            'name': collect_results[0]['name']
                        }

                        if not os.path.exists(_a_params['directory']):
                            os.makedirs(_a_params['directory'])  # make sure directories exist
                        gobject.idle_add(self.emit, 'analyse-request', _a_params)
                        self._collect_results = []
                        _logger.warn('Requesting analysis')
                        self.notify_progress(Screener.TASK_STATE_DONE)
                    else:
                        self.notify_progress(Screener.TASK_STATE_SKIPPED)
                        _logger.warn('Skipping task because frames were not collected')
                else:
                    self.notify_progress(Screener.TASK_STATE_SKIPPED)
                    _logger.warn('Skipping task because frames were not collected')

        gobject.idle_add(self.emit, 'done')
        self.stopped = True
        self.beamline.exposure_shutter.close()

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.stopped = True
        self.data_collector.stop()
