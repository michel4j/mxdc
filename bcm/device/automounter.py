# ===============================================================================
# Automounter Classes
# ===============================================================================

from zope.interface import implements
from bcm.device.interfaces import IAutomounter
from bcm.protocol import ca
from bcm.device.base import BaseDevice
from bcm.utils.log import get_module_logger
from bcm.utils.automounter import *
import gobject as GObject
import difflib
import time
import re

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class AutomounterContainer(GObject.GObject):
    """An event driven object for representing an automounter container.
    
    Signals:
        - `changed`: Emitted when the state of the container changes. Transmits
          no data.
    """
    __gsignals__ = {
        'changed': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, []),
    }

    def __init__(self, location, status_str=None):
        """ Create a container at the specified location in the Automounter.
        
        Args:
            - `location` (str): a single character string ('L', 'R' or 'M') 
              corresponding to 'Left', 'Right', 'Middle'.
        
        Kwargs:
            - `status_str` (str or None): status string to update container with.       
        """

        GObject.GObject.__init__(self)
        self.location = location
        self.samples = {}
        self.configure(status_str)

    def do_changed(self):
        pass

    def configure(self, status_str=None):
        """Sets up the container type and state from a status string.
        If no status string is provided, it is rest the 'unknown' state.
        
        Kwargs:
            status_str (str or None): status string to update with.
            
        """
        if status_str is not None and len(status_str) > 0:
            if re.match('\d', status_str[0]):
                self.container_type = int(status_str[0])
            else:
                self.container_type = CONTAINER_UNKNOWN
        else:
            self.container_type = CONTAINER_NONE

        if self.container_type in [CONTAINER_NONE, CONTAINER_UNKNOWN, CONTAINER_EMPTY]:
            self.samples = {}
            GObject.idle_add(self.emit, 'changed')
            return
        elif self.container_type == CONTAINER_PUCK_ADAPTER:
            self.keys = 'ABCD'
            self.indices = range(1, 17)
        else:  # cassette and calibration cassette
            self.keys = 'ABCDEFGHIJKL'
            self.indices = range(1, 9)
        count = 1
        for key in self.keys:
            for index in self.indices:
                id_str = '%s%d' % (key, index)
                if status_str is not None:

                    self.samples[id_str] = [PORT_STATE_TABLE[status_str[count]], '']
                else:
                    self.samples[id_str] = [PORT_NONE, '']
                count += 1
        GObject.idle_add(self.emit, 'changed')

    def __getitem__(self, key):
        return self.samples.get(key, None)


