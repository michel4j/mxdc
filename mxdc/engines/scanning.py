import inspect
import os
import time
from datetime import datetime

import numpy
import pytz
from zope.interface import implementer

from mxdc import Registry, Signal, Engine
from mxdc.devices.interfaces import IMotor, ICounter
from mxdc.engines.interfaces import IScan, IScanPlotter
from mxdc.utils import misc, xdi
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)

MIN_CNTSCAN_UPDATE = 0.01  # minimum time between updates for continuous scans


@implementer(IScan)
class BasicScan(Engine):
    """
    Base Class for all Scan engines.

    Signals:
        - new-point: (object,) new scan point
        - new-row: (int,) new scan row for multi-row scans
        - message: (str,) messages
    """
    name = 'Basic Scan'

    class Signals:
        new_point = Signal('new-point', arg_types=(object,))
        new_row = Signal('new-row', arg_types=(int, ))
        message = Signal('message', arg_types=(str,))

    def __init__(self):
        super().__init__()
        self.name = misc.normalize_name(self.__class__.__name__)
        self.config = misc.DotDict({})

        # data variables
        self.data = None
        self.data_units = {}
        self.raw_data = []
        self.data_row = []
        self.data_ids = {}
        self.data_type = {}
        self.data_scale = []
        self.extending = False
        
        self.plotter = Registry.get_utility(IScanPlotter)
        if self.plotter:
            self.plotter.link_scan(self)

    def configure(self, **kwargs):
        """
        Set configuration parameters

        :param kwargs: keyword, value pairs to add to configuration
        :return: config object, fields are dictionary keywords
        """
        self.config.update(kwargs)
        return self.config

    def setup(self, motors, counters, i0=None):
        """
        Setup scan data configuration

        :param motors: sequence of motors
        :param counters: sequence of counters
        :param i0: reference counter
        """

        self.data_units = {
            misc.normalize_name(m.name): m.units for m in motors
        }
        motor_names = [misc.normalize_name(m.name) for m in motors]

        if self.config.i0 is not None:
            counters = [*counters, i0]
            self.config.start_channel = len(motor_names) + 1  # channel 1 is i0 scaled version of channel 2
            scaled_names = ['norm_{}'.format(misc.normalize_name(counters[0].name))]
        else:
            self.config.start_channel = len(motor_names)  # no i0 therefore no scaled channel
            scaled_names = []

        self.config.counters = [ICounter(counter) for counter in counters]  # adapt counters
        names = motor_names + scaled_names + [misc.normalize_name(counter.name) for counter in counters]

        self.data_type = {
            'names': names,
            'formats': ['f4'] * len(names)
        }

        # tuples of channel names that are on the same scale
        self.data_scale = []
        self.data_scale.append(tuple(names[1:self.config.start_channel + 1]))
        self.data_scale += [(name,) for name in names[(self.config.start_channel + 1):]]

    def get_specs(self):
        """
        Get the scan specification describing the scan and scan data

        :return: dictionary
        """
        return {
            'start_time': self.config.get('start_time'),
            'scan_type': misc.normalize_name(self.__class__.__name__),
            'data_type': self.data_type,
            'data_scale': self.data_scale,
            'units': self.data_units,
            'extension': self.extending,
        }

    def finalize(self):
        """
        Convert the data after the scan is complete and finalize before wrapping up

        :param data: a list of tuples representing the acquired data
        """
        self.data = numpy.array(self.raw_data, self.data_type)

    def extend(self, amount):
        """
        Extend the scan by the given amount. Subclasses should update the configuration before calling the
        base class extend() method since this method will start the scan.

        :param amount: amount to extend scan by
        """
        self.extending = True
        self.start()

    def start(self):
        """
        Start the scan engine
        """
        self.stopped = False
        super().start()

    def run(self):
        """
        Run the scan in the current execution loop. Normally executed in a thread when the start
        method is called. Sub-classes are discouraged from re-implementing this method. Instead override
        the :func:`scan` method.
        """

        if not self.extending:
            self.config.update(start_time=datetime.now(tz=pytz.utc))
            self.raw_data = []
            self.data_row = [numpy.nan] * len(self.data_type['names'])
            self.data_row[-1] = 1.0  # make sure last column default (i0) is 1.0

        self.set_state(busy=True, message='Scan in progress', started=self.get_specs())
        self.scan()
        self.config.update(end_time=datetime.now(tz=pytz.utc))
        self.finalize()
        self.set_state(busy=False, done=self.config, message='Scan complete!')
        self.extending = False

    def scan(self):
        """
        Scan implementation. Details must be implemented by sub-classes
        """
        raise NotImplementedError('Derived classes must implement scan method')

    def prepare_xdi(self):
        """
        Prepare XDI file for saving

        :return: xdi_data object
        """
        comments = inspect.getdoc(self)
        xdi_data = xdi.XDIData(data=self.data, comments=comments, version='MxDC')
        xdi_data['Facility.name'] = self.beamline.config['facility']
        xdi_data['Facility.xray_source'] = self.beamline.config['source']
        xdi_data['Beamline.name'] = self.beamline.name
        xdi_data['Mono.name'] = self.beamline.config.get('mono', 'Si 111')
        xdi_data['Scan.start_time'] = self.config.get('start_time', datetime.now(tz=pytz.utc))
        xdi_data['Scan.end_time'] = self.config.get('end_time', datetime.now(tz=pytz.utc))
        xdi_data['MxDC.scan_type'] = self.get_specs()['scan_type']

        if 'sample' in self.config:
            xdi_data['Sample.name'] = self.config['sample'].get('name', 'unknown')
            xdi_data['Sample.id'] = self.config['sample'].get('sample_id', 'unknown')
            xdi_data['Sample.temperature'] = (self.beamline.cryojet.temperature, 'K')
            xdi_data['Sample.group'] = self.config['sample'].get('group', 'unknown')

        for i, name in enumerate(self.data_type['names']):
            key = 'Column.{}'.format(i + 1)
            xdi_data[key] = (name, self.data_units.get(name))
        return xdi_data

    def save(self, filename=None):
        """
        Save the scan data.

        :param filename: full path to data file. If None, a file name will be generated.
        :return: the file name of the saved file
        """
        if filename is None:
            # save in ~/Scans/YYYY/Mmm/HHMMSS.xdi.gz
            directory = self.config.get(
                'directory',
                os.path.join(
                    misc.get_project_home(),
                    'Scans',
                    time.strftime('%Y'),
                    time.strftime('%b')
                )
            )
            name = '{}-{}.xdi.gz'.format(self.data_type['names'][0], time.strftime('%H%M%S'))
            if not os.path.exists(directory):
                os.makedirs(directory)
            filename = os.path.join(directory, name)

        logger.debug('Saving XDI: {}'.format(filename))
        xdi_data = self.prepare_xdi()
        xdi_data.save(filename)
        return filename


