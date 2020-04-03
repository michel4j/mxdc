from mxdc.devices.automounter import AutoMounter, State, logger
from mxdc.utils.automounter import Port, Basket


CATS_DEWAR = {
    'L1A': Basket('L1A', 0.1667, 0.0833),
    'L1B': Basket('L1B', 0.0833, 0.2292),
    'L1C': Basket('L1C', 0.25, 0.2292),
    'L2A': Basket('L2A', 0.5, 0.6667),
    'L2B': Basket('L2B', 0.4167, 0.8125),
    'L2C': Basket('L2C', 0.5833, 0.8125),
    'L3A': Basket('L3A', 0.8333, 0.0833),
    'L3B': Basket('L3B', 0.75, 0.2292),
    'L3C': Basket('L3C', 0.9167, 0.2292),
}


class CATSMessages(object):
    @staticmethod
    def trajectory(message):
        return {
            'getput': 'Switching sample ...',
            'get': 'Dismounting sample ...',
            'getputplate': 'Switching Plate ...',
            'getplate': 'Dismounting plate ...',
            'putplate': 'Mounting plate ...',
            'put': 'Mounting sample ...',
            'dry': 'Drying gripper ...',
            'soak': 'Soaking ...',
            'home': 'Going home ...',

        }.get(message.lower().strip())

    @staticmethod
    def errors(message):
        replacements = {
            'high level alarm Dew1': 'Dewar LN2 topped up',
            'WAIT for RdTrsf condition / 9 not TRUE': 'Waiting for endstation-ready ...',
            'WAIT for SplOn condition / not TRUE / 1': 'Checking sample on gonio ...',
        }
        for old, new in list(replacements.items()):
            message = message.replace(old, new)
        if message:
            return message


