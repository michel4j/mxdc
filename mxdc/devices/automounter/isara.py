import time
from typing import Any
from enum import IntFlag, auto, IntEnum

from mxdc.devices.automounter import AutoMounter, State, logger
from mxdc.utils.automounter import Port, Puck

ISARA_DEWAR = {
    '1A': Puck('1A', 0.1667, 1.75 / 13.),
    '2A': Puck('2A', 0.3333, 1.75 / 13.),
    '3A': Puck('3A', 0.5, 1.75 / 13.),
    '4A': Puck('4A', 0.6667, 1.75 / 13.),
    '5A': Puck('5A', 0.8333, 1.75 / 13.),

    '1B': Puck('1B', 0.0833, 3.65 / 13.),
    '2B': Puck('2B', 0.25, 3.65 / 13.),
    '3B': Puck('3B', 0.4167, 3.65 / 13),
    '4B': Puck('4B', 0.5833, 3.65 / 13),
    '5B': Puck('5B', 0.75, 3.65 / 13),
    '6B': Puck('6B', 0.9167, 3.65 / 13),

    '1C': Puck('1C', 0.1667, 5.55 / 13),
    '2C': Puck('2C', 0.3333, 5.55 / 13),
    '3C': Puck('3C', 0.5, 5.55 / 13),
    '4C': Puck('4C', 0.6667, 5.55 / 13),
    '5C': Puck('5C', 0.8333, 5.55 / 13),

    '1D': Puck('1D', 0.0833, 7.45 / 13.),
    '2D': Puck('2D', 0.25, 7.45 / 13),
    '3D': Puck('3D', 0.4167, 7.45 / 13),
    '4D': Puck('4D', 0.5833, 7.45 / 13),
    '5D': Puck('5D', 0.75, 7.45 / 13),
    '6D': Puck('6D', 0.9167, 7.45 / 13),

    '1E': Puck('1E', 0.1667, 9.35 / 13),
    '2E': Puck('2E', 0.3333, 9.35 / 13),
    '3E': Puck('3E', 0.5, 9.35 / 13),
    '4E': Puck('4E', 0.6667, 9.35 / 13),
    '5E': Puck('5E', 0.8333, 9.35 / 13),

    '1F': Puck('1F', 0.4167, 11.25 / 13),
    '2F': Puck('2F', 0.5833, 11.25 / 13),
}


class Error(IntFlag):
    BRAKE_TOGGLED = auto()
    EMERGENCY_STOP = auto()
    COLLISION = auto()
    COMMUNICATION_ERROR = auto()
    WRONG_MENU = auto()
    WRONG_MODE = auto()
    AWAITING_GONIO = auto()
    AWAITING_SAMPLE = auto()
    AWAITING_PUCK = auto()
    AWAITING_FILL = auto()
    AWAITING_LID = auto()
    SAMPLE_MISMATCH = auto()


class StatusType(IntEnum):
    IDLE, WAITING, BUSY, STANDBY, FAULT = range(5)


class HealthType(IntEnum):
    OK = 0
    TIMEOUT = auto()
    SAMPLE = auto()
    COLLISION = auto()
    ERROR = auto()


def chain_monitors(*funcs, **kwargs) -> bool:
    """
    Chain multiple monitors together.  Each monitor will be called in order with the same arguments.
    :param funcs: functions or methods to call, each function should return a boolean to indicate success
    :param kwargs: arguments to pass to each function
    """

    for func in funcs:
        if not func(**kwargs):
            return False
    return True


class ISARAMessages(object):
    @staticmethod
    def trajectory(message):
        return {
            'GETPUT': 'Switching sample ...',
            'GET': 'Dismounting sample ...',
            'PUT': 'Mounting sample ...',
            'DRY': 'Drying gripper ...',
            'SOAK': 'Soaking ...',
            'HOME': 'Going home ...',
        }.get(message.upper().strip(), '')

    @staticmethod
    def errors(flag):
        if flag:
            return Error(flag).name.replace('_', ' ').title()
        else:
            return ''