class SlewScan(BasicScan):
    """
    A Continuous scan of a single motor.

    :param m1: motor or positioner
    :param p1: start position
    :param p2: end position
    :param counters: one or more counters
    :param i0: reference counter
    :param speed:  scan speed of m1
    """

    def __init__(self, m1, p1, p2, *counters, i0=None, speed=None):
        super().__init__()
        assert len(counters) > 0, ValueError('At least one counter is required.')
        self.configure(
            m1=IMotor(m1),
            p1=p1,
            p2=p2,
            counters=counters,
            i0=i0,
            speed=speed
        )
        self.setup((self.config.m1,), self.config.counters, i0)
        self.last_update = time.time()

    def on_data(self, device, value, channel):
        self.data_row[channel] = value
        # When i0 is specified, add scaled value of first channel, last channel is i0
        if self.config.i0 and channel == self.config.start_channel and len(self.raw_data):
            self.data_row[1] = value * self.raw_data[0][-1] / self.data_row[-1]
        row = tuple(self.data_row)
        self.raw_data.append(row)

        progress = abs((self.data_row[0] - self.config.p1)/(self.config.p2 - self.config.p1))
        self.set_state(new_point=(row,), progress=(progress, ''))
        self.last_update = time.time()

    def extend(self, amount):
        direction = numpy.sign(self.config.p2 - self.config.p1)
        self.config.p1 = self.config.p2
        self.config.p2 += direction * abs(amount)
        super().extend(amount)

    def stop(self):
        self.config.m1.stop()
        self.emit('stopped', None)

    def scan(self):
        # go to start position and configure motor, save config first
        motor_conf = self.config.m1.get_config()
        self.config.m1.move_to(self.config.p1, wait=True)
        self.config.m1.configure(speed=self.config.speed)

        # initialize row connect devices
        self.data_row[0] = self.config.m1.get_position()

        # register data monitor to gather data points
        self.data_ids[self.config.m1] = self.config.m1.connect('changed', self.on_data, 0)

        self.data_ids.update({
            dev: dev.connect('count', self.on_data, i + self.config.start_channel)
            for i, dev in enumerate(self.config.counters)
        })

        # start recording data as fast as possible
        for counter in self.config.counters:
            counter.start()

        # move motor or position to end position
        self.config.m1.move_to(self.config.p2, wait=True)

        # disconnect data monitor at the end
        for counter, src_id in self.data_ids.items():
            counter.disconnect(src_id)

        # return motor to previous configuration
        self.config.m1.configure(**motor_conf)


