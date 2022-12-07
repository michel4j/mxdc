import time

from enum import Enum
from gi.repository import GLib
from zope.interface import implementer

from mxdc import Signal, Device, Property
from mxdc.utils.log import get_module_logger
from .interfaces import IModeManager

# setup module logger with a default handler
logger = get_module_logger(__name__)


@implementer(IModeManager)
class BaseManager(Device):
    """
    Base Mode Manager. A device to manage beamline modes

    Signals:
        - **mode**: beamline mode

    Properties:
        - **mode**: beamline mode
    """

    class ModeType(Enum):
        MOUNT, CENTER, COLLECT, SCAN, ALIGN, BUSY, UNKNOWN = list(range(7))

    ACTIVITY_MAP = {
        ModeType.MOUNT: 'mounting',
        ModeType.CENTER: 'centering',
        ModeType.COLLECT: 'collecting',
        ModeType.ALIGN: 'aligning',
        ModeType.SCAN: 'scanning',
        ModeType.UNKNOWN: 'unknown',
    }

    class Signals :
        mode = Signal("mode", arg_types=(object,))
        activity = Signal("activity", arg_types=(str,))

    # Properties
    mode = Property(type=object)

    def __init__(self, name='Beamline Modes'):
        super().__init__()
        self.name = name
        self.props.mode = self.ModeType.UNKNOWN

    def wait(self, *modes, timeout=30):
        """
        Wait for the one of specified modes.

        :param modes: a list of Mode ENUMS or strings to wait for
        :param timeout: maximum time in seconds to wait before failing.
        :return: (bool), False if wait timed-out
        """
        poll = 0.01
        success = True
        mode_set = {m if isinstance(m, self.ModeType) else self.ModeType[m] for m in modes}
        if self.props.mode in mode_set:
            logger.debug(f'Already in requested mode: {mode_set}')
            return success

        expire_time = time.time() + timeout
        if not mode_set:
            logger.debug('Waiting for mode manager stop')
            while time.time() < expire_time:
                time.sleep(poll)
                if not self.is_busy():
                    break
            else:
                logger.debug('Timed-out waiting for mode manager stop')
                success = False
        else:
            logger.debug(f'Waiting for {self.name}: {mode_set}')
            while time.time() < expire_time:
                time.sleep(poll)
                if self.props.mode in mode_set:
                    break
            else:
                logger.debug('Timed-out waiting for mode manager stop')
                success = False

        return success

    def mount(self, wait=False):
        """
        Switch to Mount mode

        :param wait: wait for switch to complete
        """
        raise NotImplementedError('Sub-classes must implement "mount"')

    def center(self, wait=False):
        """
        Switch to Center mode

        :param wait: wait for switch to complete
        """
        raise NotImplementedError('Sub-classes must implement "center"')

    def collect(self, wait=False):
        """
        Switch to Collect mode

        :param wait: wait for switch to complete
        """
        raise NotImplementedError('Sub-classes must implement "collect"')

    def align(self, wait=False):
        """
        Switch to Align mode

        :param wait: wait for switch to complete
        """
        raise NotImplementedError('Sub-classes must implement "align"')

    def scan(self, wait=False):
        """
        Switch to Scan mode

        :param wait: wait for switch to complete
        """
        raise NotImplementedError('Sub-classes must implement "scan"')

    def get_mode(self):
        """
        Return the current mode
        """
        return self.props.mode


