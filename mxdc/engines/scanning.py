import threading
import time
from datetime import datetime
import inspect
import numpy
from gi.repository import GObject
from scipy import interpolate
from twisted.python.components import globalRegistry
from zope.interface import implements

from mxdc.beamlines.mx import IBeamline
from mxdc.com import ca
from mxdc.devices.interfaces import IMotor, ICounter
from mxdc.engines.interfaces import IScan, IScanPlotter
from mxdc.utils import misc, xdi
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class ScanError(Exception):
    """Scan Error."""


class BasicScan(GObject.GObject):
    implements(IScan)
    __gsignals__ = {}
    __gsignals__['new-point'] = (GObject.SignalFlags.RUN_FIRST, None, (object,))
    __gsignals__['progress'] = (GObject.SignalFlags.RUN_FIRST, None, (float, str,))
    __gsignals__['done'] = (GObject.SignalFlags.RUN_FIRST, None, [])
    __gsignals__['started'] = (GObject.SignalFlags.RUN_FIRST, None, [])
    __gsignals__['message'] = (GObject.SignalFlags.RUN_FIRST, None, (str,))
    __gsignals__['busy'] = (GObject.SignalFlags.RUN_FIRST, None, (bool,))
    __gsignals__['error'] = (GObject.SignalFlags.RUN_FIRST, None, (str,))
    __gsignals__['stopped'] = (GObject.SignalFlags.RUN_FIRST, None, [])
    __gsignals__['paused'] = (GObject.SignalFlags.RUN_FIRST, None, [object, bool])

    def __init__(self):
        super(BasicScan, self).__init__()
        self.stopped = False
        self.paused = False
        self.busy = False
        self.send_notification = False
        self.append = False
        self.config = {}
        self.data_types = {}
        self.units = {}
        self.data = []
        self.data_rows = []
        self.total = 0
        self.plotter = None
        self.beamline = None
        self.start_time = None
        self.end_time = None

    def is_busy(self):
        return self.busy

    def configure(self, **kwargs):
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.plotter = globalRegistry.lookup([], IScanPlotter)
        self.data = []
        self.data_rows = []

    def extend(self, steps):
        self.append = True

    def get_specs(self):
        return {}

    def start(self, append=None):
        self.stopped = False
        if append is not None and append:
            self.append = True
        if not self.append:
            self.data_rows = []
        worker_thread = threading.Thread(target=self._thread_run)
        worker_thread.setName(self.__class__.__name__)
        worker_thread.setDaemon(True)
        self.start_time = datetime.now()
        worker_thread.start()

    def _thread_run(self):
        self.busy = True
        GObject.idle_add(self.emit, 'message', 'Scan in progress')
        GObject.idle_add(self.emit, 'busy', True)
        ca.threads_init()
        self.run()
        self.busy = False
        GObject.idle_add(self.emit, 'busy', False)

    def pause(self, state):
        self.paused = state

    def stop(self):
        self.stopped = True

    def run(self):
        pass  # derived classes should implement this

    def on_beam_change(self, obj, beam_available):
        self.send_notification = not beam_available
        if self.send_notification and (not self.paused) and (not self.stopped):
            self.pause(True)

    def set_data(self, raw_data):
        self.data = numpy.array(raw_data, dtype=self.data_types)
        return self.data

    def prepare_xdi(self):
        comments = inspect.getdoc(self)
        xdi_data = xdi.XDIData(data=self.data, comments=comments, version='MxDC/2017.10')
        xdi_data['Facility.name'] = self.beamline.config['facility']
        xdi_data['Facility.xray_source'] = self.beamline.config['source']
        xdi_data['Beamline.name'] = self.beamline.name
        xdi_data['Mono.name'] = self.beamline.config.get('mono', 'Si 111')
        xdi_data['Scan.start_time'] = self.config.get('start_time', datetime.now())
        xdi_data['Scan.end_time'] = self.config.get('end_time', datetime.now())
        xdi_data['CMCF.scan_type'] = self.__class__.__name__
        for i, name in enumerate(self.data_types['names']):
            key = 'Column.{}'.format(i + 1)
            xdi_data[key] = (name, self.units.get(name))
        return xdi_data

    def save(self, filename=None):
        if filename is None:
            filename = time.strftime('%d%a-%H:%M:%S') + '.xdi.gz'
        xdi_data = self.prepare_xdi()
        xdi_data.save(filename)