class AbsScan(BasicScan):
    """
    An absolute scan of a single motor.

    :param m1: motor or positioner
    :param p1: absolute start position
    :param p2: absolute end position
    :param steps: number of steps
    :param exposure: count time at each point
    :param counters: one or more counters
    :param i0: reference counter
    """

    def __init__(self, m1, p1, p2, steps, exposure, *counters, i0=None):
        super().__init__()
        steps = max(2, steps)  # minimum of 2 steps
        positions = numpy.linspace(p1, p2, steps)
        assert len(counters) > 0, ValueError('At least one counter is required.')
        self.configure(
            m1=IMotor(m1),
            p1=p1,
            p2=p2,
            steps=steps,
            exposure=exposure,
            counters=counters,
            i0=i0,
            position=0,
            positions=positions,
            step_size=(positions[1]-positions[0])
        )
        self.setup((self.config.m1,), counters, i0)
        self.extending = False

    def extend(self, steps):
        self.config.position = self.config.steps
        self.config.p2 += self.config.step_size * steps
        self.config.steps += steps
        self.config.positions = numpy.linspace(self.config.p1, self.config.p2, self.config.steps)
        super().extend(steps)

    def scan(self):
        ref_value = 1.0
        for i, x in enumerate(self.config.positions):
            if self.stopped:
                logger.info("Scan stopped!")
                break

            # skip to current position
            if i < self.config.position: continue

            self.config.m1.move_to(x, wait=True)
            counts = misc.multi_count(self.config.exposure, *self.config.counters)
            if self.config.i0:
                if i == 0:
                    ref_value = counts[-1]
                counts = (counts[0]*ref_value/counts[-1],) + counts

            row = (x,) + counts
            self.raw_data.append(row)
            self.emit("new-point", row)
            self.emit("progress", (i + 1.0)/self.config.steps, "")
            time.sleep(0)


class RelScan(AbsScan):
    """
    Relative scan of a single motor.

    :param m1: motor or positioner
    :param p1: relative start position
    :param p2: relative end position
    :param steps: number of steps
    :param exposure: count time at each point
    :param counters: one or more counters
    :param i0: reference counter
    """

    def __init__(self, m1, p1, p2, steps, exposure, *counters, i0=None):
        cur = IMotor(m1).get_position()
        super().__init__(m1, cur+p1, cur+p2, steps, exposure, *counters, i0=i0)


class AbsScan2(BasicScan):
    """
    Sequential Absolute scan of two motors.

    :param m1: first motor or positioner
    :param p11: relative start position of first motor
    :param p12: relative end position of first motor
    :param m2: second motor or positioner
    :param p21: relative start position of second motor
    :param p22: relative end position of second motor
    :param steps: number of steps for both motors
    :param exposure: count time at each point
    :param counters: one or more counters
    :param i0: reference counter
    """

    def __init__(self, m1, p11, p12, m2, p21, p22, steps, exposure, *counters, i0=None):
        super().__init__()
        positions_1 = numpy.linspace(p11, p12, steps)
        positions_2 = numpy.linspace(p21, p22, steps)
        assert len(counters) > 0, ValueError('At least one counter is required.')
        self.configure(
            m1=IMotor(m1),
            p11=p11,
            p12=p12,
            m2=IMotor(m2),
            p21=p21,
            p22=p22,
            steps=steps,
            counters=counters,
            exposure=exposure,
            i0=i0,
            position=0,
            positions_1=positions_1,
            positions_2=positions_2,
            step_size_1=positions_1[1] - positions_1[0],
            step_size_2=positions_2[1] - positions_2[0],
        )
        self.setup((self.config.m1, self.config.m2,), counters, i0)

    def extend(self, steps):
        self.config.position = self.config.steps
        self.config.p12 += self.config.step_size_1 * steps
        self.config.p22 += self.config.step_size_2 * steps
        self.config.steps += steps
        self.config.positions_1 = numpy.linspace(self.config.p11, self.config.p12, self.config.steps)
        self.config.positions_2 = numpy.linspace(self.config.p21, self.config.p22, self.config.steps)
        super().extend(steps)

    def scan(self):
        ref_value = 1.0
        for i in range(self.config.steps):
            if self.stopped:
                logger.info("Scan stopped!")
                break
            if i < self.config.position:
                continue
            x1 = self.config.positions_1[i]
            x2 = self.config.positions_2[i]
            self.config.m1.move_to(x1)
            self.config.m2.move_to(x2)
            self.config.m1.wait()
            self.config.m2.wait()

            counts = misc.multi_count(self.config.exposure, *self.config.counters)
            if self.config.i0:
                if i == 0:
                    ref_value = counts[-1]
                counts = (counts[0]*ref_value/counts[-1],) + counts

            row = (x1, x2, ) + counts
            self.raw_data.append(row)
            self.emit("new-point", row)
            self.emit("progress", (i + 1.0) / self.config.steps, "")
            time.sleep(0)


