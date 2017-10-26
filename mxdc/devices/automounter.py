# ===============================================================================
# Automounter Classes
# ===============================================================================

import copy
import re
import time

from enum import Enum
from gi.repository import GObject
from zope.interface import implements

from interfaces import IAutomounter
from mxdc.devices.base import BaseDevice
from mxdc.utils.automounter import Port, SAM_DEWAR, ISARA_DEWAR
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)




class State(Enum):
    IDLE, STANDBY, BUSY, NOT_READY, DISABLED, ERROR = range(6)

class AutoMounter(BaseDevice):
    implements(IAutomounter)

    layout = GObject.Property(type=object)
    sample = GObject.Property(type=object)
    ports = GObject.Property(type=object)
    status = GObject.Property(type=object)

    def __init__(self):
        super(AutoMounter, self).__init__()
        self.name = 'Automounter'
        self.state_history = set()
        self.props.layout = {}
        self.props.sample = {}
        self.props.ports = {}
        self.props.status = State.IDLE
        self.state_link = self.connect('notify::status', self._record_state)
        self.connect('notify::status', self._emit_state)

    def _emit_state(self, *args, **kwargs):
        self.set_state(busy=(self.props.status == State.BUSY))

    def _watch_states(self):
        """
        Enable automounter state monitoring
        """
        self.handler_unblock(self.state_link)

    def _unwatch_states(self):
        """
        disable automounter state monitoring
        """
        self.handler_block(self.state_link)
        self.state_history = set()

    def _record_state(self, *args, **kwargs):
        """
        Record all state changes into a set
        """
        self.state_history.add(self.props.status)

    def switch_status(self, state):
        """
        Switch to a different state
        @param state: state to switch to
        @return:
        """
        self.props.status = state


    def standby(self):
        """
        Get ready to start
        @return:
        """
        if self.is_ready() or self.in_standby():
            GObject.idle_add(self.switch_status, State.STANDBY)
            return True
        else:
            return False

    def cancel(self):
        """
        Cancel Standby state
        @return:
        """
        if self.in_standby():
            GObject.idle_add(self.switch_status, State.IDLE)
            return True
        else:
            return False

    def mount(self, port, wait=False):
        """
        Mount the sample at the given port. Must take care of preparing the end station
        and dismounting any mounted samples before mounting
        @param port: str, the port to mount
        @param wait: bool, whether to block until operation is completed
        @return: bool, True if successful
        """
        raise NotImplementedError('Sub-classes must implement mount method')

    def dismount(self, wait=False):
        """
        Dismount the currently mounted sample.
        Must take care of preparing the end station
        and dismounting any mounted samples before mounting
        @return: bool, True if successful
        """
        raise NotImplementedError('Sub-classes must implement dismount method')

    def abort(self):
        """
        Abort current operation
        @return:
        """
        raise NotImplementedError('Sub-classes must implement dismount method')

    def wait(self, states={State.IDLE}, timeout=60):
        """
        Wait for the given state to be attained
        @param states: requested state to wait for or a list of states
        @param timeout: maximum time to wait
        @return: bool, True if state was attained or False if timeout was exhausted
        """

        if self.status not in states:
            logger.debug('Waiting for {}:{}'.format(self.name, states))
            time_remaining = timeout
            poll = 0.05
            while time_remaining > 0 and not self.status in states:
                time_remaining -= poll
                time.sleep(poll)

            if time_remaining <= 0:
                logger.warning('Timed out waiting for {}:{}'.format(self.name, states))
                return False

        return True

    def is_mountable(self, port):
        """
        Check if the specified port can be mounted successfully
        @param port: str representation of the port
        @return: bool, True if it is mounted
        """
        raise NotImplementedError('Sub-classes must implement is_mountable method')

    def is_valid(self, port):
        """
        Check if the specified port is a valid port designation for this automounter
        @param port: str representation of the port
        @return: bool, True if it is valid
        """
        raise NotImplementedError('Sub-classes must implement is_valid method')


    def is_mounted(self, port=None):
        """
        Check if the specified port is mounted
        @param port: str representation of the port or None if checking for any
        @return: bool, True if it is mounted
        """

        return (
            (port is None and bool(self.sample)) or
            ((port is not None) and self.sample and self.sample.get('port') == port)
        )

    def is_ready(self):
        """
        Check if the automounter is ready for an operation
        @return:
        """
        return (self.status in [State.IDLE, State.STANDBY] and self.is_active() and not self.is_busy())


    def in_standby(self):
        """
        Check if the automounter is preparing to start
        @return:
        """
        return (self.status == State.STANDBY)

