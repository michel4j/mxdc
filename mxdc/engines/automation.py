import time
import uuid
from collections import defaultdict
from enum import IntEnum
from pathlib import Path
from typing import Any

from mxdc import Registry, Signal, Engine
from mxdc.engines import centering, transfer
from mxdc.engines.interfaces import IDataCollector
from mxdc.utils import datatools, misc
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class TaskState:
    def __init__(self, sample_code, position, count, total):
        self.position = position
        self.uuid = sample_code
        self.total = total
        self.count = count
        self.history = {}
        self.results = {}
        self.index = 0
        self.states = []
        self.reset()

    def reset(self):
        self.states = ['_'] * self.count
        self.index = 0
        self.history = {}
        self.results = {}

    def last(self):
        return list(self.history.keys())[-1]

    def succeed(self, task_id, results):
        self.history[task_id] = self.states[self.index] = 'S'
        self.results[task_id] = results
        self.index += 1
        return task_id

    def fail(self, task_id):
        self.history[task_id] = self.states[self.index] = 'F'
        self.index += 1
        return task_id

    def defer(self, task_id):
        self.history[task_id] = self.states[self.index] = '_'
        self.index += 1
        return task_id

    def skip(self):
        self.states = ['*' if x == '_' else x for x in self.states]
        self.index = self.count

    def text(self):
        return ''.join(self.states)

    def progress(self):
        return ((self.count + self.position) + (self.count - self.states.count('_'))) / max(self.total, 1)


