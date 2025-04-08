import time
import uuid
from enum import IntEnum
from pathlib import Path
from typing import Any

from mxdc import Registry, Signal, Engine
from mxdc.engines import centering, transfer
from mxdc.engines.interfaces import IDataCollector, IAnalyst
from mxdc.utils import datatools, misc, scitools
from mxdc.utils.decorators import async_call
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class TaskState:
    position: int

    def __init__(self, master, sample_code, position, tasks, total):
        self.master = master
        self.position = position
        self.uuid = sample_code
        self.total = total
        self.count = len(tasks)
        self.tasks = tasks
        self.states = {}
        self.results = {}
        self.skipped = False

    def set_state(self, task_id, code):
        self.states[task_id] = code
        self.master.emit('task-progress', self.progress(), self.uuid, self.text())

    def wait_for(self, task_id, timeout=60):
        start = time.time()
        while time.time() - start < timeout:
            if task_id in self.states.keys() and self.states[task_id] == 'S':
                return True
            time.sleep(0.1)

    def get_result(self, task_id):
        return self.results.get(task_id, {})

    def start(self, task_id: str):
        self.set_state(task_id, '>')
        return task_id

    def previous(self, task_type: datatools.TaskType = None, task_id: str = None):
        history = []
        for t, task in zip(self.states.keys(), self.tasks):
            type_ = task['type']
            if t == task_id:
                break
            history.append((t, type_))

        for t, type_ in reversed(history):
            if type_ == task_type or task_type is None:
                return t

    def succeed(self, task_id, results):
        self.results[task_id] = results
        self.set_state(task_id, 'S')
        return task_id

    def fail(self, task_id):
        self.set_state(task_id, 'F')
        return task_id

    def defer(self, task_id):
        self.set_state(task_id, '_')
        return task_id

    def skip(self):
        self.skipped = True
        self.master.emit('task-progress', self.progress(), self.uuid, self.text())

    def text(self):
        rest = '_' if not self.skipped else 'F'
        state_txt = ''.join(self.states.values())
        return state_txt + rest * (self.count - len(state_txt))

    def progress(self):
        state_txt = self.text()
        state_prog = self.count - state_txt.count('_') - 0.5 * state_txt.count('>')
        total_prog = self.position * self.count + state_prog
        return total_prog / max(self.total, 1)


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
        self.analyst = Registry.get_utility(IAnalyst)
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

    def on_dataset_ready(self, collector, data_id, meta_data):
        logger.info(f'Dataset ready: {data_id}')
        if data_id in self.processing_queue:

            logger.critical(f'Processing data: {data_id}')
            params = self.processing_queue.pop(data_id)

            options = params['options']
            sample = params['sample']
            states = params['states']
            task_id = options['uuid']

            states.start(task_id)
            method = options.get('method', 'process')
            flags = ('anomalous',) if options.get('anomalous') else ()
            if method == 'process':
                res = self.analyst.process_dataset(*meta_data, flags=flags, sample=sample)
            elif method == 'strategy':
                res = self.analyst.screen_dataset(*meta_data, flags=flags, sample=sample)
            elif method == 'powder':
                res = self.analyst.process_powder(*meta_data, flags=flags, sample=sample)
            else:
                logger.error(f'Unknown method: {method}')
                return
            res.connect('done', self.on_analysis_done, states, task_id)
            res.connect('failed', self.on_analysis_failed, states, task_id)

    @staticmethod
    def on_analysis_done(response, results, states, task_id):
        states.succeed(task_id, results)
        logger.info(f'Analysis done: {task_id}')

    @staticmethod
    def on_analysis_failed(response, results, states, task_id):
        states.fail(task_id)
        logger.info(f'Analysis failed: {task_id}')

    def update_strategy(self, strategy: dict, options: dict) -> dict:
        """
        Apply acquisition strategy to options and return an updated options
        :param strategy: strategy dictionary
        :param options: options dictionary
        :return: updated options dictionary
        """
        if strategy:
            default_rate = options['delta'] / options['exposure']
            exposure_rate = strategy.get('exposure_rate_worst', default_rate)
            delta = scitools.nearest(min(strategy.get('max_delta'), options['delta']), 0.1)
            min_exposure = self.beamline.config.dataset.exposure
            run = {
                'attenuation': strategy.get('attenuation', 0.0),
                'start': strategy.get('start_angle', 0.0),
                'range': max(strategy.get('total_range', 180.0), options['range']),
                'resolution': strategy.get('resolution', 2.0),
                'exposure': max(min_exposure, scitools.nearest(delta / exposure_rate, min_exposure)),
                'delta': delta,
            }
            options.update(run)
        return options

    @async_call
    def request_prefetch(self, position: int):
        """
        Prefetch the next sample
        :param position: the current sample position
        """

        next_sample = None if position >= len(self.samples) else self.samples[position + 1]
        if next_sample:
            logger.debug(f'Prefetching next sample ... {next_sample["port"]}')
            self.beamline.automounter.prefetch(next_sample['port'], wait=True)

    def mount_task(self, task, sample, states: TaskState) -> tuple[ResultType, Any]:
        options = self.prepare_task_options(task, sample, activity='centering')
        states.start(options['uuid'])
        success = self.beamline.automounter.mount(sample['port'], wait=True)

        if success and self.beamline.automounter.is_mounted(sample['port']):
            mounted = self.beamline.automounter.get_state("sample")
            barcode = mounted.get('barcode')
            if sample['barcode'] and barcode and barcode != sample['barcode']:
                logger.warning(f'Barcode mismatch: {barcode} vs {sample["barcode"]}')

            self.request_prefetch(states.position)
            return self.ResultType.SUCCESS, states.succeed(options['uuid'], mounted)
        else:
            logger.warning(f'Success: {success}, Mounted: {self.beamline.automounter.is_mounted(sample["port"])}')
            return self.ResultType.FAILED, states.fail(options['uuid'])

    def center_task(self, task, sample, states: TaskState) -> tuple[ResultType, Any]:
        options = self.prepare_task_options(task, sample, activity='centering')
        states.start(options['uuid'])
        method = options.get('method', 'loop')
        self.centering.configure(method=method, directory=options['directory'], name=sample['name'])
        self.beamline.manager.wait('CENTER')
        time.sleep(2)  # needed to make sure gonio is in the right state
        results = self.centering.run()
        logger.info(f'Centering Score: {self.centering.score:0.1f}')
        if self.centering.score < options.get('min_score', 50):
            return self.ResultType.FAILED, states.fail(options['uuid'])
        return self.ResultType.SUCCESS, states.succeed(options['uuid'], results)

    def acquire_task(self, task, sample, states: TaskState) -> tuple[ResultType, Any]:
        options = self.prepare_task_options(task, sample)
        states.start(options['uuid'])
        if task['type'] == self.Task.ACQUIRE and options.get('use_strategy', False):
            strategy_task = states.previous(task_type=self.Task.ANALYSE)
            self.emit('message', f'{task["name"]}: {sample["group"]}/{sample["name"]} - Waiting for strategy ...')
            logger.info(f'Waiting for strategy: {strategy_task} ...')
            found = states.wait_for(strategy_task, timeout=60)
            if found:
                results = states.get_result(strategy_task)
                strategy = results.get('strategy', {})
                options = self.update_strategy(strategy, options)
                logger.info(f'Data acquisition strategy updated!')
            else:
                logger.error('Strategy not found! Proceeding with default settings ...')
        self.emit('message', f'{task["name"]}: {sample["group"]}/{sample["name"]} - Acquiring ...')
        self.collector.configure([options], take_snapshots=True, analysis=None)
        results = self.collector.execute()
        return self.ResultType.SUCCESS, states.succeed(options['uuid'], results)

    def analyse_task(self, task, sample, states: TaskState) -> tuple[ResultType, Any]:
        options = self.prepare_task_options(task, sample, activity='process')
        states.start(options['uuid'])

        # we assume the previous task is the acquisition task we want to analyse
        target_acquisition = states.previous(task_id=options['uuid'])
        self.processing_queue[target_acquisition] = {
            'task': task, 'sample': sample, 'states': states, 'options': options
        }
        logger.critical(f'Queueing processing for data: {target_acquisition}')
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
        return success in [self.ResultType.SUCCESS, self.ResultType.ASYNC]

    def run(self):
        """
        Run the automation sequence
        :return:
        """
        self.set_state(busy=True, started=None)
        self.pause_message = ''

        for j, sample in enumerate(self.samples):
            if self.stopped:
                break

            task_states = TaskState(self, sample['uuid'], j, self.tasks, self.total)
            for i, task in enumerate(self.tasks):
                logger.info(f'Sample: {sample["group"]}/{sample["name"]}, Task: {task["name"]}')
                success = self.execute_task(task, sample, task_states)
                if not success:
                    if task['options'].get('skip_on_failure', False):
                        task_states.skip()
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
            self.beamline.automounter.dismount(wait=True)
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
