import re

from mxdc.devices.automounter import AutoMounter, State, logger
from mxdc.utils.automounter import Port, Puck, Cassette

SAM_DEWAR = {
    # Puck Adapters
    'LA': Puck('LA', 0.25 - 1 / 12., 0.25 - 1 / 12.),
    'LB': Puck('LB', 0.25 - 1 / 12., 0.25 + 1 / 12.),
    'LC': Puck('LC', 0.25 + 1 / 12., 0.25 - 1 / 12.),
    'LD': Puck('LD', 0.25 + 1 / 12., 0.25 + 1 / 12.),

    'MA': Puck('MA', 0.5 - 1 / 12., 0.75 - 1 / 12.),
    'MB': Puck('MB', 0.5 - 1 / 12., 0.75 + 1 / 12.),
    'MC': Puck('MC', 0.5 + 1 / 12., 0.75 - 1 / 12.),
    'MD': Puck('MD', 0.5 + 1 / 12., 0.75 + 1 / 12.),

    'RA': Puck('RA', 0.75 - 1 / 12, 0.25 - 1 / 12.),
    'RB': Puck('RB', 0.75 - 1 / 12, 0.25 + 1 / 12.),
    'RC': Puck('RC', 0.75 + 1 / 12, 0.25 - 1 / 12.),
    'RD': Puck('RD', 0.75 + 1 / 12, 0.25 + 1 / 12.),

    # Cassettes
    'L': Cassette('L', 0.25, 0.25),
    'M': Cassette('M', 0.50, 0.75),
    'R': Cassette('R', 0.75, 0.25)

}