class AbsScan(BasicScan):
    """An absolute scan of a single motor."""

    def __init__(self, mtr, start_pos, end_pos, steps, cntr, t, i0=None):
        super(AbsScan, self).__init__()
        self.configure(mtr, start_pos, end_pos, steps, cntr, t, i0)
        self.data_types = {
            'names': ['position', 'normcounts', 'counts', 'i0'],
            'formats': [float, float, float, float]
        }

    def configure(self, mtr, start_pos, end_pos, steps, cntr, t, i0=None):
        self._motor = IMotor(mtr)
        self.units['position'] = self._motor.units
        self._counter = ICounter(cntr)
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._steps = steps
        self._start_pos = start_pos
        self._end_pos = end_pos
        self._step_size = (self._end_pos - self._start_pos) / float(self._steps)
        self._start_step = 0

    def extend(self, steps):
        self.append = True
        self._start_step = self._steps
        self._steps += steps

    def run(self):
        if not self.append:
            GObject.idle_add(self.emit, "started")
            self.data_rows = []

        for i in range(self._start_step, self._steps):
            if self.stopped:
                logger.info("Scan stopped!")
                break
            x = self._start_pos + (i * self._step_size)
            self._motor.move_to(x, wait=True)
            if self._i0 is not None:
                y, i0 = misc.multi_count(self._counter, self._i0, self._duration)
            else:
                y = self._counter.count(self._duration)
                i0 = 1.0
            x = self._motor.get_position()
            self.data_rows.append((x, y / i0, y, i0))
            GObject.idle_add(self.emit, "new-point", [x, y / i0, y, i0])
            GObject.idle_add(self.emit, "progress", (i + 1.0) / (self._steps), "")
        self.set_data(self.data_rows)
        GObject.idle_add(self.emit, "done")


class AbsScan2(BasicScan):
    """An Absolute scan of two motors."""

    def __init__(self, mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0=None):
        super(AbsScan2, self).__init__()
        self.configure(mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0)
        self.data_types = {
            'names': ['position1', 'position2', 'normcounts', 'counts', 'i0'],
            'formats': [float, float, float, float, float]
        }

    def configure(self, mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0=None):
        self._motor1 = IMotor(mtr1)
        self._motor2 = IMotor(mtr2)
        self.units['position1'] = self._motor1.units
        self.units['position2'] = self._motor2.units
        self._counter = ICounter(cntr)
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._steps = steps
        self._start_pos1 = start_pos1
        self._end_pos1 = end_pos1
        self._start_pos2 = start_pos2
        self._end_pos2 = end_pos2
        self._step_size1 = (self._end_pos1 - self._start_pos1) / float(self._steps)
        self._step_size2 = (self._end_pos2 - self._start_pos2) / float(self._steps)
        self._start_step = 0

    def extend(self, steps):
        self.append = True
        self._start_step = self._steps
        self._steps += steps

    def run(self):
        if not self.append:
            GObject.idle_add(self.emit, "started")
            self.data_rows = []
        for i in range(self._start_step, self._steps):
            if self.stopped:
                logger.info("Scan stopped!")
                break
            x1 = self._start_pos1 + (i * self._step_size1)
            x2 = self._start_pos2 + (i * self._step_size2)
            self._motor1.move_to(x1)
            self._motor2.move_to(x2)
            self._motor1.wait()
            self._motor2.wait()
            if self._i0 is not None:
                y, i0 = misc.multi_count(self._counter, self._i0, self._duration)
            else:
                y = self._counter.count(self._duration)
                i0 = 1.0
            x1 = self._motor1.get_position()
            x2 = self._motor2.get_position()
            self.data_rows.append((x1, x2, y / i0, y, i0))
            GObject.idle_add(self.emit, "new-point", [x1, x2, y / i0, y, i0])
            GObject.idle_add(self.emit, "progress", (i + 1.0) / (self._steps), "")
        self.set_data(self.data_rows)
        GObject.idle_add(self.emit, "done")