class CATS(AutoMounter):
    """
    An abstraction fot the IRELEC CATS Auto Mounter

    :param root:  Root name of device process variables
    """

    PUCKS = [
        '',
        'L1A', 'L2A', 'L3A', 'L1B', 'L2B', 'L3B', 'L1C', 'L2C', 'L3C',
    ]
    PLATES = [
        'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8'
    ]

    def __init__(self, root):
        super(CATS, self).__init__()
        self.name = 'CATS Auto Mounter'
        self.configure(layout=CATS_DEWAR)

        self.power_cmd = self.add_pv('{}:CMD:power'.format(root))
        self.mount_cmd = self.add_pv('{}:CMD:mount'.format(root))
        self.dismount_cmd = self.add_pv('{}:CMD:dismount'.format(root))
        self.next_sample = self.add_pv('{}:PAR:nextPort'.format(root))

        # extra commands, prefer simplified ones above
        self.abort_cmd = self.add_pv('{}:CMD:abort'.format(root))
        self.reset_cmd = self.add_pv('{}:CMD:reset'.format(root))
        self.clear_cmd = self.add_pv('{}:CMD:clear'.format(root))
        self.getput_cmd = self.add_pv('{}:CMD:getPut'.format(root))
        self.get_cmd = self.add_pv('{}:CMD:get'.format(root))
        self.put_cmd = self.add_pv('{}:CMD:put'.format(root))

        # plates
        self.tilt_plate_cmd = self.add_pv('{}:CMD:tiltPlate'.format(root))
        self.well_param = self.add_pv('{}:PAR:well'.format(root))
        self.adjust_x = self.add_pv('{}:PAR:adjustX'.format(root))
        self.adjust_y = self.add_pv('{}:PAR:adjustY'.format(root))
        self.adjust_z = self.add_pv('{}:PAR:adjustZ'.format(root))
        self.plate_ang = self.add_pv('{}:PAR:plateAng'.format(root))
        self.getputplate_cmd = self.add_pv('{}:CMD:getPutPlate'.format(root))
        self.putplate_cmd = self.add_pv('{}:CMD:putPlate'.format(root))
        self.getplate_cmd = self.add_pv('{}:CMD:getPlate'.format(root))

        # feedback
        self.status_fbk = self.add_pv('{}:STATUS'.format(root))
        self.power_fbk = self.add_pv('{}:STATE:power'.format(root))
        self.enabled_fbk = self.add_pv('{}:ENABLED'.format(root))
        self.connected_fbk = self.add_pv('{}:CONNECTED'.format(root))
        self.mode_fbk = self.add_pv('{}:STATE:auto'.format(root))
        self.cmd_busy_fbk = self.add_pv('{}:STATE:running'.format(root))
        self.ln2_fbk = self.add_pv('{}:STATE:D1LN2'.format(root))
        self.message_fbk = self.add_pv('{}:LOG'.format(root))
        self.trajectory_fbk = self.add_pv('{}:STATE:path'.format(root))
        self.mounted_fbk = self.add_pv('{}:STATE:onDiff'.format(root))
        self.barcode_fbk = self.add_pv('{}:STATE:barcode'.format(root))
        self.tooled_fbk = self.add_pv('{}:STATE:onTool'.format(root))
        self.puck_probe_fbk = self.add_pv('{}:STATE:pucks1'.format(root))

        # connect monitors
        self.trajectory_fbk.connect('changed', self.on_message, CATSMessages.trajectory)
        self.puck_probe_fbk.connect('changed', self.on_pucks_changed)
        self.mounted_fbk.connect('changed', self.on_sample_changed)
        self.status_fbk.connect('change', self.on_status_changed)

    def is_mountable(self, port):
        if self.is_valid(port):
            return (self.ports.get(port, Port.UNKNOWN) not in [Port.BAD, Port.EMPTY]) or port[0] == 'P'
        return False

    def is_valid(self, port):
        if port:
            if port[:3] in self.PUCKS:
                try:
                    pin = int(port[3:])
                    return (pin > 0) and  (pin <= 16)
                except ValueError:
                    return False
            elif port[:2] in self.PLATES:
                well = port[2:]
                if well and well[0] in 'ABCDEFGH':
                    try:
                        sample = int(port[1:])
                        return (sample > 0) and (sample <= 24)
                    except ValueError:
                        return False
        return False

    def power_on(self):
        if self.power_fbk.get() == 0:
            self.power_cmd.put(1)

    def mount(self, port, wait=True):
        self.power_on()
        enabled = self.wait(states={State.IDLE, State.PREPARING}, timeout=240)
        if not enabled:
            logger.warning('{}: not ready. command ignored!'.format(self.name))
            self.set_state(message="Not ready, command ignored!")
            self.cancel()
            return False
        elif self.is_mounted(port):
            logger.info('{}: Sample {} already mounted.'.format(self.name, port))
            self.set_state(message="Sample already mounted!")
            return True
        elif self.is_valid(port) and self.is_mountable(port):
            self.next_sample.put(port)
            logger.info('{}: Mounting Sample: {}'.format(self.name, port))
            if self.is_mounted():
                self.mount_cmd.put(1)  # translates to getput, or getputplate within bobcats
                success = self.wait(states={State.BUSY}, timeout=5)
            else:
                self.mount_cmd.put(1) # translates to put, putplate  within bobcats
                success = self.wait(states={State.BUSY}, timeout=5)

            if wait and success:
                success = self.wait(states={State.STANDBY, State.IDLE}, timeout=240)
                if not success:
                    self.set_state(message="Mounting timed out!")
                return success
            else:
                return success
        else:
            logger.warning('{}: Invalid Port. Command ignored!'.format(self.name))
            self.set_state(message="Invalid Port. Command ignored!")

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
            self.dis_mount_cmd.put(1)
            logger.info('{}: Dismounting sample.'.format(self.name, ))
            success = self.wait(states={State.BUSY}, timeout=5)
            if wait and success:
                success = self.wait(states={State.STANDBY, State.IDLE}, timeout=240)
                if not success:
                    self.set_state(message="Dismount timed out!")
                return success
            else:
                return success

    def abort(self):
        self.abort_cmd.put(1)

    def on_pucks_changed(self, obj, states):
        """
        Callback when the puck detection state changes

        :param obj: Process Variable which triggered the callback
        :param states: New states, an integer representing the bits of the puck states, only 9 bits are read
        """

        puck_states = bin(states)[2:].ljust(9, '0') # convert int to binary, and zero fill to at least 9 bits
        pucks = {self.PUCKS[i + 1] for i, bit in enumerate(puck_states) if bit == '1'}
        states = {
            '{}{}'.format(puck, 1 + pin): Port.UNKNOWN for pin in range(16) for puck in pucks
        }
        self.props.ports = states
        self.props.containers = pucks
        self.set_state(health=(0, 'pucks', ''))

    def on_sample_changed(self, *args):
        """
        Called when the currently mounted sample changes
        """
        mounted = self.mounted_fbk.get()
        port = self.props.sample.get('port')
        ports = self.ports
        if mounted:
            port = mounted
            barcode = self.barcode_fbk.get()
            ports[port] = Port.MOUNTED
            self.props.sample = {
                'port': port,
                'barcode': barcode
            }
        else:
            if ports.get(port) == Port.MOUNTED:
                ports[port] = Port.UNKNOWN
                self.set_state(message='Sample dismounted')
            self.props.sample = {}
        self.configure(ports=ports)

    def on_status_changed(self, *args):
        fbk_value = self.status_fbk.get()
        if fbk_value == 0:
            status = State.PREPARING if self.status == State.PREPARING else State.IDLE
        elif fbk_value == 3:
            status = State.ERROR
        elif fbk_value == 1:
            status = State.WAITING
        elif fbk_value == 2:
            status = State.BUSY
        else:
            status = State.ERROR
        self.configure(status=status)
