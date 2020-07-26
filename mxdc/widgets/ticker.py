import os
import threading
import time
from collections import defaultdict
import atexit

import numpy
from gi.repository import Gtk, GObject
from matplotlib import rcParams
from matplotlib.animation import FuncAnimation
from matplotlib.backends.backend_gtk3cairo import FigureCanvasGTK3Cairo as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from mxdc.utils import misc
from mxdc.widgets import dialogs

rcParams['font.family'] = 'Cantarell'
rcParams['font.size'] = 10

COLORS = [
    '#1f77b4',
    '#ff7f0e',
    '#2ca02c',
    '#d62728',
    '#9467bd',
    '#8c564b',
    '#e377c2',
    '#7f7f7f',
    '#bcbd22',
    '#17becf'
]


class TickerChart(Gtk.Box):
    __gsignals__ = {
        'cursor-time': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, interval=100, view=20, keep=None, linewidth=1):
        super().__init__()
        self.fig = Figure(dpi=72)
        self.canvas = FigureCanvas(self.fig)
        self.pack_start(self.canvas, True, True, 0)

        self.data = {}
        self.plots = {}
        self.info = {}
        self.alternates = set()
        self.active = None

        self.axes = []
        self.axes.append(self.fig.add_subplot(111))
        self.fig.subplots_adjust(left=0.12, right=0.88)

        self.axes[0].set_xlabel('seconds ago')
        self.interval = interval  # milliseconds
        self.view_range = view  # seconds

        self.keep_range = keep or (view * 4)  # seconds
        self.linewidth = linewidth

        self.keep_size = int(self.keep_range * 1000 / self.interval)
        self.view_step = view // 2
        self.deviation = 10

        self.view_time = time.time()
        self.add_data('time')
        self.paused = False
        self.show_all()

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def zoom_out(self):
        self.view_range = max(self.view_range - self.view_step, self.view_step)
        self.update()

    def zoom_in(self):
        self.view_range = min(self.view_range + self.view_step, self.keep_range)
        self.update()

    def incr_margin(self):
        self.deviation = min(self.deviation + 5, 50)
        self.update()

    def decr_margin(self):
        self.deviation = max(self.deviationi - 5, 5)
        self.update()

    def add_data(self, name):
        if name in self.data:
            return
        self.data[name] = numpy.empty(self.keep_size)
        self.data[name][:] = numpy.nan

    def resize_data(self):
        for name, data in list(self.data.items()):
            self.data[name] = numpy.empty(self.keep_size)
            if self.max_samples > len(data):
                self.data[name][-len(data):] = data
            else:
                self.data[name] = data[-self.keep_size:]

    def select_active(self, name):
        if name in self.alternates:
            self.active = name
            self.axes[1].set_ylabel(name)

    def add_alternate(self, name):
        self.alternates.add(name)

    def shift_data(self):
        for name, data in list(self.data.items()):
            data[:-1] = data[1:]

    def add_plot(self, name, color=None, linestyle='-', axis=0, alternate=False):
        assert axis in [0, 1], 'axis must be 0 or 1'
        if axis == 1 and len(self.axes) == 1:
            self.axes.append(self.axes[0].twinx())
        if not color:
            color = COLORS[len(self.plots)]
        self.plots[name] = Line2D([], [], color=color, linewidth=self.linewidth, linestyle=linestyle)
        self.axes[axis].add_line(self.plots[name])
        self.axes[axis].set_ylabel(name, color=color)
        self.info[name] = {'color': color, 'linestyle': linestyle, 'axis': axis}
        if alternate:
            self.add_alternate(name)
            self.select_active(name)
        self.add_data(name)

    def clear(self):
        for name, line in list(self.plots.items()):
            self.data[name][:] = numpy.nan

    def update(self):
        if self.paused:
            return
        selector = ~numpy.isnan(self.data['time'])
        selector[selector] = (
            (self.data['time'][selector] > (self.view_time - self.view_range))
            & (self.data['time'][selector] <= self.view_time)
        )

        if selector.sum() < 2:
            return
        now = self.data['time'][selector][-1]
        x_data = self.data['time'][selector] - now
        xmin, xmax = min(x_data.min(), -self.view_range), x_data.max()

        extrema = defaultdict(lambda: (numpy.nan, numpy.nan))

        for name, line in list(self.plots.items()):
            if name in self.alternates and name != self.active: continue
            axis = self.info[name]['axis']
            ymin, ymax = extrema[axis]
            y_data = self.data[name][selector]
            mn, mx = misc.get_min_max(y_data, ldev=self.deviation, rdev=self.deviation)
            ymin, ymax = numpy.nanmin([ymin, mn]), numpy.nanmax([ymax, mx])
            extrema[axis] = (ymin, ymax)
            line.set_data(x_data, y_data)

        for i, (ymin, ymax) in list(extrema.items()):
            if ymin != ymax:
                self.axes[i].set_ylim(ymin, ymax)
            if xmin != xmax:
                self.axes[i].set_xlim(xmin, xmax)

    def redraw(self):
        self.canvas.draw_idle()

    def animate(self, i):
        self.update()
        return list(self.plots.values())

    def save(self):
        dialog = Gtk.FileChooserDialog(
            "Save Chart ...", dialogs.MAIN_WINDOW, Gtk.FileChooserAction.SAVE,
            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        )
        dialog.set_size_request(600, 300)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            img_filename = dialog.get_filename()
            if os.access(os.path.dirname(img_filename), os.W_OK):
                self.fig.savefig(img_filename)
        dialog.destroy()


class ChartManager(GObject.GObject):
    def __init__(self, interval=100, view=20):
        GObject.GObject.__init__(self)
        self.chart = TickerChart(interval=interval, view=view)
        self.sources = {}
        self.values = {}
        self.interval = interval / 1000.  # convert from milliseconds to seconds
        self.animation = FuncAnimation(self.chart.fig, self.chart.animate, None, interval=interval, blit=False)
        self.start()
        atexit.register(self.stop)

    def add_plot(self, dev, name, signal='changed', color=None, linestyle='-', axis=0, alternate=False):
        self.chart.add_plot(name, color=color, linestyle=linestyle, axis=axis, alternate=alternate)
        self.values[name] = numpy.nan
        self.sources[name] = dev.connect(signal, self.collect_data, name)

    def select_active(self, name):
        self.chart.select_active(name)

    def zoom_in(self, *args, **kwargs):
        self.chart.zoom_in()

    def zoom_out(self, *args, **kwargs):
        self.chart.zoom_out()

    def clear(self, *args, **kwargs):
        self.chart.clear()

    def save(self, *args, **kwargs):
        self.chart.save()

    def collect_data(self, dev, value, name):
        self.values[name] = value

    def start(self):
        """Start the Data monitor thread """
        self._stopped = False
        worker_thread = threading.Thread(name="TickerSampler", target=self.update_data)
        worker_thread.setDaemon(True)
        worker_thread.start()

    def stop(self):
        self._stopped = True

    def pause(self, *args, **kwargs):
        self.chart.pause()

    def resume(self, *args, **kwargs):
        self.chart.resume()

    def is_paused(self):
        return self.chart.paused

    def update_data(self):
        # update the values of the array every interval seconds, shift left
        while not self._stopped:
            self.chart.shift_data()
            if not self.is_paused():
                for name, value in list(self.values.items()):
                    if name in self.chart.data:
                        self.chart.data[name][-1] = value
            self.chart.data['time'][-1] = time.time()
            self.chart.view_time = time.time()
            time.sleep(self.interval)

    def cleanup(self):
        self.stop()