class RelScan(AbsScan):
    """A relative scan of a single motor."""

    def __init__(self, mtr, start_offset, end_offset, steps, cntr, t, i0=None):
        super(RelScan, self).__init__(mtr, start_offset, end_offset, steps, cntr, t, i0=None)
        self.data_types = {
            'names': ['position', 'normcounts', 'counts', 'i0'],
            'formats': [float, float, float, float, float]
        }

    def configure(self, mtr, start_offset, end_offset, steps, cntr, t, i0=None):
        self._motor = IMotor(mtr)
        self.units['position'] = self._motor.units
        self._counter = ICounter(cntr)
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._steps = steps
        cur_pos = self._motor.get_position()
        self._start_pos = cur_pos + start_offset
        self._end_pos = cur_pos + end_offset
        self._step_size = (self._end_pos - self._start_pos) / float(self._steps)
        self._start_step = 0


class CntScan(BasicScan):
    """A Continuous scan of a single motor."""

    def __init__(self, mtr, start_pos, end_pos, cntr, t, i0=None):
        super(CntScan, self).__init__()
        self.configure(mtr, start_pos, end_pos, cntr, t, i0)
        self.data_types = {
            'names': ['position', 'normcounts', 'counts', 'i0'],
            'formats': [float, float, float, float, float]
        }

    def configure(self, mtr, start_pos, end_pos, cntr, t, i0=None):
        self._motor = IMotor(mtr)
        self._counter = ICounter(cntr)
        self.units['position'] = self._motor.units
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._start_pos = start_pos
        self._end_pos = end_pos

    def run(self):
        if not self.append:
            GObject.idle_add(self.emit, "started")
            self.data_rows = []
        x_ot = []
        y_ot = []
        i_ot = []

        def _chg_cb(obj, dat):
            x_ot.append(dat)

        self._motor.move_to(self._start_pos, wait=True)
        self._motor.move_to(self._end_pos, wait=False)
        src_id = self._motor.connect('change', lambda x, y: x_ot.append((x.time_state, y)))
        self._motor.wait(start=True, stop=False)

        while self._motor.busy_state:
            if self.stopped:
                logger.info("Scan stopped!")
                break
            ts = time.time()
            y = self._counter.count(self._duration)
            t = (ts + time.time() / 2.0)

            if self._i0 is not None:
                ts = time.time()
                i0 = self._i0.count(self._duration)
                ti = (ts + time.time() / 2.0)
            else:
                ti = time.time()
                i0 = 1.0
            y_ot.append((y, t))
            i_ot.append((i0, ti))
            yi = y / i0
            if len(x_ot) > 0:
                x = x_ot[-1][0]  # x should be the last value, only rough estimate for now
                GObject.idle_add(self.emit, "new-point", (x, yi, i0, y))
                GObject.idle_add(self.emit, "progress", (x - self._start_pos) / (self._end_pos - self._start_pos), "")
            time.sleep(0.01)

        self._motor.disconnect(src_id)
        # Perform interpolation
        xi, tx = zip(*x_ot)
        yi, ty = zip(*y_ot)
        ii, ti = zip(*i_ot)

        mintx, maxtx = min(tx), max(tx)
        minty, maxty = min(ty), max(ty)
        tst = max(mintx, minty)
        ten = min(maxtx, maxty)
        t_final = numpy.linspace(tst, ten, len(y_ot) * 2)  # 2 x oversampling based on counter

        # tckx = interpolate.splrep(tx, xi)
        tcky = interpolate.splrep(ty, yi)
        tcki = interpolate.splrep(ti, ii)

        # xnew = interpolate.splev(t_final, tckx, der=0)
        ynew = interpolate.splev(tx, tcky, der=0)
        inew = interpolate.splev(tx, tcki, der=0)

        yinew = ynew / inew
        self.data_rows = zip(xi, yinew, ynew, inew)
        self.set_data(self.data_rows)
        GObject.idle_add(self.emit, "done")


