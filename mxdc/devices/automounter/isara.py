import time

from gi.repository import GLib
from mxdc.devices.automounter import AutoMounter, State, logger
from mxdc.utils.automounter import Port, Puck
from mxdc.utils.decorators import async_call

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


class ISARAMessages(object):
    @staticmethod
    def trajectory(message):
        return {
            'getput': 'Switching sample ...',
            'get': 'Dismounting sample ...',
            'put': 'Mounting sample ...',
            'dry': 'Drying gripper ...',
            'soak': 'Soaking ...',
            'home': 'Going home ...'
        }.get(message.lower().strip(), 'Busy ...')

    @staticmethod
    def errors(message):
        replacements = {
            'high level alarm Dew1': 'Dewar LN2 topped up',
            'WAIT for RdTrsf condition / 9 not TRUE': 'Waiting for endstation-ready ...',
            'WAIT for SplOn condition / not TRUE / 1': 'Checking sample on gonio ...'
        }
        for old, new in list(replacements.items()):
            message = message.replace(old, new)
        if message:
            return message


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
        self.next_smpl = self.add_pv('{}:PAR:nextPort'.format(root))
        self.power_cmd = self.add_pv('{}:CMD:power'.format(root))
        self.mount_cmd = self.add_pv('{}:CMD:mount'.format(root))
        self.dismount_cmd = self.add_pv('{}:CMD:dismount'.format(root))
        self.abort_cmd = self.add_pv('{}:CMD:abort'.format(root))
        self.reset_cmd = self.add_pv('{}:CMD:reset'.format(root))
        self.clear_cmd = self.add_pv('{}:CMD:clear'.format(root))
        self.back_cmd = self.add_pv('{}:CMD:back'.format(root))
        self.safe_cmd = self.add_pv('{}:CMD:safe'.format(root))
        self.set_smpl_cmd = self.add_pv('{}:CMD:setDiffSmpl'.format(root))

        # feedback
        self.status_fbk = self.add_pv('{}:STATUS'.format(root))
        self.power_fbk = self.add_pv('{}:STATE:power'.format(root))
        self.mode_fbk = self.add_pv('{}:STATE:mode'.format(root))
        self.cryo_fbk = self.add_pv('{}:INP:cryoLevel'.format(root))
        self.autofill_fbk = self.add_pv('{}:STATE:autofill'.format(root))
        self.position_fbk = self.add_pv('{}:STATE:pos'.format(root))

        self.enabled_fbk = self.add_pv('{}:ENABLED'.format(root))
        self.connected_fbk = self.add_pv('{}:CONNECTED'.format(root))
        self.message_fbk = self.add_pv('{}:LOG'.format(root))
        self.error_fbk = self.add_pv('{}:WARNING'.format(root))
        self.path_fbk = self.add_pv('{}:STATE:path'.format(root))
        self.mounted_fbk = self.add_pv('{}:STATE:onDiff'.format(root))
        self.barcode_fbk = self.add_pv('{}:STATE:barcode'.format(root))
        self.tooled_fbk = self.add_pv('{}:STATE:onTool'.format(root))
        self.pucks_fbk = self.add_pv('{}:STATE:pucks'.format(root))
        self.path_fbk = self.add_pv('{}:STATE:path'.format(root))
        self.sample_detected = self.add_pv('{}:INP:smplOnGonio'.format(root))

        # handle signals
        self.path_fbk.connect('changed', self.on_message, ISARAMessages.trajectory)
        self.error_fbk.connect('changed', self.on_message, ISARAMessages.errors)
        self.pucks_fbk.connect('changed', self.on_pucks_changed)
        self.mounted_fbk.connect('changed', self.on_sample_changed)
        self.reset_cmd.connect('changed', self.on_reset)

        status_pvs = [
            self.status_fbk, self.enabled_fbk, self.connected_fbk, self.autofill_fbk, self.cryo_fbk,
            self.mode_fbk
        ]
        for pv in status_pvs:
            pv.connect('changed', self.on_state_changed)

    def is_mountable(self, port):
        if self.is_valid(port):
            ports = self.get_state('ports')
            return ports.get(port, Port.UNKNOWN) not in [Port.BAD, Port.EMPTY]
        return False

    def is_valid(self, port):
        return port[:2] in self.PUCKS[1:] and 1<= int(port[2:]) <=16

    def power_on(self):
        if self.power_fbk.get() == 0:
            self.power_cmd.put(1)

    def mount(self, port, wait=True):
        self.power_on()
        enabled = self.wait_until(State.IDLE, State.PREPARING, timeout=240)
        if not enabled:
            logger.warning('{}: not ready. command ignored!'.format(self.name))
            self.set_state(message="Not ready, command ignored!")
            self.cancel()
            return False
        elif self.is_mounted(port):
            logger.info('{}: Sample {} already mounted.'.format(self.name, port))
            self.set_state(message="Sample already mounted!")
            return True
        elif not self.is_mountable(port):
            logger.info('{}: Sample {} cannot be mounted!'.format(self.name, port))
            self.set_state(message="Port cannot be mounted!")
            return False
        else:
            self.next_smpl.put(port)
            self.mount_cmd.put(1)

            logger.info('{}: Mounting Sample: {}'.format(self.name, port))
            if wait:
                success = self.wait(states={State.BUSY}, timeout=10)
                if success:
                    success = self.wait(states={State.STANDBY, State.IDLE}, timeout=120)
                if not success:
                    self.set_state(message="Mounting failed!")
                return success
            else:
                return True

    def dismount(self, wait=False):
        self.power_on()
        enabled = self.wait(states={State.IDLE, State.PREPARING}, timeout=240)

        if not enabled:
            logger.warning('{}: not ready. command ignored!'.format(self.name))
            self.set_state(message="Not ready, command ignored!")
            self.cancel()
            return False
        elif not self.is_mounted():
            logger.info('{}: No Sample mounted.'.format(self.name))
            self.set_state(message="No Sample mounted!")
            return True
        else:
            self.dismount_cmd.put(1)
            logger.info('{}: Dismounting sample.'.format(self.name, ))
            if wait:
                success = self.wait(states={State.BUSY}, timeout=10)
                if success:
                    success = self.wait(states={State.STANDBY, State.IDLE}, timeout=60)
                if not success:
                    self.set_state(message="Dismounting failed!")
                return success
            else:
                return True

    def abort(self):
        self.abort_cmd.put(1)

    @async_call
    def recover(self, context):
        failure_type, message = context
        if failure_type == 'blank-mounted':
            self.set_state(message='Recovering from: {}, please wait!'.format(failure_type))
            self.wait_for_position('SOAK', timeout=200)
            self.abort_cmd.put(1)
            time.sleep(2)
            self.reset_cmd.put(1)
            time.sleep(2)
            self.clear_cmd.put(1)
            logger.warning('Recovery complete.')
        elif failure_type == 'get-failed':
            self.set_state(message='Recovering from: {}, please wait!'.format(failure_type))
            port = self.tooled_fbk.get()
            self.clear_cmd.put(1)
            time.sleep(2)
            self.next_smpl.put(port)
            self.set_smpl_cmd.put(1)
            time.sleep(2)
            self.abort_cmd.put(1)
            time.sleep(2)
            self.safe_cmd.put(1)
            self.wait_for_position('HOME')
            time.sleep(2)
            self.dry_cmd.put(1)
            self.wait_for_position('SOAK', timeout=200)
            time.sleep(5)
            logger.warning('Recovery complete.')
        else:
            logger.warning('Recovering from: {} not available.'.format(failure_type))

    def on_pucks_changed(self, obj, states):
        if len(states) == 29:
            pucks = {self.PUCKS[i + 1] for i, bit in enumerate(states) if bit == '1'}
            states = {
                '{}{}'.format(puck, 1 + pin): Port.UNKNOWN for pin in range(16) for puck in pucks
            }
            self.set_state(ports = states)
            self.set_state(containers = pucks)
            self.set_state(health=(0, 'pucks', ''))
        else:
            self.set_state(health=(16, 'pucks', 'Puck detection!'), message='Could not read puck positions!')
            self.set_state(ports = {})
            self.set_state(containers = set())

    def on_sample_changed(self, obj, mounted_port):
        # reset state
        sample = self.get_state('sample')
        port = sample.get('port')
        ports = self.get_state('ports')
        if self.is_valid(mounted_port):
            GLib.timeout_add(2000, self.check_blank)
            ports[mounted_port] = Port.MOUNTED
            sample = {
                'port': mounted_port,
                'barcode': ''
            }
        else:
            if ports.get(port) == Port.MOUNTED:
                ports[port] = Port.UNKNOWN
                self.set_state(message='Sample dismounted')
            sample = {}
        self.set_state(sample=sample)
        self.set_state(ports=ports)

    def check_blank(self):
        sample = self.get_state('sample')
        status = self.get_state('status')
        failure_state = all([
            self.sample_detected.get() == 0,
            bool(sample.get('port')),
            status in [State.BUSY],
            status != State.FAILURE
        ])

        if failure_state:
            port =  sample['port']
            ports = self.get_state('ports')
            ports[port] = Port.BAD
            message = (
                "Automounter either failed to pick the sample at {0}, \n"
                "or there was no sample at {0}. Make sure there \n"
                "really is no sample mounted, then proceed to recover."
            ).format(sample['port'])
            self.set_state(status=State.FAILURE, failure=('blank-mounted', message), ports=ports)
        else:
            self.set_state(message='Sample mounted')

    def check_no_get(self):
        status = self.get_state('status')
        failure_state = all([
            self.sample_detected.get() == 1,
            bool(self.mounted_fbk.get()) == False,
            bool(self.tooled_fbk.get()),
            self.position_fbk.get() == 'UNKNOWN',
            status in [State.BUSY],
            status != State.FAILURE
        ])

        if failure_state:
            message = (
                "Automounter failed to get sample from Gonio.\n"
                "Make sure samples is still on gonio then then proceed to recover."
            )
            self.set_state(status=State.FAILURE, failure=('get-failed', message))

    def on_state_changed(self, *args):

        health = 0
        diagnosis = []
        connected = (self.connected_fbk.get() == 1)
        enabled = (self.enabled_fbk.get() == 1)
        auto_mode = (self.mode_fbk.get() == 1)
        status_value = self.status_fbk.get()
        cryo_good = (self.autofill_fbk.get() == 0) or (2 <= self.cryo_fbk.get() <= 4)  # good if autofill disabled

        if connected:
            if not enabled:
                status = State.DISABLED
                health |= 16
                diagnosis += ['Disabled by staff']
            elif status_value in [1, 2]:
                status = State.BUSY
            elif status_value == 3:
                status = State.STANDBY
            elif status_value == 4:
                status = State.ERROR
            else:
                status = State.PREPARING if self.status == State.PREPARING else State.IDLE
        elif not auto_mode:
            status = State.ERROR
            self.set_state(message='Staff Needed! Wrong Mode/Tool.')
        else:
            health |= 4
            diagnosis += ['Controller Disconnected! Staff Needed.']
            status = State.ERROR

        if not cryo_good:
            health |= 4
            diagnosis += ['Cryo Level Problem! Staff Needed.']

        self.set_state(status=status)
        self.set_state(health=(health, 'notices', 'Staff Needed'), message=', '.join(diagnosis))

    def on_message(self, obj, value, transform):
        message = transform(value)
        if message:
            self.set_state(message=message)

    def on_reset(self, obj, value):
        if value == 1:
            self.set_state(failure=None)

    def on_error_changed(self, *args):
        messages = ', '.join([
            txt for txt, obj in list(self.errors.items()) if obj.is_active() and obj.get() == 1
        ])
        self.set_state(message=messages)
        if messages:
            self.set_state(health=(4, 'error','Staff needed'))
        else:
            self.set_state(health=(0, 'error', ''))

    def wait_for_position(self, position, timeout=120):
        """
        Wait for the given position to be reached
        :param position: requested position to wait for
        :param timeout: maximum time to wait
        :return: bool, True if state was attained or False if timeout was exhausted
        """

        time_remaining = timeout
        poll = 0.05
        while time_remaining > 0 and self.position_fbk.get() != position:
            time_remaining -= poll
            time.sleep(poll)

        if time_remaining <= 0:
            logger.warning('Timed out waiting for {} to reach {} position'.format(self.name, position))
            return False