class Automator(Engine):
    Task = datatools.TaskType

    class ResultType(IntEnum):
        FAILED = 0
        SUCCESS = 1
        ASYNC = 2

    samples: list
    tasks: list
    unattended: bool

    class Signals:
        message = Signal('message', arg_types=(str,))
        task_progress = Signal('task-progress', arg_types=(float, str, str))

    def __init__(self):
        super().__init__()
        self.pause_message = ''
        self.total = 1
        self.unattended = False
        self.collector = Registry.get_utility(IDataCollector)
        self.centering = centering.Centering()
        self.processing_queue = {}
        self.task_results = {}
        self.task_methods = {
            self.Task.MOUNT: self.mount_task,
            self.Task.CENTER: self.center_task,
            self.Task.ACQUIRE: self.acquire_task,
            self.Task.SCREEN: self.acquire_task,
            self.Task.ANALYSE: self.analyse_task,
        }
        self.collector.connect('dataset-ready', self.on_dataset_ready)

    def configure(self, samples, tasks):
        self.samples = samples
        self.tasks = tasks
        self.total = len(tasks) * len(samples)

    def prepare_task_options(self, task: dict, sample: dict, **kwargs) -> dict:
        """
        Prepare task options, add uuid and name to the options
        :param task: task dictionary
        :param sample: sample dictionary
        :param kwargs: additional keywords to inject to options
        :return: updated options dictionary
        """
        options = {
            'uuid': str(uuid.uuid4()),
            'name': sample['name'],
            **task.get("options", {}), **kwargs
        }
        return datatools.update_for_sample(options, sample, self.beamline.session_key)

    def on_dataset_ready(self, collector, task_id, meta_data):
        logger.info(f'Dataset ready: {task_id}')
        if task_id in self.processing_queue:
            task = self.processing_queue.pop(task_id)
            logger.info(f'Processing task: {task_id}')

    def take_snapshot(self, directory: str, name: str, index: int = 0):
        # setup folder
        self.beamline.dss.setup_folder(directory, misc.get_project_name())
        file_path = Path(directory)
        file_name = f"{name}-{index}.png"

        # take snapshot
        if file_path.exists():
            self.beamline.sample_camera.save_frame(file_path / file_name)
            logger.debug(f'Snapshot saved... {file_name}')
        return file_name

    def mount_task(self, task, sample, states: TaskState) -> tuple[ResultType, Any]:
        options = self.prepare_task_options(task, sample, activity='centering')
        success = transfer.auto_mount_manual(self.beamline, sample['port'])
        if success and self.beamline.automounter.is_mounted(sample['port']):
            mounted = self.beamline.automounter.get_state("sample")
            barcode = mounted.get('barcode')
            if sample['barcode'] and barcode and barcode != sample['barcode']:
                logger.error(f'Barcode mismatch: {barcode} vs {sample["barcode"]}')
            return self.ResultType.SUCCESS, states.succeed(options['uuid'], mounted)
        else:
            logger.debug(f'Success: {success}, Mounted: {self.beamline.automounter.is_mounted(sample["port"])}')
            return self.ResultType.FAILED, states.fail(options['uuid'])

    def center_task(self, task, sample, states: TaskState) -> tuple[ResultType, Any]:
        options = self.prepare_task_options(task, sample, activity='centering')
        method = options.get('method', 'loop')
        self.centering.configure(method=method)
        self.beamline.manager.wait('CENTER')
        time.sleep(2)  # needed to make sure gonio is in the right state
        self.centering.run()
        snapshot_name = self.take_snapshot(options['directory'], sample['name'], 0)
        logger.debug(f'Centering Score: {self.centering.score:0.1f}, Snapshot: {snapshot_name}')

        results = {
            'score': self.centering.score,
            'snapshot': snapshot_name
        }
        if self.centering.score < options.get('min_score', 50):
            return self.ResultType.FAILED, states.fail(options['uuid'])
        return self.ResultType.SUCCESS, states.succeed(options['uuid'], results)

    def acquire_task(self, task, sample, states: TaskState) -> tuple[ResultType, Any]:
        options = self.prepare_task_options(task, sample)
        self.collector.configure([options], take_snapshots=False, analysis=None)
        results = self.collector.execute()
        return self.ResultType.SUCCESS, states.succeed(options['uuid'], results)

    def analyse_task(self, task, sample, states: TaskState) -> tuple[ResultType, Any]:
        options = self.prepare_task_options(task, sample, activity='process')
        self.processing_queue[(states.uuid, states.index)] = {
            'task': task, 'sample': sample, 'states': states, 'options': options
        }
        return self.ResultType.ASYNC, states.defer(options['uuid'])

    def execute_task(self, task, sample, states: TaskState) -> bool:
        """
        Execute a task
        :param task: task information
        :param sample: sample information
        :param states: task progress state
        :return: bool
        """

        self.emit('message', f'{task["name"]}: {sample["group"]}/{sample["name"]}')
        self.emit('task-progress', states.progress(), sample['uuid'], states.text())
        if task['type'] == self.Task.MOUNT:
            success, task_id = self.mount_task(task, sample, states)
        elif task['type'] == self.Task.CENTER:
            success, task_id = self.center_task(task, sample, states)
        elif task['type'] in [self.Task.SCREEN, self.Task.ACQUIRE]:
            success, task_id = self.acquire_task(task, sample, states)
        elif task['type'] == self.Task.ANALYSE:
            success, task_id = self.analyse_task(task, sample, states)
        else:
            success, task_id = self.ResultType.FAILED, None
        self.emit('task-progress', states.progress(), sample['uuid'], states.text())
        return success in [self.ResultType.SUCCESS, self.ResultType.ASYNC]

    @staticmethod
    def skip_rest(i, states):
        for i in range(i + 1, len(states)):
            states[i] = '*'
        return states

    def run(self):
        """
        Run the automation sequence
        :return:
        """
        self.set_state(busy=True, started=None)
        self.pause_message = ''
        num_tasks = len(self.tasks) + 1

        for j, sample in enumerate(self.samples):
            if self.stopped:
                break

            task_states = TaskState(sample['uuid'], j, num_tasks, self.total)
            self.task_results[sample['uuid']] = task_states
            task = {'name': 'Mount', 'type': self.Task.MOUNT, 'options': {}}  # Mount task
            success = self.execute_task(task, sample, task_states)

            if not success:
                task_states.skip()
                self.emit('task-progress', task_states.progress(), sample['uuid'], task_states.text())
                continue

            for i, task in enumerate(self.tasks):
                logger.info(f'Sample: {sample["group"]}/{sample["name"]}, Task: {task["name"]}')
                success = self.execute_task(task, sample, task_states)
                if not success:
                    if task['options'].get('skip_on_failure', False):
                        task_states.skip()
                        self.emit('task-progress', task_states.progress(), sample['uuid'], task_states.text())
                        break
                    elif task['options'].get('pause', False):
                        self.intervene(
                            'As requested, automation has been paused for manual intervention. \n'
                            'Please resume after intervening to continue the sequence. '
                        )
                if self.stopped:
                    break

        if self.stopped:
            self.set_state(stopped=None, busy=False)
            logger.info('Automation stopped')

        else:
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