class SimModeManager(BaseManager):
    """
    Simulated Mode Manager.
    """

    def __init__(self):
        super().__init__(name='Beamline Modes')
        self.mode_delay = {
            self.ModeType.MOUNT: 4,
            self.ModeType.CENTER: 3,
            self.ModeType.COLLECT: 2,
            self.ModeType.SCAN: 2,
            self.ModeType.ALIGN: 8,

        }
        self.set_state(
            active=True, busy=False, health=(0, 'faults', ''),
            mode=self.ModeType.MOUNT, activity=self.ACTIVITY_MAP[self.ModeType.MOUNT]
        )

    def _switch_mode(self, mode):
        self.set_state(
            busy=True, message='Switching mode ...',
            mode=self.ModeType.BUSY
        )
        GLib.timeout_add(self.mode_delay[mode] * 1000, self._notify_mode, mode)

    def _notify_mode(self, mode):
        activity = self.ACTIVITY_MAP.get(mode, 'unknown')
        self.props.mode = mode
        self.set_state(busy=False, activity=activity, mode=mode)

    def mount(self, wait=False):
        """
        Switch to Mount mode
        :param wait: wait for switch to complete
        """
        self._switch_mode(self.ModeType.MOUNT)
        if wait:
            self.wait(self.ModeType.MOUNT)

    def center(self, wait=False):
        """
        Switch to center mode
        :param wait: wait for switch to complete
        """
        self._switch_mode(self.ModeType.CENTER)
        if wait:
            self.wait(self.ModeType.CENTER)

    def collect(self, wait=False):
        """
        Switch to Collect mode
        :param wait: wait for switch to complete
        """
        self._switch_mode(self.ModeType.COLLECT)
        if wait:
            self.wait(self.ModeType.COLLECT)

    def scan(self, wait=False):
        """
        Switch to Scan mode
        :param wait: wait for switch to complete
        """
        self._switch_mode(self.ModeType.SCAN)
        if wait:
            self.wait(self.ModeType.SCAN)

    def align(self, wait=False):
        """
        Switch to Align mode

        :param wait: wait for switch to complete
        """
        self._switch_mode(self.ModeType.ALIGN)
        if wait:
            self.wait(self.ModeType.ALIGN)


class MD2Manager(BaseManager):
    """
    MD2 Based Mode Manager.
    """

    def __init__(self, root):
        super().__init__(name='Beamline Modes')

        self.mode_cmd = self.add_pv(f"{root}:CurrentPhase")
        self.mode_fbk = self.add_pv(f"{root}:CurrentPhase")
        self.state_fbk = self.add_pv("{root}:State")
        self.mca_nozzle = self.add_pv(f"{root}:FluoDetectorIsBack")

        # signal handlers
        self.mode_fbk.connect('changed', self.on_status_changed)
        self.state_fbk.connect('changed', self.on_status_changed)

        # mode types
        self.int_to_mode = {
            0: self.ModeType.CENTER,
            1: self.ModeType.ALIGN,
            2: self.ModeType.COLLECT,
            3: self.ModeType.MOUNT,
            4: self.ModeType.UNKNOWN,
            5: self.ModeType.BUSY,
            6: self.ModeType.ALIGN,
        }
        self.mode_to_int = {
            self.ModeType.CENTER: 0,
            self.ModeType.ALIGN: 1,
            self.ModeType.COLLECT: 2,
            self.ModeType.MOUNT: 3,
        }

    def on_status_changed(self, *args, **kwargs):
        state = self.state_fbk.get()
        mode_val = self.mode_fbk.get()
        mca_pos = self.mca_nozzle.get()
        message = ''
        if state in [5, 6, 7, 8]:
            health = (0, 'faults', '')
            busy = True
            current_mode = self.ModeType.BUSY
            message = 'Switching mode ...'
        elif state in [11, 12, 13, 14]:
            health = (2, 'faults', 'Gonio Error')
            busy = False
            current_mode = self.ModeType.UNKNOWN
        else:
            current_mode = self.int_to_mode.get(mode_val, self.ModeType.UNKNOWN)
            if mca_pos == 1 and current_mode == self.ModeType.COLLECT:
                current_mode = self.ModeType.SCAN
            health = (0, 'faults', '')
            busy = False

        self.props.mode = current_mode
        activity = self.ACTIVITY_MAP.get(current_mode, 'unknown')
        self.set_state(health=health, busy=busy, mode=current_mode, message=message, activity=activity)

    def mount(self, wait=False):
        """
        Switch to Mount mode
        :param wait: wait for switch to complete
        """
        self.mode_cmd.put(self.mode_to_int[self.ModeType.MOUNT])
        if wait:
            self.wait(self.ModeType.MOUNT)

    def center(self, wait=False):
        """
        Switch to Mount mode
        :param wait: wait for switch to complete
        """
        self.mode_cmd.put(self.mode_to_int[self.ModeType.CENTER])
        if wait:
            self.wait(self.ModeType.CENTER)

    def collect(self, wait=False):
        """
        Switch to Mount mode
        :param wait: wait for switch to complete
        """
        # self.fluor_cmd.put(1)
        self.mode_cmd.put(self.mode_to_int[self.ModeType.COLLECT])
        if wait:
            self.wait(self.ModeType.COLLECT)

    def align(self, wait=False):
        """
        Switch to Mount mode
        :param wait: wait for switch to complete
        """
        self.mode_cmd.put(self.mode_to_int[self.ModeType.ALIGN])
        if wait:
            self.wait(self.ModeType.ALIGN)

    def scan(self, wait=False):
        """
        Switch to Scan mode
        :param wait: wait for switch to complete
        """
        self.mca_nozzle.put(0)
        if wait:
            self.wait(self.ModeType.SCAN)


