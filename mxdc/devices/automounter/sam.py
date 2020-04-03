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

class SAM(AutoMounter):
    """
    Auto mounter Device based on the old EPICS/DCSS/Blu-ICE driver .

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
        self.ports_fbk = self.add_pv('{}:cassette:fbk'.format(root))
        self.sample_fbk = self.add_pv('%s:status:mounted' % root)

        self.message_fbk = self.add_pv('{}:sample:msg'.format(root))
        self.warning_fbk = self.add_pv('{}:status:warning'.format(root))
        self.state_fbk = self.add_pv('{}:status:state'.format(root))
        self.normal_fbk = self.add_pv('{}:mod:normal'.format(root))
        self.disabled_fbk = self.add_pv('{}:mnt:usrEnable'.format(root))
        self.safety_fbk = self.add_pv('{}:botSafety:state'.format(root))

        # commands
        self.mount_cmd = self.add_pv('%s:mntX:opr' % root)
        self.mount_param = self.add_pv('%s:mntX:param' % root)
        self.dismount_cmd = self.add_pv('%s:dismntX:opr' % root)
        self.dismount_param = self.add_pv('%s:dismntX:param' % root)
        self.mount_next_cmd = self.add_pv('%s:mntNextX:opr' % root)
        self.abort_cmd = self.add_pv('%s:abort:opr' % root)

        self.wash_param = self.add_pv('%s:washX:param' % root)
        #self.bar_code = self.add_pv('%s:bcode:barcode' % root)
        #self.barcode_reset = self.add_pv('%s:bcode:clear' % root)
        self.robot_busy = self.add_pv('%s:sample:sts' % root)

        self.ports_fbk.connect('changed', self.on_ports_changed)
        self.sample_fbk.connect('changed', self.on_sample_changed)
        self.message_fbk.connect('changed', self.on_messages)

        status_pvs = [
            self.warning_fbk, self.state_fbk, self.normal_fbk,
            self.disabled_fbk, self.safety_fbk
        ]
        for pv in status_pvs:
            pv.connect('changed', self.on_states_changed)

    def is_valid(self, port):
        if not re.match('[RML][ABCDEFGHIJKL]\d{1,2}', port):
            return False
        return True

    def is_mountable(self, port):
        if self.is_valid(port):
            return self.ports.get(port, Port.UNKNOWN) not in [Port.BAD, Port.EMPTY]
        return False

    def mount(self, port, wait=True):
        enabled = self.wait(states={State.IDLE, State.PREPARING}, timeout=60)
        if not enabled:
            logger.warning('{}: not ready. command ignored!'.format(self.name))
            self.set_state(message="Not ready, command ignored!")
            self.cancel()
            return False
        elif self.is_mounted(port):
            logger.info('{}: Sample {} already mounted.'.format(self.name, port))
            self.set_state(message="Sample already mounted!")
            return True
        else:
            param = '{} {} {}'.format(port[0].lower(), port[2:], port[1])
            #self.barcode_reset.put(1)

            if self.is_mounted():
                dismount_param = self.sample_fbk.get()
                self.dismount_param.put(dismount_param)
                self.mount_param.put(param)
                self.wash_param.put(0)
                self.mount_next_cmd.put(1)
            else:
                self.mount_param.put(param)
                self.wash_param.put(0)
                self.mount_cmd.put(1)

            logger.info('{}: Mounting Sample: {}'.format(self.name, port))
            if wait:
                success = self.wait(states={State.BUSY}, timeout=10)
                if success:
                    success = self.wait(states={State.STANDBY, State.IDLE}, timeout=300)
                if not success:
                    self.set_state(message="Mounting failed!")
                return success
            else:
                return True

    def dismount(self, wait=False):
        enabled = self.wait(states={State.IDLE}, timeout=60)
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
            dismount_param = self.sample_fbk.get()
            self.dismount_param.put(dismount_param)
            self.wash_param.put(0)
            self.dismount_cmd.put(1)
            logger.info('{}: Dismounting sample.'.format(self.name, ))
            if wait:
                success = self.wait(states={State.BUSY}, timeout=10)
                if success:
                    success = self.wait(states={State.STANDBY, State.IDLE}, timeout=240)
                if not success:
                    self.set_state(message="Dismounting failed!")
                return success
            else:
                return True

    def abort(self):
        self.abort_cmd.put(1)

    def on_messages(self, obj, *args, **kwargs):
        text_msg = self.message_fbk.get()
        text_warn = self.warning_fbk.get()
        warnings = text_warn.strip().capitalize()
        messages = text_msg.strip().capitalize()
        self.set_state(message="{} {}".format(messages, warnings).strip())

    def on_states_changed(self, obj, *args, **kwargs):
        is_normal = self.normal_fbk.get() == 0
        is_disabled = self.disabled_fbk.get() == 0
        is_busy = self.robot_busy.get() == 1
        state = self.safety_fbk.get()

        health = 0
        diagnosis = []

        if is_normal:
            if is_disabled:
                status = State.DISABLED
                health |= 16
                diagnosis += ['Disabled by staff']
            elif state == 4:
                status = State.STANDBY
            elif state in [2, 3, 5] or is_busy:
                status = State.BUSY
            elif state == 1:
                status = State.PREPARING if self.status == State.PREPARING else State.IDLE
                diagnosis += ['Ready']
            else:
                status = State.BUSY
        else:
            health |= 4
            diagnosis += ['Error! Staff Needed.']
            status = State.ERROR

        self.configure(status=status)
        self.set_state(health=(health, 'notices', 'Staff Needed'), message=', '.join(diagnosis))

    def on_sample_changed(self, obj, val):
        port_str = val.strip().split()
        if not port_str:
            self.sample = None
            logger.debug('Sample dismounted')
        else:
            port = '{}{}{}'.format(port_str[0], port_str[2], port_str[1])
            sample = {
                'port': port.upper(),
                'barcode': '' #self.bar_code.get()
            }
            if sample != self.props.sample:
                self.props.sample = sample
                logger.debug('Mounted:  port={port} barcode={barcode}'.format(**self.props.sample))

    def on_ports_changed(self, obj, state_str):
        fbstr = ''.join(state_str.split())
        if len(fbstr) < 291:
            return
        info = {
            'L': (fbstr[0], fbstr[1:97]),
            'M': (fbstr[97], fbstr[98:-97]),
            'R': (fbstr[-97], fbstr[-96:])
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

        self.props.layout = {loc: SAM_DEWAR[loc] for loc in containers}
        self.props.containers = containers
        self.props.ports = port_states


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
            return self.ports.get(port, Port.UNKNOWN) not in [Port.BAD, Port.EMPTY]
        return False

    def mount(self, port, wait=True):
        enabled = self.wait(states={State.IDLE, State.PREPARING}, timeout=60)
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
            self.port_param.put(port)
            self.mount_cmd.put(1)

            logger.info('{}: Mounting Sample: {}'.format(self.name, port))
            if wait:
                success = self.wait(states={State.BUSY}, timeout=10)
                if success:
                    success = self.wait(states={State.STANDBY, State.IDLE}, timeout=300)
                if not success:
                    self.set_state(message="Mounting failed!")
                return success
            else:
                return True

    def dismount(self, wait=False):
        enabled = self.wait(states={State.IDLE, State.PREPARING}, timeout=60)
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

    def prefetch(self, port, wait=True):
        enabled = self.wait(states={State.IDLE, State.PREPARING}, timeout=60)
        if self.prefetched_fbk.get():
            return False  # no prefetching if already prefetched
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
            logger.info('{}: Sample {} cannot be prefetched!'.format(self.name, port))
            self.set_state(message="Port cannot be prefetched!")
            return False
        else:
            self.port_param.put(port)
            self.prefetch_cmd.put(1)

            logger.info('{}: Prefetch Sample: {}'.format(self.name, port))
            if wait:
                success = self.wait(states={State.STANDBY}, timeout=10)
                if success:
                    success = self.wait(states={State.IDLE}, timeout=60)
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
                status = State.PREPARING if self.status == State.PREPARING else State.IDLE
                diagnosis += ['Ready']
            else:
                health |= 4
                diagnosis += ['Error! Staff Needed.']
                status = State.ERROR
        else:
            health |= 4
            diagnosis += ['Error! Staff Needed.']
            status = State.ERROR

        self.configure(status=status)
        self.set_state(health=(health, 'notices', 'Staff Needed'), message=', '.join(diagnosis))

    def on_sample_changed(self, obj, val):
        port_str = val.strip()
        if not port_str:
            self.sample = None
            logger.debug('Sample dismounted')
        else:
            port = port_str
            sample = {
                'port': port.upper(),
                'barcode': '' # TODO reimplement barcode reader
            }
            if sample != self.props.sample:
                self.props.sample = sample
                logger.debug('Mounted:  port={port} barcode={barcode}'.format(**self.props.sample))

    def on_prefetch_changed(self, obj, port):
        if not port:
            self.props.next_port = ''
            logger.debug('Sample De-fetched')
        else:
            self.props.next_port = port
            logger.debug('Prefetched:  port={}'.format(port))
            self.set_state(message='{} Prefetched'.format(port))

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

        self.props.layout = {loc: SAM_DEWAR[loc] for loc in containers}
        self.props.containers = containers
        self.props.ports = port_states


