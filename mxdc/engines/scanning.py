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
    name = 'Basic Scan'
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
        self.config = misc.DotDict({})
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

    def configure(self, *args, **kwargs):
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.plotter = globalRegistry.lookup([], IScanPlotter)
        if self.plotter:
            self.plotter.link_scan(self)
        self.data = []
        self.config = misc.DotDict(kwargs)

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

    def pause(self, state=True):
        self.paused = state

    def resume(self):
        self.paused = False

    def stop(self):
        self.stopped = True

    def run(self):
        pass  # derived classes should implement this

    def on_beam_change(self, obj, beam_available):
        self.send_notification = not beam_available
        if self.send_notification and (not self.paused) and (not self.stopped):
            self.pause()

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
            filename = time.strftime('%y%m%dT%H%M%S') + '.xdi.gz'
        logger.debug('Saving XDI: {}'.format(filename))
        xdi_data = self.prepare_xdi()
        xdi_data.save(filename)
        return filename


class AbsScan(BasicScan):
    """An absolute scan of a single motor."""

    def __init__(self, m1, p1, p2, steps, counter, t, i0=None):
        super(AbsScan, self).__init__()
        self.configure(m1=IMotor(m1), p1=p1, p2=p2, steps=steps, counter=ICounter(counter), t=t, i0=i0)

    def configure(self, *args, **kwargs):
        super(AbsScan, self).configure(self, *args, **kwargs)

        counter_name = misc.slugify(self.config.counter.name)
        self.data_types = {
            'names': [misc.slugify(self.config.m1.name), 'norm_{}'.format(counter_name), counter_name, 'i0'],
            'formats': [float, float, float, float]
        }
        self.units[misc.slugify(self.config.m1.name)] = self.config.m1.units

        self.config.i0 = None if not self.config.i0 else ICounter(self.config.i0)
        self.config.step_size = (self.config.p2 - self.config.p1) / float(self.config.steps)
        self.config.position = 0

    def extend(self, steps):
        self.append = True
        self.config.position = self.config.steps
        self.config.steps += steps

    def run(self):
        if not self.append:
            GObject.idle_add(self.emit, "started")
            self.data_rows = []

        for i in range(self.config.position, self.config.steps):
            if self.stopped:
                logger.info("Scan stopped!")
                break
            x = self.config.p1 + (i * self.config.step_size)
            self.config.m1.move_to(x, wait=True)
            if self.config.i0:
                y, i0 = misc.multi_count(self.config.counter, self.config.i0, self.config.t)
            else:
                y = self.config.counter.count(self.config.t)
                i0 = 1.0
            #x = self.config.m1.get_position()
            self.data_rows.append((x, y / i0, y, i0))
            GObject.idle_add(self.emit, "new-point", [x, y / i0, y, i0])
            GObject.idle_add(self.emit, "progress", (i + 1.0) / (self.config.steps), "")
        self.set_data(self.data_rows)
        GObject.idle_add(self.emit, "done")


class RelScan(AbsScan):
    """A relative scan of a single motor."""

    def __init__(self, m1, p1, p2, steps, counter, t, i0=None):
        cur = IMotor(m1).get_position()
        super(RelScan, self).__init__(m1, cur+p1, cur+p2, steps, counter, t, i0)


class CntScan(AbsScan):
    """A Continuous scan of a single motor."""

    def __init__(self, m1, p1, p2, counter, t, i0=None):
        super(CntScan, self).__init__(m1, p1, p2, 1, counter, t, i0)

    def run(self):
        if not self.append:
            GObject.idle_add(self.emit, "started")
            self.data_rows = []
        x_ot = []
        y_ot = []
        i_ot = []

        def _chg_cb(obj, dat):
            x_ot.append(dat)

        self.config.m1.move_to(self.config.p1, wait=True)
        self.config.m1.move_to(self.config.p2, wait=False)
        src_id = self._motor.connect('change', lambda x, y: x_ot.append((x.time_state, y)))
        self.config.m1.wait(start=True, stop=False)

        while self.m1.is_busy():
            if self.stopped:
                logger.info("Scan stopped!")
                break
            ts = time.time()
            y = self.config.counter.count(self.config.t)
            t = (ts + time.time() / 2.0)

            if self.config.i0:
                ts = time.time()
                i0 = self.config.i0.count(self.config.t)
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
                GObject.idle_add(self.emit, "progress", (x - self.config.p1) / (self.config.p2 - self.config.p1), "")
            time.sleep(0.01)

        self.config.m1.disconnect(src_id)
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