class ModeManager(BaseManager):
    """
    CMCF BL Mode Mode Manager.
    """

    def __init__(self, root):
        super().__init__(name='Beamline Modes')

        self.mode_commands = {
            self.ModeType.MOUNT: self.add_pv(f'{root}:Mount:cmd'),
            self.ModeType.CENTER: self.add_pv(f'{root}:Center:cmd'),
            self.ModeType.COLLECT: self.add_pv(f'{root}:Collect:cmd'),
            self.ModeType.ALIGN: self.add_pv(f'{root}:Align:cmd'),
            self.ModeType.SCAN: self.add_pv(f'{root}:Scan:cmd'),
        }

        self.mode_fbk = self.add_pv("{}:mode:fbk".format(root))
        self.moving_fbk = self.add_pv("{}:moving".format(root))
        self.calib_fbk = self.add_pv("{}:calibrated".format(root))

        # signal handlers
        self.mode_fbk.connect('changed', self.on_status_changed)
        self.moving_fbk.connect('changed', self.on_status_changed)
        self.calib_fbk.connect('changed', self.on_status_changed)

        # mode types
        self.int_to_mode = {
            0: self.ModeType.UNKNOWN,
            1: self.ModeType.MOUNT,
            2: self.ModeType.CENTER,
            3: self.ModeType.COLLECT,
            4: self.ModeType.ALIGN,
            5: self.ModeType.SCAN,
        }

    def on_status_changed(self, *args, **kwargs):
        state = self.mode_fbk.get()
        moving = self.moving_fbk.get()
        calib = self.calib_fbk.get()
        message = ''
        if not calib:
            health = (2, 'faults', 'Devices Not Calibrated')
            busy = False
            current_mode = self.ModeType.UNKNOWN
        elif moving:
            health = (0, 'faults', '')
            busy = True
            current_mode = self.ModeType.BUSY
            message = 'Switching mode ...'
        else:
            current_mode = self.int_to_mode.get(state, self.ModeType.UNKNOWN)
            health = (0, 'faults', '')
            busy = False

        self.props.mode = current_mode
        activity = self.ACTIVITY_MAP.get(current_mode, "unknown")
        self.set_state(health=health, busy=busy, mode=current_mode, activity=activity, message=message)

    def mount(self, wait=False):
        """
        Switch to Mount mode
        :param wait: wait for switch to complete
        """
        self.mode_commands[self.ModeType.MOUNT].put(1)
        if wait:
            self.wait(self.ModeType.MOUNT)

    def center(self, wait=False):
        """
        Switch to Center mode
        :param wait: wait for switch to complete
        """
        logger.debug('Switching to collect mode ...')
        self.mode_commands[self.ModeType.CENTER].put(1)
        if wait:
            self.wait(self.ModeType.CENTER)

    def collect(self, wait=False):
        """
        Switch to Collect mode
        :param wait: wait for switch to complete
        """
        logger.debug('Switching to collect mode ...')
        self.mode_commands[self.ModeType.COLLECT].put(1)
        if wait:
            self.wait(self.ModeType.COLLECT)

    def align(self, wait=False):
        """
        Switch to Align mode
        :param wait: wait for switch to complete
        """
        logger.debug('Switching to collect mode ...')
        self.mode_commands[self.ModeType.ALIGN].put(1)
        if wait:
            self.wait(self.ModeType.ALIGN)

    def scan(self, wait=False):
        """
        Switch to Scan mode
        :param wait: wait for switch to complete
        """
        self.mode_commands[self.ModeType.SCAN].put(1)
        if wait:
            self.wait(self.ModeType.SCAN)