class UncleSAM(AutoMounter):
    """
    Auto mounter Device based on the UncleSAM EPICS driver without Blu-ICE.

    :param root: Root name of EPICS process variables
    """

    StateCodes = {
        '0': Port.EMPTY,
        '1': Port.GOOD,
        'u': Port.UNKNOWN,
        'm': Port.MOUNTED,
        'j': Port.BAD,
        'b': Port.EMPTY,
        '-': Port.UNKNOWN
    }
    TypeCodes = {
        'u': 'unknown',
        '1': 'cassette',
        '2': 'calib',
        '3': 'puck',
    }

    def __init__(self, root):
        super().__init__()
        self.name = 'SAM Automounter'

        # Status
        self.ports_fbk = self.add_pv('{}:PORTS'.format(root))
        self.sample_fbk = self.add_pv('{}:STATE:PORT'.format(root))
        self.prefetched_fbk = self.add_pv('{}:STATE:PREFETCHED'.format(root))

        self.message_fbk = self.add_pv('{}:MESSAGE'.format(root))
        self.warning_fbk = self.add_pv('{}:STATE:WRN'.format(root))
        self.state_fbk = self.add_pv('{}:STATE:CODE'.format(root))
        self.health_fbk = self.add_pv('{}:HEALTH'.format(root))
        self.enabled_fbk = self.add_pv('{}:ENABLED'.format(root))
        self.status_fbk = self.add_pv('{}:STATUS'.format(root))
        self.position_fbk = self.add_pv(f'{root}:STATE:POS')

        # commands
        self.mount_cmd = self.add_pv('{}:CMD:mount'.format(root))
        self.port_param = self.add_pv('{}:PARAM:NEXTPORT'.format(root))
        self.dismount_cmd = self.add_pv('{}:CMD:dismount'.format(root))
        self.prefetch_cmd = self.add_pv('{}:CMD:prefetch'.format(root))
        self.abort_cmd = self.add_pv('{}:CMD:abort'.format(root))

        self.ports_fbk.connect('changed', self.on_ports_changed)
        self.sample_fbk.connect('changed', self.on_sample_changed)
        self.prefetched_fbk.connect('changed', self.on_prefetch_changed)
        self.message_fbk.connect('changed', self.on_messages)

        status_pvs = [self.warning_fbk, self.status_fbk, self.health_fbk, self.enabled_fbk]
        for pv in status_pvs:
            pv.connect('changed', self.on_states_changed)

    def is_valid(self, port):
        if not re.match('[RML][ABCDEFGHIJKL]\d{1,2}', port):
            return False
        return True

    def is_mountable(self, port):
        if self.is_valid(port):
            ports = self.get_state('ports')
            return ports.get(port, Port.UNKNOWN) not in [Port.BAD, Port.EMPTY]
        return False

    def mount(self, port, wait=True):
        enabled = self.wait_until(State.IDLE, State.PREPARING, State.STANDBY, timeout=360)
        if enabled and self.get_state('status') == State.STANDBY:
            self.set_state(message='STANDBY. Mount will be excuted after current operation.')
            self.wait_while(State.STANDBY, timeout=720)

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
            logger.info('{}: Mounting Sample: {}'.format(self.name, port))
            self.port_param.put(port)
            self.mount_cmd.put(1)

            if wait:
                success = self.wait_while(State.IDLE, timeout=60)
                success |= self.wait_until(State.STANDBY, State.IDLE, timeout=360)
                mounted = self.sample_fbk.get()
                success |= (mounted == port)
                if not success:
                    self.set_state(message="Mounting failed!")
                return success
            else:
                return True

    def dismount(self, wait=False):
        enabled = self.wait_until(State.IDLE, State.PREPARING, State.STANDBY, timeout=360)
        if enabled and self.get_state('status') == State.STANDBY:
            self.set_state(message='STANDBY. Mount will be excuted after current operation.')
            self.wait_while(State.STANDBY, timeout=720)

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
            logger.info('{}: Dismounting sample.'.format(self.name, ))
            self.dismount_cmd.put(1)

            if wait:
                success = self.wait_while(State.IDLE, timeout=60)
                success |= self.wait_until(State.STANDBY, State.IDLE, timeout=360)
                mounted = self.sample_fbk.get()
                success |= (mounted == '')
                if not success:
                    self.set_state(message="Dismounting failed!")
                return success
            else:
                return True

    def prefetch(self, port, wait=False):
        if self.prefetched_fbk.get():
            return False

        enabled = self.wait_until(State.IDLE, State.PREPARING, State.STANDBY, timeout=360)
        if enabled and self.get_state('status') == State.STANDBY:
            self.set_state(message='STANDBY. Mount will be excuted after current operation.')
            self.wait_while(State.STANDBY, timeout=720)

        if not enabled:
            logger.warning('{}: not ready. command ignored!'.format(self.name))
            self.set_state(message="Not ready, command ignored!")
            self.cancel()
            return False
        elif self.is_mounted(port):
            logger.info('{}: Sample {} already mounted. Will not prefetch it.'.format(self.name, port))
            self.set_state(message="Sample already mounted!")
            return True
        elif not self.is_mountable(port):
            logger.info('{}: Sample {} cannot be prefetched!'.format(self.name, port))
            self.set_state(message="Port cannot be prefetched!")
            return False
        else:
            logger.info('{}: Prefetch Sample: {}'.format(self.name, port))
            self.port_param.put(port)
            self.prefetch_cmd.put(1)

            if wait:
                success = self.wait_while(State.IDLE, timeout=60)
                success |= self.wait_until(State.IDLE, timeout=240)
                prefetched_port = self.prefetched_fbk.get()
                success |= port == prefetched_port
                if not success:
                    self.set_state(message="Prefetch failed!")
                return success
            else:
                return True

    def abort(self):
        self.abort_cmd.put(1)

    def on_messages(self, obj, *args, **kwargs):
        text_msg = self.message_fbk.get()
        text_warn = self.warning_fbk.get()
        warnings = text_warn.strip()
        messages = text_msg.strip()
        self.set_state(message="{} {}".format(messages, warnings).strip())

    def on_states_changed(self, obj, *args, **kwargs):
        is_normal = self.health_fbk.get() == 1
        is_disabled = self.enabled_fbk.get() == 0
        state = self.status_fbk.get()
        cur_status = self.get_state('status')
        health = 0
        diagnosis = []

        if is_normal:
            if is_disabled:
                status = State.DISABLED
                health |= 16
                diagnosis += ['Disabled by staff']
            elif state == 3:
                status = State.STANDBY
            elif state in [1, 2, 4]:
                status = State.BUSY
            elif state == 0:
                status = State.PREPARING if cur_status == State.PREPARING else State.IDLE
                diagnosis += ['Ready']
            else:
                health |= 4
                diagnosis += ['Error! Staff Needed.']
                status = State.ERROR
        else:
            health |= 4
            diagnosis += ['Error! Staff Needed.']
            status = State.ERROR

        logger.debug('Automounter state: {}'.format(status))
        self.set_state(status=status, health=(health, 'notices', 'Staff Needed'), message=', '.join(diagnosis))

    def on_sample_changed(self, obj, val):
        port_str = val.strip()
        if not port_str:
            self.set_state(sample={})
            logger.debug('Sample dismounted')
        else:
            port = port_str
            sample = {
                'port': port.upper(),
                'barcode': '' # TODO reimplement barcode reader
            }
            if sample != self.get_state('sample'):
                self.set_state(sample=sample)
                logger.debug('Mounted:  port={port} barcode={barcode}'.format(**sample))

    def on_prefetch_changed(self, obj, port):
        if not port:
            signals = {
                'next_port': '',
                'message': 'Sample De-fetched'
            }
            logger.debug('Sample De-fetched')
        else:
            signals = {
                'next_port': port,
                'message': 'Prefetched:  port={}'.format(port)
            }
            logger.debug(signals['message'])

        self.set_state(**signals)

    def on_ports_changed(self, obj, state_str):
        if len(state_str) < 291:
            return

        info = {
            'L': (state_str[0], state_str[1:97]),
            'M': (state_str[97], state_str[98:-97]),
            'R': (state_str[-97], state_str[-96:])
        }
        port_states = {}

        container_spec = {
            'puck': ('ABCD', list(range(1, 17))),
            'cassette': ('ABCDEFGHIJKL', list(range(1, 9))),
            'calib': ('ABCDEFGHIJKL', list(range(1, 9))),
        }
        containers = set()
        for location, (type_code, port_states_str) in list(info.items()):
            type_name = self.TypeCodes.get(type_code)
            if not type_name: continue
            spec = container_spec.get(type_name)

            if type_name == 'puck':
                containers |= {'{}{}'.format(location, pos) for pos in spec[0]}
            elif type_name in ['cassette', 'calib']:
                containers |= {location}

            if spec:
                ports = [
                    '{}{}{}'.format(location, sub_loc, pos)
                    for sub_loc in spec[0]
                    for pos in spec[1]
                ]
                states = [self.StateCodes.get(c, Port.UNKNOWN) for c in port_states_str]
                port_states.update({port: state for port, state in zip(ports, states)})

        self.set_state(layout={loc: SAM_DEWAR[loc] for loc in containers})
        self.set_state(containers=containers)
        self.set_state(ports=port_states)


