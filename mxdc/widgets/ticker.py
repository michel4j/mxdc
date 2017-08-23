import threading
import time

import numpy
from gi.repository import Gtk, GObject
from matplotlib import rcParams
from matplotlib.animation import FuncAnimation
from matplotlib.backends.backend_gtk3cairo import FigureCanvasGTK3Cairo as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

rcParams['font.family'] = 'Cantarell'
rcParams['font.size'] = 9


def get_min_max(a, ldev=5, rdev=5):
    a = a[(numpy.isnan(a) == False)]
    if len(a) == 0:
        return -0.1, 0.1
    _std = a.std()
    if _std == 0:  _std = 0.1
    mn, mx = a.min() - ldev * _std, a.max() + rdev * _std
    return mn, mx


class TickerChart(Gtk.Box):
    __gsignals__ = {
        'cursor-time': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, interval=100, view=20, keep=40, linewidth=1):
        Gtk.Box.__init__(self)
        self.fig = Figure(facecolor='w')
        self.canvas = FigureCanvas(self.fig)
        self.pack_start(self.canvas, True, True, 0)

        self.data = {}
        self.plots = {}

        self.axis = self.fig.add_subplot(111)
        self.axis.set_xlabel('seconds ago')
        self.interval = interval  # milliseconds
        self.view_range = view  # seconds
        self.keep_range = keep  # seconds
        self.linewidth = linewidth

        self.view_size = view * 1000 // self.interval
        self.keep_size = keep * 1000 // self.interval

        self.view_time = time.time()
        self.add_data('time')
        self.show_all()

    def add_data(self, name):
        if name in self.data:
            return
        self.data[name] = numpy.empty(self.keep_size)
        self.data[name][:] = numpy.nan

    def resize_data(self):
        for name, data in self.data.items():
            self.data[name] = numpy.empty(self.keep_size)
            if self.max_samples > len(data):
                self.data[name][-len(data):] = data
            else:
                self.data[name] = data[-self.keep_size:]

    def shift_data(self):
        for name, data in self.data.items():
            data[:-1] = data[1:]

    def add_plot(self, name, color):
        self.plots[name] = Line2D([], [], color=color, linewidth=self.linewidth)
        self.axis.add_line(self.plots[name])
        self.add_data(name)

    def clear(self):
        for name, line in self.plots.items():
            line.set_data([], [])

    def update(self):
        selector = (self.data['time'] > self.view_time - self.view_range) & (self.data['time'] <= self.view_time)
        if selector.sum() < 2: return
        now = self.data['time'][selector][-1]
        x_data = self.data['time'][selector] - now
        xmin, xmax = min(x_data.min(), -self.view_range), x_data.max()

        ymin, ymax = numpy.nan, numpy.nan
        for name, line in self.plots.items():
            y_data = self.data[name][selector]
            mn, mx = get_min_max(y_data)
            ymin, ymax = numpy.nanmin([ymin, mn]), numpy.nanmax([ymax, mx])
            line.set_data(x_data, y_data)

        self.axis.set_ylim(ymin, ymax)
        self.axis.set_xlim(xmin, xmax)

    def redraw(self):
        self.canvas.draw_idle()

    def animate(self, i):
        self.update()
        return self.plots.values()


class ChartManager(GObject.GObject):
    def __init__(self, interval=100, view=20):
        GObject.GObject.__init__(self)
        self.chart = TickerChart(interval=interval * 2, view=view, keep=view*2)
        self.sources = {}
        self.values = {}
        self.interval = interval / 1000.  # convert from milliseconds to seconds
        self.animation = FuncAnimation(self.chart.fig, self.chart.animate, None, interval=interval, blit=False)
        self.start()

    def add_plot(self, dev, name, color='#FF0000'):
        self.chart.add_plot(name, color)
        self.values[name] = numpy.nan
        self.sources[name] = dev.connect('changed', self.collect_data, name)

    def collect_data(self, dev, value, name):
        self.values[name] = value

    def start(self):
        """Start the Data monitor thread """
        self._stopped = False
        worker_thread = threading.Thread(name="PVSampler", target=self.update_data)
        worker_thread.setDaemon(True)
        worker_thread.start()

    def update_data(self):
        # update the values of the array every interval seconds, shift left
        while not self._stopped:
            self.chart.shift_data()
            for name, value in self.values.items():
                if name in self.chart.data:
                    self.chart.data[name][-1] = value
            self.chart.data['time'][-1] = time.time()
            self.chart.view_time = time.time()
            time.sleep(self.interval)