class AbsScan2(BasicScan):
    """An Absolute scan of two motors."""

    def __init__(self, m1, p11, p12, m2, p21, p22, steps, counter, t, i0=None):
        super(AbsScan2, self).__init__()
        self.configure(
            m1=IMotor(m1), p11=p11, p12=p12, m2=IMotor(m2), p21=p21, p22=p22, steps=steps,
            counter=ICounter(counter), t=t, i0=i0
        )

    def configure(self, *args, **kwargs):
        super(AbsScan2, self).configure(*args, **kwargs)
        self.units[misc.slugify(self.config.m1.name)] = self.config.m1.units
        self.units[misc.slugify(self.config.m1.name)] = self.config.m2.units
        counter_name = misc.slugify(self.config.counter.name)
        self.data_types = {
            'names': [misc.slugify(self.config.m1.name), misc.slugify(self.config.m2.name), 'norm_{}'.format(counter_name), counter_name, 'i0'],
            'formats': [float, float, float, float, float]
        }
        self.config.i0 = None if not self.config.i0 else ICounter(self.config.i0)
        self.config.step_size = (self.config.p2 - self.config.p1) / float(self.config.steps)
        self.config.position = 0
        self.config.step_size1 = (self.config.p12 - self.config.p11) / float(self.config.steps)
        self.config.step_size2 = (self.config.p22 - self.config.p21) / float(self.config.steps)

    def extend(self, steps):
        self.append = True
        self.config.position = self.config.steps
        self.config.steps += steps

    def run(self):
        if not self.append:
            GObject.idle_add(self.emit, "started")
            self.data_rows = []
        for i in range(self.config.position, self.config.steps):
            if self.stopped:
                logger.info("Scan stopped!")
                break
            x1 = self.config.p11 + (i * self.config.step_size1)
            x2 = self.config.p21 + (i * self.config.step_size2)
            self.config.m1.move_to(x1)
            self.config.m2.move_to(x2)
            self.config.m1.wait()
            self.config.m2.wait()
            if self.config.i0 is not None:
                y, i0 = misc.multi_count(self.config.counter, self.config.i0, self.config.t)
            else:
                y = self.config.counter.count(self.config.t)
                i0 = 1.0
            x1 = self.config.m1.get_position()
            x2 = self.config.m2.get_position()
            self.data_rows.append((x1, x2, y / i0, y, i0))
            GObject.idle_add(self.emit, "new-point", [x1, x2, y / i0, y, i0])
            GObject.idle_add(self.emit, "progress", (i + 1.0) / (self.config.steps), "")
        self.set_data(self.data_rows)
        GObject.idle_add(self.emit, "done")


class RelScan2(AbsScan2):
    """A relative scan of a two motors."""

    def __init__(self, m1, p11, p12, m2, p21, p22, steps, counter, t, i0=None):
        cur1 = IMotor(m1).get_position()
        cur2 = IMotor(m2).get_position()
        super(RelScan2, self).__init__(m1, cur1+p11, cur1+p12, m2, cur2+p21, cur2+p22, steps, counter, t, i0)


class GridScan(AbsScan2):
    """A absolute scan of two motors in a grid."""

    def configure(self, *args, **kwargs):
        super(GridScan, self).configure(*args, **kwargs)

        self.config.points1 = numpy.linspace(self.config.p12, self.config.p11, self.config.steps)
        self.config.points2 = numpy.linspace(self.config.p22, self.config.p21, self.config.steps)

    def extend(self, steps):
        logger.error('Grid Scan can not be extended')

    def run(self):
        GObject.idle_add(self.emit, "started")
        total_points = len(self.config.points1) * len(self.config.points2)
        pos = 0
        for x2 in self.config.points2:
            if self.stopped:
                logger.info("Scan stopped!")
                break
            self.config.m2.move_to(x2, wait=True)
            for x1 in self.config.points1:
                if self.stopped:
                    logger.info("Scan stopped!")
                    break
                self.config.m1.move_to(x1, wait=True)

                if self.config.i0 is not None:
                    y, i0 = misc.multi_count(self.config.counter, self.config.i0, self.config.t)
                else:
                    y = self.config.counter.count(self.config.t)
                    i0 = 1.0
                self.data.append([x1, x2, y / i0, i0, y])
                logger.info("%4d %15g %15g %15g %15g %15g" % (pos, x1, x2, y / i0, i0, y))
                GObject.idle_add(self.emit, "new-point", (x1, x2, y / i0, i0, y))
                GObject.idle_add(self.emit, "progress", (pos + 1.0) / (total_points), "")
                pos += 1

        GObject.idle_add(self.emit, "done")
