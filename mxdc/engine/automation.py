import threading
import time

from mxdc.com import ca
from mxdc.engine import centering, auto
from gi.repository import GObject
from mxdc.interface.beamlines import IBeamline
from mxdc.interface.engines import IDataCollector
from twisted.python.components import globalRegistry
from mxdc.utils import datatools
from mxdc.utils.log import get_module_logger


logger = get_module_logger(__name__)

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
                logger.info(
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
                        params = {'name': sample['name']}
                        params.update(task['options'])
                        params = datatools.update_for_sample(params, sample)
                        logger.debug('Acquiring frames for sample {}, in directory {}.'.format(
                            sample['name'], params['directory']
                        ))
                        self.collector.configure(params, take_snapshots=True)
                        sample['results'] = self.collector.run()
                    else:
                        self.stop(error='Sample not mounted. Unable to continue automation!')

                elif task['type'] == Automator.Task.ANALYSE:
                    if sample.get('results') is not None:
                        params = {}
                        params.update(task['options'])
                        params = datatools.update_for_sample(params, sample)
                        GObject.idle_add(self.emit, 'analysis-request', params)
                    else:
                        self.stop(error='Data not available. Unable to continue automation!')
            GObject.idle_add(self.emit, 'sample-done', sample['uuid'])

        if self.stopped:
            GObject.idle_add(self.emit, 'stopped')
            logger.info('Automation stopped')

        if not self.stopped:
            if self.beamline.automounter.is_mounted():
                port, barcode = self.beamline.automounter.mounted_state
                auto.auto_dismount_manual(self.beamline, port)
            GObject.idle_add(self.emit, 'done')
            logger.info('Automation complete')

    def pause(self, message=''):
        if message:
            logger.warn(message)
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
            logger.error(error)
            GObject.idle_add(self.emit, 'error', error)