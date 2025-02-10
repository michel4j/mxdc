import os
import time
import uuid
from pathlib import Path

from mxdc import Registry, Signal, Engine
from mxdc.engines import centering, transfer
from mxdc.engines.interfaces import IDataCollector
from mxdc.utils import datatools, misc
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class Automator(Engine):
    TaskNames = ('Mount', 'Center', 'Pause', 'Acquire', 'Analyse', 'Dismount')

    class Task:
        (MOUNT, CENTER, PAUSE, ACQUIRE, ANALYSE, DISMOUNT) = list(range(6))

    samples: list
    tasks: list
    unattended: bool

    class Signals:
        sample_done = Signal('sample-done', arg_types=(str,))
        sample_failed = Signal('sample-failed', arg_types=(str,))
        sample_started = Signal('sample-started', arg_types=(str,))

    def __init__(self):
        super().__init__()
        self.pause_message = ''
        self.total = 1
        self.unattended = False
        self.collector = Registry.get_utility(IDataCollector)
        self.centering = centering.Centering()

    def configure(self, samples, tasks):
        self.samples = samples
        self.tasks = tasks
        self.total = len(tasks) * len(samples)
        self.unattended = self.beamline.config.automation.unattended

    def get_progress(self, pos, task, sample):
        fraction = float(pos) / self.total
        msg = '{}: {}/{}'.format(self.TaskNames[task['type']], sample['group'], sample['name'])
        return fraction, msg

    def take_snapshot(self, directory: str, name: str, index: int = 0):
        # setup folder
        self.beamline.dss.setup_folder(directory, misc.get_project_name())
        file_path = Path(directory)
        file_name = f"{name}-{index}.png"

        # take snapshot
        if file_path.exists():
            self.beamline.sample_camera.save_frame(file_path / file_name)
            logger.debug(f'Snapshot saved... {file_name}')

    def run(self):
        self.set_state(busy=True, started=None)
        pos = 0
        self.pause_message = ''
        for sample in self.samples:
            if self.stopped:
                break
            self.emit('sample-started', sample['uuid'])

            params = {}
            params.update({'name': sample['name'], 'uuid': str(uuid.uuid4())})
            params = datatools.update_for_sample(params, sample=sample, session=self.beamline.session_key)

            for task in self.tasks:
                if self.paused:
                    self.intervene()
                if self.stopped:
                    break
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
                        params.update(task['options'])
                        self.centering.configure(method=method)
                        self.beamline.manager.wait('CENTER')
                        time.sleep(2)           # needed to make sure gonio is in the right state
                        self.take_snapshot(params['directory'], sample['name'], 0)
                        self.centering.run()
                        if self.centering.score < 0.5:
                            if not self.unattended:
                                self.intervene(
                                    f'Centering Sore: {self.centering.score:0.1f}.\n'
                                    'Not confident about the centering, automation has been paused\n'
                                    'Please resume after manual centering. '
                                )
                            else:
                                logger.error(f'Skipping sample due to poor centering: Sore: {self.centering.score}')
                                self.emit('sample-failed', sample['uuid'])
                                break
                    else:
                        self.emit('sample-failed', sample['uuid'])
                        if not self.unattended:
                            self.emit('error', 'Sample not mounted. Aborting!')
                            self.stop()
                        else:
                            break

                elif task['type'] == self.Task.MOUNT:
                    success = transfer.auto_mount_manual(self.beamline, sample['port'])
                    if success and self.beamline.automounter.is_mounted(sample['port']):
                        mounted = self.beamline.automounter.get_state("sample")
                        barcode = mounted.get('barcode')
                        if sample['barcode'] and barcode and barcode != sample['barcode']:
                            logger.error('Barcode mismatch: {} vs {}'.format(barcode, sample['barcode']))
                    else:
                        logger.debug('Success: {}, Mounted: {}'.format(
                            success, self.beamline.automounter.is_mounted(sample['port'])
                        ))
                        if not self.unattended:
                            self.emit('error', 'Mounting Failed. Unable to continue automation!')
                            self.stop()
                        else:
                            self.emit('sample-failed', sample['uuid'])
                            break
                elif task['type'] == self.Task.ACQUIRE:
                    if self.beamline.automounter.is_mounted(sample['port']):
                        params.update(task['options'])
                        logger.debug('Acquiring frames for sample {}, in directory {}.'.format(
                            sample['name'], params['directory']
                        ))

                        self.collector.configure(
                            [params], take_snapshots=True, analysis=params.get('analysis'),
                            anomalous=params.get('anomalous', False)
                        )
                        sample['results'] = self.collector.execute()

                    else:
                        if not self.unattended:
                            self.emit('error', 'Sample not mounted. Unable to continue automation!')
                            self.stop()
                        else:
                            self.emit('sample-failed', sample['uuid'])
                            break
            else:
                self.emit('sample-done', sample['uuid'])

        if self.stopped:
            self.set_state(stopped=None, busy=False)
            logger.info('Automation stopped')

        if not self.stopped:
            transfer.auto_dismount_manual(self.beamline)
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