class BasicAutomounter(BaseDevice):
    """Basic Automounter object. 

    An automounter object contains a number of AutomounterContainers.
    
    Signals:        
        - `status`: transmits changes in automounter states. The signal data is 
          a string, one of ['ready','fault'], 
        - `enabled`: <boolean>
        - `preparing`: <boolean>, indicates that a mount operation is imminent, 
            no new state changes allowed other than the currently executing ones.
        - `mounted`: emitted when a sample is mounted or dismounted. The data 
          transmitted is a tuple of the form (<port no.>, <barcode>) when 
          mounting and `None` when dismounting.
        - `progress`:  notifies listeners of automounter progress. Data is a 
           tuple of the form (<% complete>, <robot_position>, <pin_location>, <magnet_location>).
            
    """
    implements(IAutomounter)
    __gsignals__ = {
        'status': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING,)),
        'enabled': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_BOOLEAN,)),
        'preparing': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_BOOLEAN,)),
        'mounted': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_PYOBJECT,)),
        'progress': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(self):
        BaseDevice.__init__(self)
        self.containers = {'L': AutomounterContainer('L'),
                           'M': AutomounterContainer('M'),
                           'R': AutomounterContainer('R')}
        self._mounted_port = None
        self._last_warn = ''
        self.set_state(active=False, enabled=False, status='fault', preparing=False)

    def do_state(self, st):
        pass

    def do_enabled(self, st):
        pass

    def do_mounted(self, st):
        pass

    def do_preparing(self, st):
        pass

    def do_progress(self, st):
        pass

    def _parse_states(self, state):
        """This method sets up all the container types and states from a DCSS type status string.
        If no status string.
        
        Args:
            `state` (str): State string for container.
        """
        fbstr = ''.join(state.split())
        info = {
            'L': fbstr[:97],
            'M': fbstr[97:-97],
            'R': fbstr[-97:]}
        for k, s in info.items():
            self.containers[k].configure(s)

    def abort(self):
        """Abort all actions."""

    def prepare(self):
        self.set_state(preparing=True, message='Preparing to mount')

    def is_preparing(self):
        return self.preparing_state

    def mount(self, port, wash=False, wait=False):
        """Mount the sample at the specified port, optionally washing the sample
        in the process. Does nothing if the requested port is already mounted.
        Dismounts the mounted sample prior to mounting if a another sample is 
        already mounted.
        
        Args:
            - `port` (str): Address to mount.
        
        Kwargs:
            - `wash` (bool): Whether to wash or not (default is False)
            - `wait` (bool): Run asynchronously or block (default is async, False)
        
        Returns:
            bool. True if the requested sample is successfully mounted, and False
            otherwise.
        """
        pass

    def dismount(self, port=None, wait=False):
        """Dismount the sample into the specified port if provided, otherwise 
        dismount it to the original port from which it was mounted.
        
        Kwargs:
            - `port` (str): Destination address to dismount to, default is original
              port
            - `wait` (bool): Run asynchronously or block (default is async, False)
        """
        pass

    def wait(self, start=True, stop=True, timeout=240):
        """Wait for the automounter
        
        Kwargs:
            - `start` (bool): Wait for automounter to start.
            - `stop` (bool): Wait for automounter to stop.
            - `timeout` (int): Maximum time to wait
        
        Returns:
            True if the wait was successful. False if the wait timed-out.
            
        """
        poll = 0.10

        if (start and not self.is_busy()):
            _logger.debug('Waiting for (%s) to start' % (self.name,))
            _start_timeout = 60
            while not self.is_busy() and _start_timeout > 0:
                _start_timeout -= poll
                time.sleep(poll)
            if _start_timeout <= 0:
                _logger.warning('Timed out waiting for (%s) to start.' % (self.name,))
                self.set_state(preparing=False)
                return False

        if (stop and self.is_busy()):
            _logger.debug('Waiting for (%s) to stop' % (self.name,))
            while self.is_busy() and timeout > 0:
                timeout -= poll
                time.sleep(poll)
            if timeout <= 0:
                _logger.warning('Timed out waiting for (%s) to top.' % (self.name,))
                return False
        return True

    def is_mountable(self, port):
        """Check if a sample location can be mounted safely. Does not guarantee
        that the port is actually mountable, only that the the port was marked 
        as mountable during the last probe operation.
        
        Args:
            `port` (str): The sample location to check.
        
        Returns:
            True or False.
        """

        if not re.match('[RML][ABCDEFGHIJKL]\d{1,2}', port):
            return False
        info = self.containers[port[0]][port[1:]]
        if info is None:
            return False
        else:
            return info[0] in [PORT_GOOD, PORT_MOUNTED, PORT_UNKNOWN]

    def is_mounted(self, port=None):
        """Check if any sample or a specific sample location is currently 
        mounted. 
        
        Kwargs:
            `port` (str): The sample location to check.
            
        Returns:
            True if a port is specified and is mounted or if no port is 
            specified and any sample is mounted. False otherwise.
        """

        if port is None:
            return self._mounted_port != None

        if not re.match('[RML][ABCDEFGHIJKL]\d{1,2}', port):
            return False
        try:
            info = self.containers[port[0]][port[1:]]
            port_state = info[0]
        except (AttributeError, TypeError):
            port_state = PORT_UNKNOWN

        if info is None:
            return False
        else:
            return port_state == PORT_MOUNTED

    def get_port_state(self, port):
        """Obtain the detailed state of the specified sample location.
        
        Args:
            `port` (str): The sample location
        
        Returns:
            int. one of::
            
                0 -- PORT_EMPTY
                1 -- PORT_GOOD
                2 -- PORT_UNKNOWN
                3 -- PORT_MOUNTED
                4 -- PORT_JAMMED
                5 -- PORT_NONE
        """
        if not self.active_state:
            return PORT_UNKNOWN

        if not re.match('[RML][ABCDEFGHIJKL]\d{1,2}', port):
            return PORT_NONE
        else:
            try:
                info = self.containers[port[0]][port[1:]]
                port_state = info[0]
            except (AttributeError, TypeError):
                port_state = PORT_UNKNOWN
            return port_state


class ColList(object):
    """Combine repeating elements in list comprehension"""

    def __init__(self):
        self._last = None

    def last(self):
        return self._last

    def next(self, v):
        self._last = v
        return self._last

    def reset(self):
        self._last = None


