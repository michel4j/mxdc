import time
import uuid

from mxdc import Registry, Signal, Engine
from mxdc.engines import centering, auto
from mxdc.engines.interfaces import IDataCollector
from mxdc.utils import datatools
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class Automator(Engine):
    TaskNames = ('Mount', 'Center', 'Pause', 'Acquire', 'Analyse', 'Dismount')

    class Task:
        (MOUNT, CENTER, PAUSE, ACQUIRE, ANALYSE, DISMOUNT) = list(range(6))

    class Signals:
        sample_done = Signal('sample-done', arg_types=(str,))
        sample_started = Signal('sample-started', arg_types=(str,))

    def __init__(self):
        super().__init__()
        self.pause_message = ''
        self.total = 1

        self.collector = Registry.get_utility(IDataCollector)
        self.centering = centering.Centering()

    def configure(self, samples, tasks):
        self.samples = samples
        self.tasks = tasks
        self.total = len(tasks) * len(samples)

    def get_progress(self, pos, task, sample):
        fraction = float(pos) / self.total
        msg = '{}: {}/{}'.format(self.TaskNames[task['type']], sample['group'], sample['name'])
        return fraction, msg

    def run(self):
        self.set_state(busy=True, started=None)
        pos = 0
        self.pause_message = ''
        for sample in self.samples:
            if self.stopped: break
            self.emit('sample-started', sample['uuid'])
            for task in self.tasks:
                if self.paused:
                    self.intervene()
                if self.stopped: break
                pos += 1
                self.emit('progress', *self.get_progress(pos, task, sample))
                logger.info(
                    'Sample: {}/{}, Task: {}'.format(sample['group'], sample['name'], self.TaskNames[task['type']])
                )

                if task['type'] == self.Task.PAUSE:
                    self.intervene(
                        'As requested, automation has been paused for manual intervention. \n'
                        'Please resume after intervening to continue the sequence. '
                    )
                elif task['type'] == self.Task.CENTER:
                    if self.beamline.automounter.is_mounted(sample['port']):
                        method = task['options'].get('method')
                        self.centering.configure(method=method)
                        self.centering.run()
                        if self.centering.score < 0.5:
                            self.intervene(
                                'Not confident about the centering, automation has been paused\n'
                                'Please resume after manual centering. '
                            )
                    else:
                        self.emit('error', 'Sample not mounted. Aborting!')
                        self.stop()

                elif task['type'] == self.Task.MOUNT:
                    success = auto.auto_mount_manual(self.beamline, sample['port'])
                    if success and self.beamline.automounter.is_mounted(sample['port']):
                        mounted = self.beamline.automounter.get_state("sample")
                        barcode = mounted.get('barcode')
                        if sample['barcode'] and barcode and barcode != sample['barcode']:
                            logger.error('Barcode mismatch: {} vs {}'.format(barcode, sample['barcode']))
                    else:
                        logger.debug('Success: {}, Mounted: {}'.format(
                            success, self.beamline.automounter.is_mounted(sample['port'])
                        ))
                        self.emit('error', 'Mouting Failed. Unable to continue automation!')
                        self.stop()
                elif task['type'] == self.Task.ACQUIRE:
                    if self.beamline.automounter.is_mounted(sample['port']):
                        params = {}
                        params.update(task['options'])
                        params.update({'name': sample['name'], 'uuid': str(uuid.uuid4())})
                        params = datatools.update_for_sample(params, sample)
                        logger.debug('Acquiring frames for sample {}, in directory {}.'.format(
                            sample['name'], params['directory']
                        ))

                        self.collector.configure(
                            [params], take_snapshots=True, analysis=params.get('analysis'),
                            anomalous=params.get('anomalous', False)
                        )
                        sample['results'] = self.collector.execute()

                    else:
                        self.emit('error', 'Sample not mounted. Unable to continue automation!')
                        self.stop()

            self.emit('sample-done', sample['uuid'])

        if self.stopped:
            self.set_state(stopped=None, busy=False)
            logger.info('Automation stopped')

        if not self.stopped:
            auto.auto_dismount_manual(self.beamline)
            self.set_state(done=None, busy=False)
            logger.info('Automation complete')

    def intervene(self, message=''):
        self.pause(message)
        while self.paused and not self.stopped:
            time.sleep(0.1)
        self.resume()

    def resume(self):
        super().resume()
        self.collector.resume()

    def stop(self, error=''):
        self.collector.stop()
        super().stop()