class RelScan2(AbsScan2):
    """
    Sequential Relative scan of two motors.

    :param m1: first motor or positioner
    :param p11: relative start position of first motor
    :param p12: relative end position of first motor
    :param m2: second motor or positioner
    :param p21: relative start position of second motor
    :param p22: relative end position of second motor
    :param steps: number of steps for both motors
    :param exposure: count time at each point
    :param counters: one or more counters
    :param i0: reference counter
    """

    def __init__(self, m1, p11, p12, m2, p21, p22, steps, *counters, t, i0=None):
        cur1 = IMotor(m1).get_position()
        cur2 = IMotor(m2).get_position()
        super().__init__(m1, cur1+p11, cur1+p12, m2, cur2+p21, cur2+p22, steps, *counters, t, i0)


class GridScan(BasicScan):
    """
    Absolute Step Grid scan of two motors.

    :param m1: first motor or positioner
    :param p11: start position of first motor
    :param p12: end position of first motor
    :param steps1: number of steps for motor 1
    :param m2: second motor or positioner
    :param p21: start position of second motor
    :param p22: end position of second motor
    :param steps2: number of steps for motor 2
    :param exposure: count time at each point
    :param counters: one or more counters
    :param i0: reference counter
    :param snake: if True, scan in both directions
    """

    def __init__(self, m1, p11, p12, steps1, m2, p21, p22, steps2, exposure, *counters, i0=None, snake=False):
        super().__init__()
        positions_1 = numpy.linspace(p11, p12, steps1)
        positions_2 = numpy.linspace(p21, p22, steps2)
        assert len(counters) > 0, ValueError('At least one counter is required.')
        self.configure(
            m1=IMotor(m1),
            p11=p11,
            p12=p12,
            m2=IMotor(m2),
            p21=p21,
            p22=p22,
            steps_1=steps1,
            steps_2=steps2,
            counters=counters,
            exposure=exposure,
            i0=i0,
            position=0,
            positions_1=positions_1,
            positions_2=positions_2,
            step_size_1=positions_1[1] - positions_1[0],
            step_size_2=positions_2[1] - positions_2[0],
            snake=snake
        )
        self.setup((self.config.m1, self.config.m2,), counters, i0)

    def get_specs(self):
        specs = super().get_specs()
        specs['grid_snake'] = self.config.snake
        return specs

    def extend(self, steps):
        self.config.position = self.config.steps_2
        self.config.p22 += self.config.step_size_2 * steps
        self.config.steps_2 += steps
        self.config.positions_2 = numpy.linspace(self.config.p21, self.config.p22, self.config.steps_2)
        super().extend(steps)

    def scan(self):
        total_points = self.config.steps_1 * self.config.steps_2
        ref_value = 1.0

        for i, x2 in enumerate(self.config.positions_2):
            if i < self.config.position:
                continue
            if self.stopped:
                break
            self.config.m2.move_to(x2, wait=True)
            x1_positions = self.config.positions_1 if not self.config.snake else reversed(self.config.positions_1)
            for j, x1 in enumerate(x1_positions):
                if self.stopped:
                    break
                self.config.m1.move_to(x1, wait=True)

                counts = misc.multi_count(self.config.exposure, *self.config.counters)
                if self.config.i0:
                    if i == 0:
                        ref_value = counts[-1]
                    counts = (counts[0] * ref_value / counts[-1],) + counts

                position = j + i * self.config.steps_2
                row = (x1, x2,) + counts
                self.raw_data.append(row)
                self.emit("new-point", row)
                self.emit("progress", position / total_points, "")
                time.sleep(0)
            self.emit('new-row', i + 1)