class AuntISARA(AutoMounter):
    """
    Auto mounter Device for the IRELEC ISARA based on the newer AunISARA python-based EPICS driver.

    :param root: Root name of EPICS process variables
    """
    PUCKS = [
        '',
        '1A', '2A', '3A', '4A', '5A',
        '1B', '2B', '3B', '4B', '5B', '6B',
        '1C', '2C', '3C', '4C', '5C',
        '1D', '2D', '3D', '4D', '5D', '6D',
        '1E', '2E', '3E', '4E', '5E',
        '1F', '2F',
    ]

    def __init__(self, root):
        super().__init__()
        self.name = 'ISARA Auto Mounter'
        self.set_state(layout=ISARA_DEWAR)

        # parameters and commands
        self.next_smpl = self.add_pv(f'{root}:PAR:nextPort')
        self.power_cmd = self.add_pv(f'{root}:CMD:power')
        self.mount_cmd = self.add_pv(f'{root}:CMD:mount')
        self.dismount_cmd = self.add_pv(f'{root}:CMD:dismount')
        self.abort_cmd = self.add_pv(f'{root}:CMD:abort')
        self.reset_cmd = self.add_pv(f'{root}:CMD:reset')
        self.clear_cmd = self.add_pv(f'{root}:CMD:clear')
        self.back_cmd = self.add_pv(f'{root}:CMD:back')
        self.safe_cmd = self.add_pv(f'{root}:CMD:safe')
        self.set_smpl_cmd = self.add_pv(f'{root}:CMD:setDiffSmpl')
        self.prefetch_cmd = self.add_pv(f'{root}:CMD:prefetch')

        # feedback
        self.status_fbk = self.add_pv(f'{root}:STATUS')
        self.power_fbk = self.add_pv(f'{root}:STATE:power')
        self.mode_fbk = self.add_pv(f'{root}:STATE:mode')
        self.cryo_fbk = self.add_pv(f'{root}:INP:cryoLevel')
        self.autofill_fbk = self.add_pv(f'{root}:STATE:autofill')
        self.position_fbk = self.add_pv(f'{root}:STATE:pos')
        self.warning_fbk = self.add_pv(f'{root}:WARNING')
        self.enabled_fbk = self.add_pv(f'{root}:ENABLED')
        self.connected_fbk = self.add_pv(f'{root}:CONNECTED')
        self.message_fbk = self.add_pv(f'{root}:LOG')
        self.health_fbk = self.add_pv(f'{root}:HEALTH')
        self.error_fbk = self.add_pv(f'{root}:STATE:error')
        self.path_fbk = self.add_pv(f'{root}:STATE:path')
        self.mounted_fbk = self.add_pv(f'{root}:STATE:onDiff')
        self.barcode_fbk = self.add_pv(f'{root}:STATE:barcode')
        self.tooled_fbk = self.add_pv(f'{root}:STATE:onTool')
        self.pucks_fbk = self.add_pv(f'{root}:STATE:pucks')
        self.path_fbk = self.add_pv(f'{root}:STATE:path')
        self.sample_detected = self.add_pv(f'{root}:INP:smplOnGonio')

        # handle signals
        self.path_fbk.connect('changed', self.on_message, ISARAMessages.trajectory)
        self.warning_fbk.connect('changed', self.on_warning_message)
        self.pucks_fbk.connect('changed', self.on_pucks_changed)
        self.mounted_fbk.connect('changed', self.on_sample_changed)

        status_pvs = [
            self.status_fbk, self.enabled_fbk, self.connected_fbk, self.autofill_fbk, self.cryo_fbk,
            self.mode_fbk, self.path_fbk, self.position_fbk, self.health_fbk
        ]
        for pv in status_pvs:
            pv.connect('changed', self.on_state_changed)

    def is_mountable(self, port):
        if self.is_valid(port):
            ports = self.get_state('ports')
            return ports.get(port, Port.UNKNOWN) not in [Port.BAD, Port.EMPTY]
        return False

    def is_valid(self, port):
        return port[:2] in self.PUCKS[1:] and 1 <= int(port[2:]) <= 16

    def power_on(self):
        if self.power_fbk.get() == 0:
            self.power_cmd.put(1)

    def clear_prefetch(self):
        logger.warning(f'{self.name}: Switching prefetched sample!')
        self.back_cmd.put(1)
        success = self.wait_while(State.IDLE, timeout=10)
        success |= self.wait_until(State.IDLE, timeout=30)
        return success

    def mount(self, port, wait=True):
        self.power_on()
        enabled = self.wait_until(State.IDLE, State.PREPARING, timeout=240)

        if not enabled:
            logger.warning(f'{self.name}: not ready. command ignored!')
            self.set_state(message="Not ready, command ignored!")
            self.cancel()
            return False
        elif self.is_mounted(port):
            logger.info(f'{self.name}: Sample {port} already mounted.')
            self.set_state(message="Sample already mounted!")
            return True
        elif not self.is_mountable(port):
            logger.info(f'{self.name}: Sample {port} cannot be mounted!')
            self.set_state(message="Port cannot be mounted!")
            return False

        if self.tooled_fbk.get() and self.tooled_fbk.get() != port:
            self.clear_prefetch()

        self.next_smpl.put(port, wait=True)
        self.mount_cmd.put(1, wait=True)

        logger.info(f'{self.name}: Mounting Sample: {port}')
        if wait:
            success = self.wait(states={State.BUSY}, timeout=10)
            if success:
                success &= self.wait_while(State.BUSY, timeout=60)
            if success:
                success &= (self.mounted_fbk.get() == port)

            if not success:
                self.set_state(message='Mounting failed!')
            return success
        return True

    def dismount(self, wait=False):
        self.power_on()
        enabled = self.wait(states={State.IDLE, State.PREPARING}, timeout=240)

        if not enabled:
            logger.warning(f'{self.name}: not ready. command ignored!')
            self.set_state(message="Not ready, command ignored!")
            self.cancel()
            return False
        elif not self.is_mounted():
            logger.info(f'{self.name}: No Sample mounted.')
            self.set_state(message="No Sample mounted!")
            return True

        self.dismount_cmd.put(1)
        logger.info(f'{self.name}: Dismounting sample.')
        if wait:
            success = self.wait(states={State.BUSY}, timeout=10)
            if success:
                success &= self.wait_while(State.BUSY, timeout=60)
            if success:
                success &= (self.mounted_fbk.get() == '')
            if not success:
                self.set_state(message='Dismounting failed!')
            return success
        else:
            return True

    def prefetch(self, port, wait=False):
        enabled = self.wait_until(State.IDLE, State.PREPARING, State.STANDBY, timeout=120)
        if enabled and self.get_state('status') == State.STANDBY:
            self.set_state(message='Prefetch will be executed after current operation.')
            self.wait_while(State.STANDBY, timeout=720)

        if not enabled:
            logger.warning(f'{self.name}: not ready. command ignored!')
            self.set_state(message="Not ready, command ignored!")
            self.cancel()
            return False
        elif self.is_mounted(port):
            logger.info(f'{self.name}: Sample {port} already mounted. Will not prefetch it.')
            self.set_state(message="Sample already mounted!")
            return True
        elif not self.is_mountable(port):
            logger.info(f'{self.name}: Sample {port} cannot be prefetched!')
            self.set_state(message="Port cannot be prefetched!")
            return False

        if self.tooled_fbk.get() and self.tooled_fbk.get() != port:
            self.clear_prefetch()

        if self.tooled_fbk.get():
            logger.warning(f'{self.name}: Sample {self.tooled_fbk.get()} is mounted. Prefetching will be skipped!')
            self.set_state(message='Sample is mounted. Prefetching will be skipped!')
            return False

        logger.info(f'{self.name}: Prefetch Sample: {port}')
        self.next_smpl.put(port, wait=True)
        self.prefetch_cmd.put(1)

        if wait:
            success = self.wait_while(State.IDLE, timeout=30)
            if success:
                success &= self.wait_until(State.IDLE, timeout=30)
            return success
        else:
            return True

    def abort(self):
        self.abort_cmd.put(1)

    def on_pucks_changed(self, obj, states):
        if len(states) == 29:
            pucks = {self.PUCKS[i + 1] for i, bit in enumerate(states) if bit == '1'}
            states = {
                '{}{}'.format(puck, 1 + pin): Port.UNKNOWN for pin in range(16) for puck in pucks
            }
            self.set_state(ports=states)
            self.set_state(containers=pucks)
            self.set_state(health=(0, 'pucks', ''))
        else:
            self.set_state(health=(16, 'pucks', 'Puck detection!'), message='Could not read puck positions!')
            self.set_state(ports={})
            self.set_state(containers=set())

    def on_sample_changed(self, obj, mounted_port):
        # reset state
        sample = self.get_state('sample')
        port = sample.get('port')
        ports = self.get_state('ports')
        if self.is_valid(mounted_port):
            ports[mounted_port] = Port.MOUNTED
            sample = {
                'port': mounted_port,
                'barcode': ''
            }
        else:
            if ports.get(port) == Port.MOUNTED:
                ports[port] = Port.UNKNOWN

            sample = {}
        self.set_state(sample=sample)
        self.set_state(ports=ports)

    def on_state_changed(self, *args):
        raw_status = StatusType(self.status_fbk.get())
        raw_errors = Error(self.error_fbk.get())
        raw_health = HealthType(self.health_fbk.get())
        cur_status = self.get_state('status')

        status = {
            raw_status.IDLE: State.IDLE,
            raw_status.STANDBY: State.STANDBY,
            raw_status.FAULT: State.ERROR,
            raw_status.WAITING: State.BUSY,
            raw_status.BUSY: State.BUSY,
        }.get(raw_status, State.WARNING)

        diagnosis = []
        message = ''
        health = 0

        if not self.connected_fbk.get() or Error.COMMUNICATION_ERROR in raw_errors:
            status = State.ERROR
            diagnosis += ['Controller Disconnected! Staff Needed.']
            health |= 4
        elif not self.enabled_fbk.get() or Error.WRONG_MODE in raw_errors or self.mode_fbk.get() == 0:
            status = State.WARNING
            diagnosis += ['Disabled by staff/Manual Mode']
            health |= 16
        elif status == State.IDLE and cur_status == State.PREPARING:
            status = State.PREPARING

        if raw_health == HealthType.TIMEOUT:
            message = 'Robot timeout!'
        elif raw_health == HealthType.COLLISION:
            health |= 32
            diagnosis += ['Robot collision!']
            status = State.ERROR
        elif raw_health == HealthType.ERROR:
            health |= 32
            diagnosis += ['Robot collision!']
            message = 'Robot Error!'
            status = State.ERROR
        elif raw_health == HealthType.SAMPLE:
            message = 'Sample mismatch. Recovering, please try again!'
        elif raw_health == HealthType.OK:
            message = ''
            health = 0

        if self.get_state('status') != status:
            self.set_state(status=status)
        if message.strip():
            self.set_state(message=message)
        self.set_state(health=(health, 'notices', 'Staff Needed'))

    def on_message(self, obj, value, transform):
        message = transform(value)
        self.on_warning_message(obj, message)

    def on_warning_message(self, obj, message):
        if len(message):
            self.set_state(message=message)

    def on_error_changed(self, *args):
        messages = ', '.join(
            [
                txt for txt, obj in list(self.errors.items()) if obj.is_active() and obj.get() == 1
            ]
        )
        self.set_state(message=messages)
        if messages:
            self.set_state(health=(4, 'error', 'Staff needed'))
        else:
            self.set_state(health=(0, 'error', ''))

    @staticmethod
    def wait_for_value(variable: Any, *values: Any, timeout: int = 30, invert: bool = False) -> bool:
        """
        Wait for a variable to reach a specific value
        :param variable: process variable to check
        :param values: values to check
        :param timeout: max duration to wait
        :param invert: if True, wait for the variable to not be in values
        :return: True if successful, False if timed out
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            current_value = variable.get()
            if invert != (current_value in values):
                break
            time.sleep(0.01)
        else:
            value_str = ' | '.join([str(v) for v in values])
            logger.warn(f'Timeout waiting for variable "{variable.name}" to be "{value_str}"')
            return False
        return True

    def wait_for_position(self, position, timeout=120):
        return self.wait_for_value(self.position_fbk, position, timeout=timeout)


