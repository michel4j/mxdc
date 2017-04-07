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
import gobject
import os
import pwd
import threading
import time


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
    'energy': [12.658],
    'energy_label': ['E0'],
    'number': 1,
    'two_theta': 0.0,
    'jump': 0.0
}


class DataCollector(gobject.GObject):
    implements(IDataCollector)
    __gsignals__ = {
        'new-image': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_INT, gobject.TYPE_STRING)),
        'progress': (
            gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT, gobject.TYPE_INT)),
        'done': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []), 'paused': (
            gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN, gobject.TYPE_PYOBJECT)),
        'started': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'stopped': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'error': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    }

    STATE_PENDING, STATE_RUNNING, STATE_DONE, STATE_SKIPPED = range(4)

    def __init__(self):
        gobject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.skip_existing = False
        self.run_list = []
        self.runs = []
        self.results = {}
        self.config = {}
        self.beamline = None
        self.beam_connect = None
        self.total_frames = 0

    def configure(self, run_data, skip_existing=True, take_snapshots=True):
        # associate beamline devices
        self.beamline = globalRegistry.lookup([], IBeamline)

        if self.beam_connect:
            self.beamline.storage_ring.disconnect(self.beam_connect)
        self.beam_connect = self.beamline.storage_ring.connect('beam', self.on_beam_change)

        self.config['skip_existing'] = skip_existing
        self.config['take_snapshots'] = take_snapshots
        self.config['runs'] = run_data[:] if isinstance(run_data, list) else [run_data]

        datasets, wedges = runlists.generate_wedges(self.config['runs'])

        self.config['wedges'] = wedges
        self.config['datasets'] = datasets
        self.config['user_properties'] = (pwd.getpwuid(os.geteuid())[0], os.geteuid(), os.getegid())

    def start(self):
        if self.beamline is None:
            _logger.error('No Beamline found. Aborting data collection...')
            return False
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Data Collector')
        self.paused = False
        self.stopped = False
        worker_thread.start()

    def run(self):
        if self.beamline.detector.shutterless:
            self.run_shutterless()
        else:
            self.run_default()

    def run_default(self):
        ca.threads_init()
        self.beamline.lock.acquire()

        skip_existing = self.config['skip_existing']
        datasets = self.config['datasets']
        wedges = self.config['wedges']

        # Calcualte total work
        self.total_frames = sum([wedge['num_frames'] for wedge in wedges])

        # Take snapshots before beginning collection
        if self.config['take_snapshots']:
            name = os.path.commonprefix([dataset['name'] for dataset in datasets])
            prefix = '%s-pic' % (name)
            a1 = datasets[0]['start_angle']
            a2 = (a1 + 90.0) % 360.0
            if not os.path.exists(os.path.join(datasets[0]['directory'], '%s_%0.1f.png' % (prefix, a1))):
                _logger.info('Taking snapshots of crystal at %0.1f and %0.1f' % (a1, a2))
                snapshot.take_sample_snapshots(
                    prefix, os.path.join(datasets[0]['directory']), [a2, a1], decorate=True
                )

        # Prepare directory
        self.beamline.image_server.set_user(*self.config['user_properties'])

        self.beamline.goniometer.set_mode('COLLECT', wait=True)
        current_attenuation = self.beamline.attenuator.get()
        gobject.idle_add(self.emit, 'started')

        try:
            self.beamline.exposure_shutter.close()
            self.count = 0

            first_frame = True
            for wedge in wedges:
                # setup devices
                if abs(self.beamline.energy.get_position() - wedge['energy']) >= 0.0005:
                    self.beamline.energy.move_to(wedge['energy'], wait=True)

                if abs(self.beamline.diffractometer.distance.get_position() - wedge['distance']) >= 0.1:
                    self.beamline.diffractometer.distance.move_to(wedge['distance'], wait=True)

                if abs(self.beamline.attenuator.get() - wedge['attenuation']) >= 25:
                    self.beamline.attenuator.set(wedge['attenuation'], wait=True)

                # setup folder for wedge
                self.beamline.image_server.setup_folder(wedge['directory'])

                for frame in runlists.generate_frame_list(wedge):
                    if self.paused:
                        gobject.idle_add(self.emit, 'paused', True, {})
                        while self.paused and not self.stopped:
                            time.sleep(0.05)
                        self.beamline.goniometer.set_mode('COLLECT', wait=True)
                        gobject.idle_add(self.emit, 'paused', False, {})
                    if self.stopped:
                        _logger.info("Stopping Collection ...")
                        break

                    if frame['saved'] and skip_existing:
                        _logger.info('Skipping %s' % frame['frame_name'])
                        # self.notify_progress(self.STATE_SKIPPED)
                        continue
                    elif frame['saved']:
                        _logger.info('Overwriting %s' % frame['frame_name'])
                        os.remove(
                            "{}/{}.{}".format(frame['directory'], frame['frame_name'],
                                              self.beamline.detector.file_extension)
                        )
                    self.notify_progress(self.STATE_RUNNING)

                    # Prepare image header
                    header = {
                        'delta_angle': frame['delta_angle'],
                        'filename': '{}.{}'.format(frame['frame_name'], self.beamline.detector.file_extension),
                        'directory': os.path.sep.join(
                            ['', 'data'] + frame['directory'].split(os.path.sep)[2:]
                        ) if frame['directory'].startswith('/users') else frame['directory'],
                        'distance': frame['distance'],
                        'exposure_time': frame['exposure_time'],
                        'frame_number': frame['frame_number'],
                        'wavelength': energy_to_wavelength(frame['energy']),
                        'energy': frame['energy'],
                        'frame_name': frame['frame_name'],
                        'start_angle': frame['start_angle'],
                        'comments': 'BEAMLINE: %s %s' % ('CLS', self.beamline.name),
                    }

                    # prepare goniometer for scan
                    self.beamline.goniometer.configure(
                        time=frame['exposure_time'], delta=frame['delta_angle'], angle=frame['start_angle']
                    )
                    if frame.get('dafs', False):
                        self.beamline.i_0.async_count(frame['exposure_time'])
                    self.beamline.detector.start(first=first_frame)
                    self.beamline.goniometer.scan(wait=False)
                    self.beamline.detector.set_parameters(header)
                    self.beamline.goniometer.wait(start=False, stop=True, timeout=frame['exposure_time'] * 4)
                    self.beamline.detector.save()
                    if frame.get('dafs', False):
                        _logger.info('DAFS I0  %s\t%s' % (frame['frame_name'], self.beamline.i_0.avg_value))

                    first_frame = False

                    _logger.info("Image Collected: %s" % (header['filename']))
                    gobject.idle_add(
                        self.emit, 'new-image', self.count, "{}/{}".format(frame['directory'], header['filename'])
                    )

                    self.notify_progress(self.STATE_DONE)
                    self.count += 1

            # Wait for Last image to be transfered (only if dataset is to be uploaded to MxLIVE)
            if self.count >= 4:
                time.sleep(5.0)

            self.results = self.get_dataset_info(datasets)
            if not self.stopped:
                gobject.idle_add(self.emit, 'done')
            else:
                gobject.idle_add(self.emit, 'stopped')
            self.stopped = True
        finally:
            self.beamline.exposure_shutter.close()
            # Restore attenuation
            self.beamline.attenuator.set(current_attenuation)
            self.beamline.lock.release()
        return self.results

    def run_shutterless(self):
        ca.threads_init()
        self.beamline.lock.acquire()

        skip_existing = self.config['skip_existing']
        datasets = self.config['datasets']
        wedges = self.config['wedges']

        # Calcualte total work
        self.total_frames = sum([wedge['num_frames'] for wedge in wedges])

        # Take snapshots before beginning collection
        if self.config['take_snapshots']:
            name = os.path.commonprefix([dataset['name'] for dataset in datasets])
            prefix = '%s-pic' % (name)
            a1 = datasets[0]['start_angle']
            a2 = (a1 + 90.0) % 360.0
            if not os.path.exists(os.path.join(datasets[0]['directory'], '%s_%0.1f.png' % (prefix, a1))):
                _logger.info('Taking snapshots of crystal at %0.1f and %0.1f' % (a1, a2))
                snapshot.take_sample_snapshots(
                    prefix, os.path.join(datasets[0]['directory']), [a2, a1], decorate=True
                )

        # Configure user parameters
        self.beamline.image_server.set_user(*self.config['user_properties'])

        self.beamline.goniometer.set_mode('COLLECT', wait=True)
        current_attenuation = self.beamline.attenuator.get()
        gobject.idle_add(self.emit, 'started')

        try:
            self.beamline.exposure_shutter.close()
            self.count = 0

            first_frame = True
            for wedge in wedges:
                # setup devices
                if abs(self.beamline.energy.get_position() - wedge['energy']) >= 0.0005:
                    self.beamline.energy.move_to(wedge['energy'], wait=True)

                if abs(self.beamline.diffractometer.distance.get_position() - wedge['distance']) >= 0.1:
                    self.beamline.diffractometer.distance.move_to(wedge['distance'], wait=True)

                if abs(self.beamline.attenuator.get() - wedge['attenuation']) >= 25:
                    self.beamline.attenuator.set(wedge['attenuation'], wait=True)
                name = wedge['file_template'] % wedge['start_frame']
                detector_parameters = {
                    'file_template': '{}.{}'.format(name, self.beamline.detector.file_extension),
                    'directory': wedge['directory'],
                    'wavelength': energy_to_wavelength(wedge['energy']),
                    'energy': wedge['energy'],
                    'distance': wedge['distance'],
                    'two_theta': wedge['two_theta'],
                    'exposure_time': wedge['exposure_time'],
                    'num_frames': wedge['num_frames'],
                    'start_angle': wedge['start_angle'],
                    'delta_angle': wedge['delta_angle'],
                    'comments': 'BEAMLINE: %s %s' % ('CLS', self.beamline.name),
                }
                # prepare goniometer for scan
                self.beamline.goniometer.configure(
                    time=wedge['exposure_time'] * wedge['num_frames'],
                    delta=wedge['delta_angle'] * wedge['num_frames'],
                    angle=wedge['start_angle']
                )

                self.beamline.detector.set_parameters(detector_parameters)
                self.beamline.detector.start(first=first_frame)
                self.beamline.goniometer.scan(wait=False)

                self.beamline.goniometer.wait(
                    start=False, stop=True, timeout=wedge['exposure_time'] * wedge['num_frames'] * 2
                )
                self.count += wedge['num_frames']

                _logger.info("Set of %d Images Collected: %s" % (wedge['num_frames'], name))
                gobject.idle_add(
                    self.emit, 'new-image', self.count,
                    "{}/{}".format(wedge['directory'], detector_parameters['file_template'])
                )

            # Wait for Last image to be transfered (only if dataset is to be uploaded to MxLIVE)
            if self.count >= 4:
                time.sleep(5.0)

            self.results = self.get_dataset_info(datasets)
            if not self.stopped:
                gobject.idle_add(self.emit, 'done')
            else:
                gobject.idle_add(self.emit, 'stopped')
            self.stopped = True
        finally:
            self.beamline.exposure_shutter.close()
            # Restore attenuation
            self.beamline.attenuator.set(current_attenuation)
            self.beamline.lock.release()
        return self.results

    def on_beam_change(self, obj, beam_available):
        if not beam_available and (not self.paused) and (not self.stopped):
            self.pause()
            pause_dict = {
                'type': Screener.PAUSE_BEAM,
                'collector': True,
                'position': self.count - 1
            }
            gobject.idle_add(self.emit, 'paused', True, pause_dict)
        return True

    def notify_progress(self, status):
        fraction = float(self.count + 1) / self.total_frames
        gobject.idle_add(self.emit, 'progress', fraction, status)

    def get_dataset_info(self, data_list):
        results = []
        for d in data_list:
            data = d.copy()

            if len(data['frame_sets']) == 0:
                continue
            if len(data['frame_sets'][0]) < 2:
                continue

            data['id'] = None
            data['frame_sets'], data['num_frames'] = runlists.get_disk_frameset(
                data['directory'],
                '{}_*.{}'.format(data['name'], self.beamline.detector.file_extension),
            )
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
                data['crystal_id'] = data.get('crystal_id') if not old_data.get('crystal_id') else old_data[
                    'crystal_id']
                data['experiment_id'] = data.get('experiment_id') if not old_data.get('experiment_id') else old_data[
                    'experiment_id']

            with open(filename, 'w') as fobj:
                json.dump(data, fobj, indent=4)
            results.append(data)
        return results

    def set_position(self, pos):
        for i, frame in enumerate(self.run_list):
            if i < pos and len(self.run_list) > pos:
                frame['saved'] = True
            else:
                frame['saved'] = False
        self.pos = pos

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.stopped = True


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

    def configure(self, run_list):
        # associate beamline devices
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)

        except:
            self.beamline = None
            _logger.warning('No registered beamline found.')
            raise
        try:
            self.data_collector = globalRegistry.lookup([], IDataCollector, 'mxdc.screening')
        except:
            if self.data_collector is None:
                self.data_collector = DataCollector()
        try:
            self.data_collector.disconnect(self.collect_connect)
        except:
            pass
        self.collect_connect = self.data_collector.connect('paused', self.on_collector_pause)
        self.run_list = run_list
        self.total_items = len(self.run_list)
        return

    def on_collector_pause(self, obj, state, pause_dict):
        task = self.run_list[self.pos]
        if task.task_type == Screener.TASK_COLLECT and (not self.paused) and (not self.stopped) and (
                    'collector' in pause_dict):
            self.paused = True
            gobject.idle_add(self.emit, 'paused', True, pause_dict)
        return True

    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Screener')
        worker_thread.start()

    def notify_progress(self, status):
        # Notify progress
        if status == self.TASK_STATE_DONE:
            fraction = float(self.pos + 1) / self.total_items
        else:
            fraction = float(self.pos) / self.total_items
        gobject.idle_add(self.emit, 'progress', fraction, self.pos, status)

    def run(self):
        self.paused = False
        self.stopped = False
        if self.beamline is None:
            _logger.error('No Beamline found. Aborting Screening.')
            return
        ca.threads_init()
        # self.beamline.lock.acquire()
        gobject.idle_add(self.emit, 'started')
        try:
            self.pos = 0
            pause_dict = {}

            while self.pos < len(self.run_list):
                task = self.run_list[self.pos]
                _logger.debug('TASK: "%s"' % str(task))

                # Making sure beam is available before trying to collect
                if (
                            self.last_pause != Screener.PAUSE_BEAM) and task.task_type == Screener.TASK_COLLECT and not self.beamline.storage_ring.beam_state and not self.paused:
                    self.pause()
                    pause_dict = {'type': Screener.PAUSE_BEAM,
                                  'object': None}

                if self.stopped:
                    gobject.idle_add(self.emit, 'stopped')
                    break
                if self.paused:
                    gobject.idle_add(self.emit, 'paused', True, pause_dict)
                    self.last_pause = pause_dict.get('type', None)
                    pause_dict = {}
                    while self.paused and not self.stopped:
                        time.sleep(0.05)
                    gobject.idle_add(self.emit, 'paused', False, pause_dict)
                    continue

                # Perform the screening task here
                if task.task_type == Screener.TASK_PAUSE:
                    self.pause()
                    self.notify_progress(Screener.TASK_STATE_DONE)
                    pause_dict = {'type': Screener.PAUSE_TASK,
                                  'task': self.run_list[self.pos - 1].name,
                                  'sample': self.run_list[self.pos]['sample']['name'],
                                  'port': self.run_list[self.pos]['sample']['port']}

                elif task.task_type == Screener.TASK_MOUNT:
                    _logger.warn('TASK: Mount "%s"' % task['sample']['port'])
                    if self.beamline.automounter.is_mounted(task['sample']['port']):
                        # do nothing
                        self.notify_progress(Screener.TASK_STATE_SKIPPED)
                    elif self.beamline.automounter.is_mountable(task['sample']['port']):
                        self.notify_progress(Screener.TASK_STATE_RUNNING)
                        success = auto.auto_mount_manual(self.beamline, task['sample']['port'])
                        mounted_info = self.beamline.automounter.mounted_state
                        if not success or mounted_info is None:
                            self.pause()
                            self.stop()
                            pause_dict = {'type': Screener.PAUSE_MOUNT,
                                          'task': self.run_list[self.pos - 1].name,
                                          'sample': self.run_list[self.pos]['sample']['name'],
                                          'port': self.run_list[self.pos]['sample']['port']}
                            self.notify_progress(Screener.TASK_STATE_ERROR)
                        else:
                            port, barcode = mounted_info
                            if port != self.run_list[self.pos]['sample']['port']:
                                gobject.idle_add(self.emit, 'sync', False,
                                                 'Port mismatch. Expected %s.' % self.run_list[self.pos]['sample'][
                                                     'port'])
                            elif barcode != self.run_list[self.pos]['sample']['barcode']:
                                gobject.idle_add(self.emit, 'sync', False,
                                                 'Barcode mismatch. Expected %s.' % self.run_list[self.pos]['sample'][
                                                     'barcode'])
                            else:
                                gobject.idle_add(self.emit, 'sync', True, '')
                            self.notify_progress(Screener.TASK_STATE_DONE)
                    else:
                        # "skip mounting"
                        _logger.warn('Skipping sample: "%s @ %s". Sample port is not mountable!' % (
                            task['sample']['name'], task['sample']['port']))
                        self.notify_progress(Screener.TASK_STATE_SKIPPED)
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
                            pause_dict = {'type': Screener.PAUSE_ALIGN,
                                          'task': self.run_list[self.pos - 1].name,
                                          'sample': self.run_list[self.pos]['sample']['name'],
                                          'port': self.run_list[self.pos]['sample']['port']}
                            self.pause()
                            self.notify_progress(Screener.TASK_STATE_ERROR)
                        elif _out < 70:
                            pause_dict = {'type': Screener.PAUSE_UNRELIABLE,
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
                        self.beamline.cryojet.nozzle.close()
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
                        self.data_collector.configure(params, skip_existing=False, take_snapshots=False)
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
                            frame_list = runlists.frameset_to_list(collect_results[0]['frame_sets'])
                            _first_frame = os.path.join(collect_results[0]['directory'],
                                                        "%s_%04d.img" % (collect_results[0]['name'], frame_list[0]))
                            _a_params = {'directory': os.path.join(task['directory'], task['sample']['name'], 'scrn'),
                                         'info': {'anomalous': False,
                                                  'file_names': [_first_frame, ]
                                                  },
                                         'type': 'SCRN',
                                         'crystal': task.options['sample'],
                                         'name': collect_results[0]['name']}

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

                self.pos += 1

            gobject.idle_add(self.emit, 'done')
            self.stopped = True
        finally:
            self.beamline.exposure_shutter.close()
            # self.beamline.lock.release()

    def set_position(self, pos):
        self.pos = pos

    def pause(self):
        self.paused = True
        self.data_collector.pause()

    def resume(self):
        if self.last_pause is Screener.PAUSE_BEAM and self.beamline.storage_ring.beam_state:
            self.last_pause = None
        self.paused = False
        self.data_collector.resume()

    def stop(self):
        self.stopped = True
        self.data_collector.stop()