class SlewGridScan(BasicScan):
    """
    A Grid scan with Slewing of the inner motor (first).

    :param m1: first motor or positioner for slew scan
    :param p11: start position of first motor
    :param p12: end position of first motor
    :param m2: second motor or positioner
    :param p21: start position of second motor
    :param p22: end position of second motor
    :param steps: number of steps for motor 2
    :param exposure: count time at each point
    :param counters: one or more counters
    :param i0: reference counter
    :param speed:  scan speed of m1
    """

    def __init__(self, m1, p11, p12, m2, p21, p22, steps, exposure, *counters, i0=None, speed=None):
        super().__init__()
        positions = numpy.linspace(p21, p22, steps)
        self.configure(
            m1=IMotor(m1),
            p11=p11,
            p12=p12,
            m2=IMotor(m2),
            p21=p21,
            p22=p22,
            steps=steps,
            counters=counters,
            exposure=exposure,
            i0=i0,
            position=0,
            positions=positions,
            step_size=positions[1] - positions[0],
            speed=speed
        )
        self.setup((self.config.m1, self.config.m2,), counters, i0)
        self.cur_count = 0
        self.cur_origin = 0
        self.last_update = time.time()

    def get_specs(self):
        specs = super().get_specs()
        specs['grid_snake'] = True  # Slew Grids are always snake grids
        return specs

    def on_data(self, device, value, channel):
        self.data_row[channel] = value
        if self.config.i0 and channel == self.config.start_channel and len(self.raw_data):
            self.data_row[1] = value * self.raw_data[0][-1] / self.data_row[-1]

        row = tuple(self.data_row)
        self.raw_data.append(row)

        self.set_state(new_point=(row,))
        outer_progress = self.cur_count / self.config.steps
        inner_progress = abs((self.data_row[0] - self.cur_origin) / (self.config.p12 - self.config.p11))/self.config.steps
        progress = outer_progress + inner_progress
        self.set_state(progress=(progress, ''))
        self.last_update = time.time()

    def extend(self, steps):
        self.config.position = self.config.steps
        self.config.p22 += self.config.step_size * steps
        self.config.steps += steps
        self.config.positions = numpy.linspace(self.config.p21, self.config.p22, self.config.steps)
        super().extend(steps)

    def stop(self):
        self.stopped = True
        self.config.m1.stop()
        self.config.m2.stop()

    def scan(self):
        # initialize data
        outer_channel = 1
        slew_channel = 0

        # go to start position and configure motor, save config first
        motor_conf = self.config.m1.get_config()

        self.config.m1.move_to(self.config.p11, wait=True)
        self.config.m1.configure(speed=self.config.speed)
        self.data_row[slew_channel] = self.config.m1.get_position()

        for i, x2 in enumerate(self.config.positions):
            self.cur_count = i

            if i < self.config.position:
                continue

            if self.stopped: break
            self.config.m2.move_to(x2, wait=True)
            self.data_row[outer_channel] = self.config.m2.get_position()

            # INNER Slew Scan
            # prepare data recorder
            self.data_ids[self.config.m1] = self.config.m1.connect('changed', self.on_data, slew_channel)
            self.data_ids.update({
                dev: dev.connect('count', self.on_data, i + self.config.start_channel)
                for i, dev in enumerate(self.config.counters)
            })

            # start recording data as fast as possible
            for counter in self.config.counters:
                counter.start()

            # move motor to start or end
            x1 = [self.config.p12, self.config.p11][i % 2]  # alternate p11 and p12
            self.cur_origin = self.config.m1.get_position()
            self.config.m1.move_to(x1, wait=True)

            self.emit('new-row', i+1)

            # disconnect data monitor at the end
            for counter, src_id in self.data_ids.items():
                counter.disconnect(src_id)
            self.data_ids = {}
            time.sleep(0)

        # return motor to previous configuration
        self.config.m1.configure(**motor_conf)