ACTION_STATES = {
    r'cooling tong .*': 'cooling',
    r'done': 'idle',
    r'drying tong': 'drying',
    r'get sample from port': 'get_sample',
    r'go home.*': 'to_home',
    r'gonio to dumbbell': 'to_placer',
    r'grip sample': 'get_sample',
    r'move to goniometer': 'to_gonio',
    r'moving to Dewar': 'to_dewar',
    r'put back dumbbell': 'put_magnet',
    r'release sample': 'put_sample',
    r'.*move to port.*': 'to_port',
    r'take dumbbell': 'get_magnet'
}


def _get_action(s):
    for k, v in ACTION_STATES.items():
        if re.match(k, s):
            return v


class Automounter(BasicAutomounter):
    """EPICS Based SAM Automounter object. 

    """
    SEQUENCES = {
        'mount': ['P0', 'P1', 'P2', 'P3', 'P6', 'P50', 'P52', 'P53', 'P52', 'P50', 'P4', 'P6', 'P3',
                  'P93', 'P5', 'P93', 'P16', 'P2', 'P18', 'P22', 'P24', 'P21', 'P23', 'P22',
                  'P18', 'P1', 'P0'],

        'mountnext': ['P0', 'P1', 'P2', 'P3', 'P2', 'P18', 'P22', 'P23', 'P21', 'P22', 'P18', 'P27',
                      'P26', 'P3', 'P6', 'P50', 'P52', 'P53', 'P52', 'P50', 'P52', 'P53', 'P52',
                      'P50', 'P4', 'P6', 'P3', 'P93', 'P5', 'P93', 'P16', 'P2', 'P18', 'P22',
                      'P24', 'P21', 'P23', 'P22', 'P18', 'P1', 'P0'],
        'dismount': ['P0', 'P1', 'P2', 'P3', 'P2', 'P18', 'P22', 'P23', 'P21', 'P22', 'P18', 'P27',
                     'P26', 'P3', 'P6', 'P50', 'P52', 'P53', 'P52', 'P50', 'P4', 'P6', 'P3',
                     'P2', 'P1', 'P0']
    }

    def __init__(self, pv_name, pv_name2=None):
        BasicAutomounter.__init__(self)
        self.name = 'SAM Automounter'
        self._pv_name = pv_name

        self.full_state = {}

        self.port_states = self.add_pv('%s:cassette:fbk' % pv_name)
        self.port_states.connect('changed', lambda x, y: self._parse_states(y))

        self.status_msg = self.add_pv('%s:sample:msg' % pv_name)
        self._warning = self.add_pv('%s:status:warning' % pv_name)
        self._status = self.add_pv('%s:status:state' % pv_name)
        self._sample = self.add_pv('%s:state:sts' % pv_name)
        self._magnet = self.add_pv('%s:state:mag' % pv_name)

        # Detailed Status
        self._normal = self.add_pv('%s:mod:normal' % pv_name)
        self._usr_disable = self.add_pv('%s:mnt:usrEnable' % pv_name)
        self._gonio_safe = self.add_pv('%s:goniPos:mntEn' % pv_name)
        self._mounted = self.add_pv('%s:status:mounted' % pv_name)
        self._position = self.add_pv('%s:state:curPnt' % pv_name)
        self._autofill = self.add_pv('%s:LN2Fill:en' % pv_name2)

        self._mount_cmd = self.add_pv('%s:mntX:opr' % pv_name)
        self._mount_param = self.add_pv('%s:mntX:param' % pv_name)
        self._dismount_cmd = self.add_pv('%s:dismntX:opr' % pv_name)
        self._dismount_param = self.add_pv('%s:dismntX:param' % pv_name)
        self._mount_next_cmd = self.add_pv('%s:mntNextX:opr' % pv_name)
        self._abort_cmd = self.add_pv('%s:abort:opr' % pv_name)

        self._wash_param = self.add_pv('%s:washX:param' % pv_name)
        self._bar_code = self.add_pv('%s:bcode:barcode' % pv_name)
        self._barcode_reset = self.add_pv('%s:bcode:clear' % pv_name)
        self._mount_enabled = self.add_pv('%s:mntEn' % pv_name)
        self._robot_busy = self.add_pv('%s:sample:sts' % pv_name)

        self._position.connect('changed', self._notify_progress)
        self._mounted.connect('changed', self._on_mount_changed)

        self._warning.connect('changed', self._on_status_warning)
        self.status_msg.connect('changed', self._send_message)
        self._gonio_safe.connect('changed', self._on_safety_changed)

        self._mount_enabled.connect('changed', self._on_state_changed)
        self._robot_busy.connect('changed', self._on_state_changed)
        self._status.connect('changed', self._on_state_changed)
        self._normal.connect('changed', self._on_state_changed)
        self._usr_disable.connect('changed', self._on_state_changed)
        self._autofill.connect('changed', self._on_state_changed)

        self._position.connect('changed', self._do_full_state)
        self._sample.connect('changed', self._do_full_state)
        self._magnet.connect('changed', self._do_full_state)
        self.status_msg.connect('changed', self._do_full_state)

        self.reset_progress([])

    def abort(self):
        """Abort all actions."""
        self._abort_cmd.put(1)

    def mount(self, port, wash=False, wait=False):
        """Mount the sample at the specified port, optionally washing the sample
        in the process. Does nothing if the requested port is already mounted.
        Dismounts the mounted sample prior to mounting if a another sample is 
        already mounted.
        
        Args:
            - `port` (str): Address to mount.
        
        Kwargs:
            - `wash` (bool): Whether to wash or not (default is False)
            - `wait` (bool): Run asynchronously or block (default is async, False)
        
        Returns:
            bool. True if the requested sample is successfully mounted, and False
            otherwise.
        """
        self._wait_for_enable(20)
        if not self.is_enabled():
            _logger.warning('(%s) command received while disabled. ' % self.name)
            self.set_state(preparing=False, message="Mounting Failed. Endstation was not ready.")
            self._on_state_changed(None, None)
            return False
        param = port[0].lower() + ' ' + port[2:] + ' ' + port[1]
        if wash:
            self._wash_param.put('1')
        else:
            self._wash_param.put('0')
        self._barcode_reset.put(1)

        # do nothing if sample is already mounted
        _mounted_port = self._mounted.get().strip()
        if _mounted_port == param:
            _logger.info('(%s) Sample at location `%s` already mounted.' % (self.name, port))
            self.set_state(message="Sample already mounted.", preparing=False)
            self._on_state_changed(None, None)
            return True

        # use mount_next if something already mounted
        if _mounted_port == '':  # nothing is mounted
            self._mount_param.put(param)
            self.reset_progress(self.SEQUENCES['mount'])
            self._mount_cmd.set(1)
        else:  # something is mounted
            dis_param = self._mounted.get()
            self._dismount_param.put(dis_param)
            self._mount_param.put(param)
            self.reset_progress(self.SEQUENCES['mountnext'])
            self._mount_next_cmd.set(1)

        _logger.info('(%s) Mount command: %s' % (self.name, port))
        if wait:
            success = self.wait_sequence(port) or (self.mounted_state and self.mounted_state[0] == port)
            if not success:
                self.set_state(message="Mounting failed!")
            return success
        return True

    def dismount(self, port=None, wait=False):
        """Dismount the sample into the specified port if provided, otherwise 
        dismount it to the original port from which it was mounted.
        
        Kwargs:
            - `port` (str): Destination address to dismount to, default is original
              port.
            - `wait` (bool): Run asynchronously or block (default is async, False)

        Returns:
            bool. True if successfully dismounted, and False otherwise.
        """
        self._wait_for_enable(20)
        if not self.is_enabled():
            _logger.warning('(%s) command received while disabled. ' % self.name)
            self.set_state(preparing=False, message="Dismount failed. Endstation was not ready")
            self._on_state_changed(None, None)
            return False

        if port is None:
            port = self._mounted.get().strip()

        if port == '':
            self.set_state(message='No sample to dismount', preparing=False)
            return False
        else:
            param = port[0].lower() + ' ' + port[2:] + ' ' + port[1]

        self._dismount_param.put(param)
        self.reset_progress(self.SEQUENCES['dismount'])
        self._dismount_cmd.set(1)

        _logger.info('(%s) Dismount command: %s' % (self.name, port))
        if wait:
            success = self.wait_sequence(None) or (self.mounted_state is None)
            if not success:
                self.set_state(message="Dismounting Failed!", preparing=False)
            return success
        return True

    def wait_sequence(self, port, timeout=240):
        poll = 0.05
        success = self.wait(start=True, stop=False, timeout=30)
        if not success:
            _logger.debug("Automounter did not start within the expected time")
            return False

        pct, pos, seqs_match, _ = self.progress_state
        _logger.debug("%s %s %s" % (pct, pos, seqs_match))
        while (not seqs_match) and timeout >= 0:
            pct, pos, seqs_match, _ = self.progress_state
            timeout -= poll
            time.sleep(poll)
        self.set_state(preparing=False)
        if timeout <= 0:
            _logger.warning('(%s) Operation Timed-out: Port %s' % (self.name, port))
            return False
        elif not seqs_match or self._mounted_port != port:
            _logger.warning('(%s) Operation failed: Port %s' % (self.name, port))
            return False

        return True

    def _wait_for_enable(self, timeout=30):
        while not self.is_enabled() and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)

    def _notify_progress(self, pv, pos):
        self._prog_sequence.append(pos)
        proc = ColList()
        actual_seq = '-'.join([proc.next(p) for p in self._prog_sequence if proc.last() != p])
        proc.reset()
        req_seq = '-'.join([proc.next(p) for p in self._command_sequence if proc.last() != p])

        if req_seq:
            sim = difflib.SequenceMatcher(a=actual_seq, b=req_seq)
            prog = sim.ratio()
            seqs_match = prog > 0.95 and req_seq.endswith(actual_seq[-5:])
            _logger.debug('Progress {:0.2f} {} {} %'.format(prog*100, seqs_match, pos))
            _logger.debug('Expected Sequence: {0}'.format(req_seq))
            _logger.debug('Actual Sequence:   {0}'.format(actual_seq))
        else:
            seqs_match = False
            prog = 0.0
        self.set_state(progress=(prog, pos, seqs_match, None))

        self._signal_states()

    def _do_full_state(self, obj, val):
        _SSTATES = ['', 'picker', 'placer', 'tong', 'gonio']
        _MSTATES = {'in cradle': 'cradle', 'on tong': 'tong'}
        act = _get_action(self.status_msg.get())
        self.full_state['pos'] = self._position.get()
        self.full_state['magnet'] = _MSTATES.get(self._magnet.get(), '')
        self.full_state['sample'] = _SSTATES[self._sample.get()]
        if act:
            self.full_state['action'] = act
        self._signal_states()

    def _signal_states(self):
        _logger.debug('(%s) state changed to: %s' % (self.name, [':'.join(pair) for pair in self.full_state.items()]))

    def reset_progress(self, command_seq):
        self._prog_sequence = [self._position.get()]
        self._command_sequence = command_seq
        self.set_state(progress=(0.0, self._position.get(), False, None))

    def _on_safety_changed(self, pv, st):
        if self.busy_state and st != 1:
            msg = "Endstation became unsafe while automounter was busy"
            self.abort()
            _logger.warning(msg)

    def _on_state_changed(self, pv, st):
        normal = self._normal.get()
        state_str = self._status.get()
        usr_enabled = self._usr_disable.get()
        mnt_enabled = self._mount_enabled.get()
        robot_busy = self._robot_busy.get()
        autofill_enabled = self._autofill.get()

        try:
            state_str = state_str.split()[0].strip()
        except IndexError:
            return
        hlth_msg = ''
        hlth_code = 0

        if normal == 0:
            status = 'ready'
        else:
            status = 'fault'
            hlth_msg += ' Needs Staff Attention.'
            hlth_code |= 4

        msg = ''
        if mnt_enabled != 1:
            # msg = 'Not ready for mounting'
            pass

        if state_str not in ['robot_standby', 'idle'] and robot_busy == 1:
            if state_str == 'robot_standby':
                msg = 'Not ready for mounting'
            busy = True
        else:
            busy = False

        if usr_enabled == 0:
            hlth_msg += ' Disabled by staff.'
            hlth_code |= 16

        if autofill_enabled == 0:
            hlth_msg += ' Autofill Disabled.'
            hlth_code |= 0

        self.set_state(busy=busy, enabled=(mnt_enabled == 1), status=status,
                       health=(hlth_code, 'status', hlth_msg))
        if msg:
            self.set_state(message=msg)

    def _on_mount_changed(self, pv, val):
        vl = val.split()
        if val.strip() == "":
            port = None
            if self._mounted_port != port:
                self.set_state(mounted=None)
                self._mounted_port = port
                _logger.debug('Sample dismounted')
        elif len(vl) >= 3:
            port = vl[0].upper() + vl[2] + vl[1]
            try:
                barcode = self._bar_code.get()
            except:
                barcode = ''
            if port != self._mounted_port:
                self.set_state(mounted=(port, barcode))
                self._mounted_port = port
                _logger.debug('Mounted:  port=%s barcode=%s' % (port, barcode))

    def _send_message(self, pv, msg):
        if msg.strip() == 'done':
            msg = "Ready."
        msg = _format_msg(msg)
        self.set_state(message=msg)

    def _on_status_warning(self, pv, val):
        if val.strip() != '' and val != self._last_warn:
            val = _format_msg(val)
            _logger.warn('%s' % val)
            self._last_warn = val
            # Warnings expire
            if (time.time() - pv._time) < 10:
                self.set_state(health=(1, 'notices', self._last_warn))
            else:
                self.set_state(health=(0, 'notices'))


