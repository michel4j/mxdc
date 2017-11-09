import threading
import time
import uuid

from gi.repository import GObject
from twisted.python.components import globalRegistry

from mxdc.beamlines.interfaces import IBeamline
from mxdc.com import ca
from mxdc.engines import centering, auto
from mxdc.engines.interfaces import IDataCollector
from mxdc.utils import datatools
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)

class Automator(GObject.GObject):
    class Task:
        (MOUNT, CENTER, PAUSE, ACQUIRE, ANALYSE, DISMOUNT) = range(6)

    TaskNames = ('Mount', 'Center', 'Pause', 'Acquire', 'Analyse', 'Dismount')

    __gsignals__ = {
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
        self.centering = centering.Centering()

    def configure(self, samples, tasks):
        self.samples = samples
        self.tasks = tasks
        self.total = len(tasks) * len(samples)

    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Automation')
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
                        self.centering.configure(method=method)
                        self.centering.run()
                    else:
                        self.stop(error='Sample not mounted. Unable to continue automation!')

                elif task['type'] == self.Task.MOUNT:
                    success = auto.auto_mount_manual(self.beamline, sample['port'])
                    if success and self.beamline.automounter.is_mounted(sample['port']):
                        barcode = self.beamline.automounter.sample.get('barcode')
                        if sample['barcode'] and barcode and barcode != sample['barcode']:
                            logger.error('Barcode mismatch: {} vs {}'.format(barcode, sample['barcode']))
                    else:
                        logger.debug('Success: {}, Mounted: {}'.format(
                            success, self.beamline.automounter.is_mounted(sample['port'])
                        ))
                        self.stop(error='Mouting Failed. Unable to continue automation!')
                elif task['type'] == self.Task.ACQUIRE:
                    if self.beamline.automounter.is_mounted(sample['port']):
                        params = {}
                        params.update(task['options'])
                        params.update({'name': sample['name'], 'uuid': str(uuid.uuid4())})
                        params = datatools.update_for_sample(params, sample)
                        logger.debug('Acquiring frames for sample {}, in directory {}.'.format(
                            sample['name'], params['directory']
                        ))

                        self.collector.configure(params, take_snapshots=True, analysis=params.get('analysis'))
                        sample['results'] = self.collector.run()
                        while not self.collector.complete:
                            time.sleep(1)  # wait until collector is stopped
                    else:
                        self.stop(error='Sample not mounted. Unable to continue automation!')

            GObject.idle_add(self.emit, 'sample-done', sample['uuid'])

        if self.stopped:
            GObject.idle_add(self.emit, 'stopped')
            logger.info('Automation stopped')

        if not self.stopped:
            auto.auto_dismount_manual(self.beamline)
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