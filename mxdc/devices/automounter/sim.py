import copy
import re
import time
from gi.repository import GObject
from mxdc.devices.automounter import AutoMounter, State, logger
from mxdc.utils.automounter import Port
from .sam import SAM_DEWAR


class SimSAM(AutoMounter):
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

    TEST_STATE1 = (
        '31uuuuuuuuuujuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu--------------------------------'
        '01uuuuuuuuuuuumuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu0uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu'
        '20------uu------uu------uu------uu------uu------uu------uu------uu------uu------uu------uu------u'
    )
    TEST_STATE2 = (
        '11uuu00000uuj11u1uuuuuuuuuuuuuuuu111111uuuuuuuuuuuuuuuuuuuuuuuuuu--------------------------------'
        '11uuuuuuuuuuuumuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu0uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu'
        '10------uu------uu------uu------uu------uu------uu------uu------uu------uu------uu------uu------u'
    )
    TEST_STATE3 = (
        '31uuu00000uuj11u1uuuuuuuuuuuuuuuu111111uuuuuuuuuuuuuuuuuuuuuuuuuu--------------------------------'
        '31uuuuuuuuuuuumuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu0uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu'
        '10------uu------uu------uu------uu------uu------uu------uu------uu------uu------uu------uu------u'
    )

    def __init__(self):
        super(SimSAM, self).__init__()
        self.name = 'SIM Automounter'
        GObject.timeout_add(2000, self._initialize)

    def _initialize(self):
        self.on_ports_changed(None, self.TEST_STATE3)
        self.props.sample = {'port': 'MA14'}
        self.props.status = State.IDLE
        self.set_state(active=True, health=(0, ''), message='Ready')

    def is_valid(self, port):
        if not re.match('[RML][ABCDEFGHIJKL]\d{1,2}', port):
            return False
        return True

    def is_mountable(self, port):
        if self.is_valid(port):
            return self.ports.get(port, Port.UNKNOWN) not in [Port.BAD, Port.EMPTY]
        return False

    def mount(self, port, wait=False):
        enabled = self.wait(states={State.IDLE, State.PREPARING})
        if not enabled:
            logger.warning('{}: not ready {}. command ignored!'.format(self.name, self.status))
            self.set_state(message="Not ready, command ignored!")
            self.cancel()
            return False
        elif self.is_mounted(port):
            logger.info('{}: Sample {} already mounted.'.format(self.name, port))
            self.set_state(message="Sample already mounted!")
            return True
        else:
            if self.is_mounted():
                command = self._sim_mountnext_done
                self._sim_mount_start('Mounting next Sample')
            else:
                self._sim_mount_start('Mounting sample')
                command = self._sim_mount_done

            logger.info('{}: Mounting Sample: {}'.format(self.name, port))
            GObject.timeout_add(8000, command, port)
            if wait:
                time.sleep(9)
                return True
            else:

                return True

    def dismount(self, wait=False):
        enabled = self.wait(states={State.IDLE, State.PREPARING})
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
            self._sim_mount_start('Dismounting')

            logger.info('{}: Dismounting sample.'.format(self.name, ))
            if wait:
                time.sleep(8)
                self._sim_dismount_done()
                return True
            else:
                GObject.timeout_add(8000, self._sim_dismount_done)
                return True

    def abort(self):
        pass

    def on_ports_changed(self, obj, state_str):
        fbstr = ''.join(state_str.split())
        info = {
            'L': (fbstr[0], fbstr[1:97]),
            'M': (fbstr[97], fbstr[98:-97]),
            'R': (fbstr[-97], fbstr[-96:])
        }
        port_states = {}

        container_spec = {
            'puck': ('ABCD', range(1, 17)),
            'cassette': ('ABCDEFGHIJKL', range(1, 9)),
            'calib': ('ABCDEFGHIJKL', range(1, 9)),
        }
        containers = set()

        for location, (type_code, port_states_str) in info.items():
            type_name = self.TypeCodes.get(type_code, 'puck')
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

    def _sim_mount_start(self, message):
        self.configure(status=State.BUSY)
        self.set_state(message=message)

    def _sim_mount_done(self, port, dry=True):
        ports = copy.deepcopy(self.ports)
        ports[port] = Port.MOUNTED
        self.configure(sample={'port': port, 'barcode': ''}, ports=ports, status=State.IDLE)
        self.set_state(busy=False, message="Sample mounted")
        #self.configure(status=State.FAILURE, failure=('testing', 'Testing Failure recovery'))


    def _sim_dismount_done(self, dry=True):
        port = self.sample['port']
        ports = self.ports
        ports[port] = Port.GOOD
        self.configure(sample={'port': port, 'barcode': ''}, ports=ports, status=State.IDLE)
        self.set_state(busy=False, message="Sample dismounted")
        #self.configure(status=State.FAILURE, failure=('testing', 'Testing Failure recovery'))

    def _sim_mountnext_done(self, port, dry=True):
        mounted_port = self.sample['port']
        ports = copy.copy(self.props.ports)
        ports[mounted_port] = Port.GOOD
        self.configure(sample={}, ports=ports)
        self.set_state(message="Sample dismounted")
        ports[port] = Port.MOUNTED
        self.configure(sample={'port': port, 'barcode': ''}, ports=ports, status=State.IDLE)
        self.set_state(busy=False, message="Sample mounted")
        #self.configure(status=State.FAILURE, failure=('testing', 'Testing Failure recovery'))

    def recover(self, context):
        failure_type, message = context
        if failure_type == 'testing':
            logger.warning('Recovering from: {}'.format(failure_type))
            port = self.props.sample['port']
            self.dismount()
            ports = self.ports
            ports[port] = Port.BAD
            if self.props.failure and self.props.failure[0] == failure_type:
                self.configure(status=State.IDLE, ports=ports, failure=None)
            else:
                self.configure(status=State.FAILURE)
        else:
            logger.warning('Recovering from: {} not available.'.format(failure_type))