class ManualMounter(BasicAutomounter):
    """Manual Mounter objects."""

    def __init__(self):
        BasicAutomounter.__init__(self)
        self.sample = None

    def mount(self, state):
        self.set_state(mounted=state)

    def dismount(self, state):
        self.set_state(mounted=None)


_TEST_STATE = '31uuuuuuuuuujuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu---\
-----------------------------01uuuuuuuuuuuumuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu\
uuuuuuuuuuuuuuuu0uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu20------uu------uu------\
uu------uu------uu------uu------uu------uu------uu------uu------uu------u'
_TEST_STATE2 = '31uuu00000uuj11u1uuuuuuuuuuuuuuuu111111uuuuuuuuuuuuuuuuuuuuuuuuuu---\
-----------------------------41uuuuuuuuuuuumuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu\
uuuuuuuuuuuuuuuu0uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu20------uu------uu------\
uu------uu------uu------uu------uu------uu------uu------uu------uu------u'


class SimAutomounter(BasicAutomounter):
    def __init__(self):
        BasicAutomounter.__init__(self)
        self._parse_states(_TEST_STATE2)
        from bcm.device.misc import SimPositioner
        self.nitrogen_level = SimPositioner('Automounter Cryogen Level', 80.0, '%')
        self.set_state(
            active=True, health=(0, ''), status='ready',
            message='Ready', enabled=True,
            preparing=False,
        )

    def mount(self, port, wash=False, wait=False):
        if self.is_busy():
            return False
        self._sim_mount_start(port)
        GObject.timeout_add(5000, self._sim_mount_done, port)
        if wait:
            return self.wait(start=True, stop=True)
        return True

    def dismount(self, port=None, wait=False):
        if self.busy_state:
            return False
        if self._mounted_port is not None:
            self._sim_mount_start(None)
            GObject.timeout_add(10000, self._sim_dismount_done)
        if wait:
            return self.wait(start=True, stop=True)
        return True

    def _sim_mount_done(self, port=None):
        self.set_state(
            busy=False, status='ready', enabled=True,
            message="Sample mounted. Drying gripper.",
            preparing=False,
            mounted=(port, '')
        )
        self._mounted_port = port
        self.set_state(progress=(1.0, 'unknown', 'on gonio', 'in cradle'))
        GObject.timeout_add(10000, self._sim_dry_done)

    def _sim_dismount_done(self):
        self.set_state(
            busy=False, status='ready', enabled=True,
            message="Sample dismounted. Drying gripper.",
            preparing=False,
            mounted=None
        )
        self._mounted_port = None
        self.set_state(progress=(1.0, 'unknown', 'in port', 'in cradle'))
        GObject.timeout_add(10000, self._sim_dry_done)

    def _sim_mount_start(self, port=None):
        if port is None:
            msg = 'Dismounting crystal'
        else:
            msg = 'Mounting sample at %s' % port
        self.set_state(busy=True, message=msg)

    def _sim_dry_done(self):
        self.set_state(status='ready', busy=False, message='Ready.')

    def is_mounted(self, port=None):
        if port is None:
            return self.mounted_state is not None
        if self.mounted_state is None:
            return False
        else:
            return self.mounted_state[0] == port


def _format_msg(txt):
    if txt.strip() == '':
        return ''
    txt = ". ".join([p.capitalize().strip() for p in txt.lower().split('. ')]).strip()
    if txt[-1] != '.':
        txt = txt + '.'
    return txt


def _format_error_string(need_list):
    nd_dict = {
        'calib': 'calibration',
        'inspect': 'inspection',
        'action': 'action'
    }
    needs = []
    calib = []
    for t in need_list:
        ts = t.split(':')
        if len(ts) > 1:
            if ts[0] == 'calib':
                calib.append(ts[1])
            else:
                needs.append(ts[1] + ' ' + nd_dict[ts[0]])
        else:
            needs.append(t)
    if len(calib) > 0:
        needs.append('calibration')
    if len(needs) > 0:
        needs_txt = 'Needs ' + ', '.join(needs)
    else:
        needs_txt = ''
    return needs_txt