class RelScan2(AbsScan2):
    """A relative scan of a two motors."""
    data_types = {
        'names': ['position1', 'position2', 'normcounts', 'counts', 'i0'],
        'formats': [float, float, float, float, float]
    }

    def __init__(self, mtr1, start_offset1, end_offset1, mtr2, start_offset2, end_offset2, steps, cntr, t, i0=None):
        BasicScan.__init__(self)
        self.configure(mtr1, start_offset1, end_offset1, mtr2, start_offset2, end_offset2, steps, cntr, t, i0)

    def configure(self, mtr1, start_offset1, end_offset1, mtr2, start_offset2, end_offset2, steps, cntr, t, i0=None):
        self._motor1 = IMotor(mtr1)
        self._motor2 = IMotor(mtr2)
        self.units['position1'] = self._motor1.units
        self.units['position2'] = self._motor2.units
        self._counter = ICounter(cntr)
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._steps = steps
        cur_pos1 = self._motor1.get_position()
        cur_pos2 = self._motor2.get_position()
        self._start_pos1 = cur_pos1 + start_offset1
        self._end_pos1 = cur_pos1 + end_offset1
        self._start_pos2 = cur_pos2 + start_offset2
        self._end_pos2 = cur_pos2 + end_offset2
        self._step_size1 = (self._end_pos1 - self._start_pos1) / float(self._steps)
        self._step_size2 = (self._end_pos2 - self._start_pos2) / float(self._steps)
        self._start_step = 0


class GridScan(BasicScan):
    """A absolute scan of two motors in a grid."""

    def __init__(self, mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0=None):
        super(GridScan, self).__init__()
        self.configure(mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0)
        self.data_types = {
            'names': ['position1', 'position2', 'normcounts', 'counts', 'i0'],
            'formats': [float, float, float, float, float]
        }

    def configure(self, mtr1, start_pos1, end_pos1, mtr2, start_pos2, end_pos2, steps, cntr, t, i0=None):
        self._motor1 = IMotor(mtr1)
        self._motor2 = IMotor(mtr2)
        self.units['position1'] = self._motor1.units
        self.units['position2'] = self._motor2.units
        self._counter = ICounter(cntr)
        if i0 is not None:
            self._i0 = ICounter(i0)
        else:
            self._i0 = None
        self._duration = t
        self._steps = steps
        self._start_pos1 = start_pos1
        self._end_pos1 = end_pos1
        self._start_pos2 = start_pos2
        self._end_pos2 = end_pos2
        self._points1 = numpy.linspace(self._start_pos1, self._end_pos1, self._steps)
        self._points2 = numpy.linspace(self._start_pos2, self._end_pos2, self._steps)

    def extend(self, steps):
        print 'Grid Scan can not be extended'

    def get_specs(self):
        return {
            'type': 'GRID',
            'steps': self._steps,
            'start_1': self._start_pos1,
            'start_2': self._start_pos2,
            'end_1': self._end_pos1,
            'end_2': self._end_pos2,
        }

    def run(self):
        GObject.idle_add(self.emit, "started")
        total_points = len(self._points1) * len(self._points2)
        pos = 0
        for x2 in self._points2:
            for x1 in self._points1:
                if self.stopped:
                    logger.info("Scan stopped!")
                    break
                self._motor2.move_to(x2)
                self._motor2.wait()
                self._motor1.move_to(x1)
                self._motor1.wait()

                if self._i0 is not None:
                    y, i0 = misc.multi_count(self._counter, self._i0, self._duration)
                else:
                    y = self._counter.count(self._duration)
                    i0 = 1.0
                self.data.append([x1, x2, y / i0, i0, y])
                logger.info("%4d %15g %15g %15g %15g %15g" % (pos, x1, x2, y / i0, i0, y))
                GObject.idle_add(self.emit, "new-point", (x1, x2, y / i0, i0, y))
                GObject.idle_add(self.emit, "progress", (pos + 1.0) / (total_points), "")
                pos += 1

        GObject.idle_add(self.emit, "done")