class SAMAutoMounter(AutoMounter):
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
        super(SAMAutoMounter, self).__init__()
        self.name = 'SAM Automounter'

        # Status
        self.ports_fbk = self.add_pv('{}:cassette:fbk'.format(root))
        self.sample_fbk = self.add_pv('%s:status:mounted' % root)

        self.status_fbk = self.add_pv('{}:sample:msg'.format(root))
        self.warning_fbk = self.add_pv('{}:status:warning'.format(root))
        self.state_fbk = self.add_pv('{}:status:state'.format(root))
        self.normal_fbk = self.add_pv('%s:mod:normal' % root)
        self.disabled_fbk = self.add_pv('%s:mnt:usrEnable' % root)
        self.gonio_safe_fbk = self.add_pv('%s:goniPos:mntEn' % root)
        self.mount_safe_fbk = self.add_pv('%s:mntEn' % root)

        # commands
        self.mount_cmd = self.add_pv('%s:mntX:opr' % root)
        self.mount_param = self.add_pv('%s:mntX:param' % root)
        self.dismount_cmd = self.add_pv('%s:dismntX:opr' % root)
        self.dismount_param = self.add_pv('%s:dismntX:param' % root)
        self.mount_next_cmd = self.add_pv('%s:mntNextX:opr' % root)
        self.abort_cmd = self.add_pv('%s:abort:opr' % root)

        self.wash_param = self.add_pv('%s:washX:param' % root)
        self.bar_code = self.add_pv('%s:bcode:barcode' % root)
        self.barcode_reset = self.add_pv('%s:bcode:clear' % root)
        self.robot_busy = self.add_pv('%s:sample:sts' % root)

        self.ports_fbk.connect('changed', self.on_ports_changed)
        self.sample_fbk.connect('changed', self.on_sample_changed)

        status_pvs = [
            self.status_fbk, self.warning_fbk, self.state_fbk, self.normal_fbk,
            self.disabled_fbk, self.gonio_safe_fbk, self.mount_safe_fbk
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
        enabled = self.wait(states={State.IDLE, State.STANDBY})
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
            self.barcode_reset.put(1)

            if self.is_mounted():
                dismount_param = self.sample_fbk.get()
                self.dismount_param.put(dismount_param)
                self.mount_param.put(param)
                self.mount_next_cmd.put(1)
            else:
                self.mount_param.put(param)
                self.mount_cmd.put(1)

            logger.info('{}: Mounting Sample: {}'.format(self.name, port))
            if wait:
                success = self.wait(states={State.IDLE}, timeout=240)
                if not success:
                    self.set_state(message="Mounting timed out!")
                return success
            else:
                return True

    def dismount(self, wait=False):
        enabled = self.wait(states={State.IDLE, State.STANDBY})
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
            self.dismount_cmd.put(1)
            logger.info('{}: Dismounting sample.'.format(self.name, ))
            if wait:
                success = self.wait(states={State.IDLE}, timeout=240)
                if not success:
                    self.set_state(message="Dismount timed out!")
                return success
            else:
                return True

    def abort(self):
        self.abort_cmd.put(1)

    def on_states_changed(self, *args, **kwargs):
        is_normal = self.normal_fbk.get() == 0,
        is_safe = self.mount_safe_fbk.get() == 1 and self.gonio_safe_fbk.get() == 1
        is_enabled = self.disabled_fbk.get() == 1
        is_idle = self.robot_busy.get() == 0
        state_str = self.state_fbk.get().strip()

        health = 0
        diagnosis = []

        if all([is_normal, is_safe, is_enabled]):
            if is_idle or 'idle' in state_str:
                GObject.idle_add(self.switch_status, State.IDLE)
            elif 'standby' in state_str:
                GObject.idle_add(self.switch_status, State.STANDBY)
            else:
                GObject.idle_add(self.switch_status, State.BUSY)
        elif is_normal and is_enabled:
            health |= 16
            diagnosis += 'Disabled by staff'
            GObject.idle_add(self.switch_status, State.DISABLED)
        elif is_normal and not is_safe:
            GObject.idle_add(self.switch_status, State.NOT_READY)
        else:
            health |= 4
            diagnosis += ['Error! Staff Needed.']
            GObject.idle_add(self.switch_status, State.ERROR)

        text_warn = self.warning_fbk.get()
        warning = ", ".join([p.capitalize().strip() for p in text_warn.lower().split('. ')]).strip()
        if (time.time() - self.warning_fbk.time_state) < 10:
            self.set_state(health=(1, 'notices', warning))
        else:
            self.set_state(health=(0, 'notices'))

        text_msg = self.status_fbk.get()
        message = ", ".join([p.capitalize().strip() for p in text_msg.lower().split('. ')]).strip()
        self.set_state(health=(health, ', '.join(diagnosis)), message=message)

    def on_sample_changed(self, obj, val):
        port_str = val.strip()
        if not port_str:
            self.sample = None
            logger.debug('Sample dismounted')
        else:
            port = '{}{}{}'.format(port_str[0], port_str[2], port_str[1])
            self.props.sample = {
                'port': port.upper(),
                'barcode': self.bar_code.get()
            }
            logger.debug('Mounted:  port={port} barcode={barcode}'.format(**self.props.sample))

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
        containers = []

        for location, (type_code, port_states_str) in info.items():
            type_name = self.TypeCodes.get(type_code, 'puck')
            spec = container_spec.get(type_name)

            if type_name == 'puck':
                containers += ['{}{}'.format(location, pos) for pos in spec[0]]
            elif type_name in ['cassette', 'calib']:
                containers += [location]

            if spec:
                ports = [
                    '{}{}{}'.format(location, sub_loc, pos)
                    for sub_loc in spec[0]
                    for pos in spec[1]
                ]
                states = [self.StateCodes.get(c, Port.UNKNOWN) for c in port_states_str]
                port_states.update({port: state for port, state in zip(ports, states)})

        self.props.layout = {loc: SAM_DEWAR[loc] for loc in containers}
        self.props.ports = port_states


class SimAutoMounter(AutoMounter):
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
        super(SimAutoMounter, self).__init__()
        self.name = 'SIM Automounter'
        GObject.timeout_add(2000, self._initialize)

    def _initialize(self):
        self.on_ports_changed(None, self.TEST_STATE3)
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
        enabled = self.wait(states={State.IDLE, State.STANDBY})
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
            if wait:
                time.sleep(8)
                command(port)
                return True
            else:
                GObject.timeout_add(8000, command, port)
                return True

    def dismount(self, wait=False):
        enabled = self.wait(states={State.IDLE, State.STANDBY})
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
        containers = []

        for location, (type_code, port_states_str) in info.items():
            type_name = self.TypeCodes.get(type_code, 'puck')
            spec = container_spec.get(type_name)

            if type_name == 'puck':
                containers += ['{}{}'.format(location, pos) for pos in spec[0]]
            elif type_name in ['cassette', 'calib']:
                containers += [location]

            if spec:
                ports = [
                    '{}{}{}'.format(location, sub_loc, pos)
                    for sub_loc in spec[0]
                    for pos in spec[1]
                ]
                states = [self.StateCodes.get(c, Port.UNKNOWN) for c in port_states_str]
                port_states.update({port: state for port, state in zip(ports, states)})

        self.props.layout = {loc: SAM_DEWAR[loc] for loc in containers}
        self.props.ports = port_states

    def _sim_mount_start(self, message):
        GObject.idle_add(self.switch_status, State.BUSY)
        self.set_state( message=message)

    def _sim_mount_done(self, port, dry=True):
        self.props.sample = {
            'port': port,
            'barcode': '',
        }
        ports = copy.deepcopy(self.ports)
        ports[port] = Port.MOUNTED
        self.props.ports = ports
        self.set_state(busy=False, message="Sample mounted")
        GObject.idle_add(self.switch_status, State.IDLE)

    def _sim_dismount_done(self, dry=True):
        port = self.sample['port']
        ports = self.ports
        ports[port] = Port.GOOD
        self.props.ports = ports
        self.props.sample = {}
        self.set_state(busy=False, message="Sample dismounted")
        GObject.idle_add(self.switch_status, State.IDLE)

    def _sim_mountnext_done(self, port, dry=True):
        mounted_port = self.sample['port']
        ports = copy.copy(self.props.ports)
        ports[mounted_port] = Port.GOOD
        self.props.sample = {}
        self.set_state(busy=False, message="Sample dismounted")
        self.props.sample = {
            'port': port,
            'barcode': '',
        }
        ports[port] = Port.MOUNTED
        self.props.ports = ports
        GObject.idle_add(self.switch_status, State.IDLE)
        self.set_state(busy=False, message="Sample mounted")



class ISARAMounter(AutoMounter):
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
        super(ISARAMounter, self).__init__()
        self.name = 'ISARA Auto Mounter'
        self.command_fbk = self.add_pv('{}:last_cmnd_sts:fbk'.format(root))

        self.sample_number = self.add_pv('{}:trjarg_sampleNumber'.format(root))
        self.puck_number = self.add_pv('{}:trjarg_puckNumber'.format(root))
        self.tool_number = self.add_pv('{}:trjarg_toolNumber'.format(root))

        self.gonio_puck_fbk = self.add_pv('{}:stscom_puckNumOnDiff:fbk'.format(root))
        self.gonio_sample_fbk = self.add_pv('{}:stscom_sampleNumOnDiff:fbk'.format(root))
        self.tool_puck_fbk = self.add_pv('{}:stscom_puckNumOnTool:fbk'.format(root))
        self.tool_sample_fbk = self.add_pv('{}:stscom_sampleNumOnTool:fbk'.format(root))

        self.path_busy_fbk = self.add_pv('{}:stscom_path_run:fbk'.format(root))
        self.message_fbk = self.add_pv('{}:message'.format(root))
        self.status_fbk = self.add_pv('{}:state'.format(root))
        self.puck_probe_fbk = self.add_pv('{}:dewar_puck_sts:fbk'.format(root))

        self.abort_cmd = self.add_pv('{}:abort'.format(root))
        self.getput_cmd = self.add_pv('{}:getput'.format(root))
        self.get_cmd = self.add_pv('{}:get'.format(root))
        self.put_cmd = self.add_pv('{}:put'.format(root))
        self.on_cmd = self.add_pv('{}:message'.format(root))
        self.home_cmd = self.add_pv('{}:home'.format(root))

        self.puck_probe_fbk.connect('changed', self.on_pucks_changed)
        self.gonio_sample_fbk.connect('changed', self.on_sample_changed)
        self.path_busy_fbk.connect('changed', self.on_state_changed)

    def is_mountable(self, port):
        if self.is_valid(port):
            return self.ports.get(port, Port.UNKNOWN) not in [Port.BAD, Port.EMPTY]
        return False

    def is_valid(self, port):
        puck, sample = self._port2puck(port)
        return 29 >= puck >= 1 and 1 <= sample <= 16

    def _port2puck(self, port):
        position = (0, 0)
        if len(port) >= 3:
            if port[:2] in self.PUCKS:
                position = (self.PUCKS.index(port[:2]), int(port[2:]))
        return position

    def mount(self, port, wait=True):
        enabled = self.wait(states={State.IDLE, State.STANDBY})
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
            puck, pin = self._port2puck(port)
            if self.is_mounted():
                self.puck_number.put(puck)
                self.sample_number.put(pin)
                self.getput_cmd.put(1)
            else:
                self.put_cmd.put(1)

            logger.info('{}: Mounting Sample: {}'.format(self.name, port))
            if wait:
                success = self.wait(states={State.IDLE}, timeout=240)
                if not success:
                    self.set_state(message="Mounting timed out!")
                return success
            else:
                return True

    def dismount(self, wait=False):
        enabled = self.wait(states={State.IDLE, State.STANDBY})
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
            self.get_cmd.put(1)
            logger.info('{}: Dismounting sample.'.format(self.name, ))
            if wait:
                success = self.wait(states={State.IDLE}, timeout=240)
                if not success:
                    self.set_state(message="Dismount timed out!")
                return success
            else:
                return True

    def abort(self):
        self.abort_cmd.put(1)

    def on_pucks_changed(self, obj, states):
        m = re.match('^di2\(([\d,]+)\)?$', states)
        if m:
            sts = m.groups()[0].replace(',','')
            pucks = [
                self.PUCKS[i+1] for i, bit in enumerate(sts) if bit == '1'
            ]
            states = {
                '{}{}'.format(puck, 1+pin) : Port.UNKNOWN for pin in range(16) for puck in pucks
            }
            self.props.ports = states
            self.props.layout = ISARA_DEWAR
        else:
            self.props.ports = {}

    def on_sample_changed(self, obj, value):
        pin = int(self.gonio_puck_fbk.get())
        puck = int(self.gonio_sample_fbk.get())

        if puck and pin:
            port = '{}{}'.format(self.PUCKS[puck], pin)
            self.props.sample = {
                'port': port,
                'barcode': ''
            }
        else:
            self.props.sample = None

    def on_state_changed(self, obj, value):
        if value:
            GObject.idle_add(self.switch_status, State.BUSY)
        else:
            GObject.idle_add(self.switch_status, State.IDLE)
