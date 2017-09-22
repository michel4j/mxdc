"""
A Plotting widget using matplotlib - several lines can be added to multiple axes
points can be added to each line and the plot is automatically updated.
"""

import os
import time

import numpy
from gi.repository import Gtk, GObject
from matplotlib import rcParams
from matplotlib.backends.backend_gtk3 import NavigationToolbar2GTK3 as NavigationToolbar
from matplotlib.backends.backend_gtk3cairo import FigureCanvasGTK3Cairo as FigureCanvas
from matplotlib.colors import Normalize
from matplotlib.dates import MinuteLocator, SecondLocator
from matplotlib.figure import Figure
from matplotlib.ticker import FormatStrFormatter
from mpl_toolkits.mplot3d import axes3d
from mxdc.interface.engines import IScanPlotter
from mxdc.utils import misc
from mxdc.widgets import dialogs
from twisted.python.components import globalRegistry
from utils import fitting
from zope.interface import implements

rcParams['legend.loc'] = 'best'
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


class PlotterToolbar(NavigationToolbar):
    toolitems = (
        ('Home', 'Reset original view', 'go-home-symbolic', 'home'),
        ('Back', 'Back to  previous view', 'go-previous-symbolic', 'back'),
        ('Forward', 'Forward to next view', 'go-next-symbolic', 'forward'),
        (None, None, None, None),
        ('Pan', 'Pan axes with left mouse, zoom with right', 'view-fullscreen-symbolic', 'pan'),
        ('Zoom', 'Zoom to rectangle', 'edit-select-all-symbolic', 'zoom'),
        (None, None, None, None),
        ('Save', 'Save the figure', 'media-floppy-symbolic', 'save_figure'),
    )

    def _init_toolbar(self):
        for text, tooltip_text, icon, callback in self.toolitems:
            if text is None:
                self.insert(Gtk.SeparatorToolItem(), -1)
                continue

            tbutton = Gtk.ToolButton.new(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
            tbutton.set_label(text)
            self.insert(tbutton, -1)
            tbutton.connect('clicked', getattr(self, callback))
            tbutton.set_tooltip_text(tooltip_text)

        toolitem = Gtk.SeparatorToolItem()
        self.insert(toolitem, -1)
        toolitem.set_draw(False)
        toolitem.set_expand(True)

        toolitem = Gtk.ToolItem()
        self.insert(toolitem, -1)

        self.message = Gtk.Label()
        self.message.get_style_context().add_class('plot-tool-message')
        toolitem.add(self.message)
        self.set_style(Gtk.ToolbarStyle.ICONS)
        self.set_icon_size(Gtk.IconSize.BUTTON)
        self.show_all()


class Plotter(Gtk.Alignment):
    def __init__(self, loop=False, buffer_size=2500, xformat='%g', dpi=96):
        super(Plotter, self).__init__()
        self.set(0.5, 0.5, 1, 1)
        rcParams['legend.loc'] = 'best'
        rcParams['legend.fontsize'] = 8.5
        rcParams['legend.isaxes'] = False
        rcParams['figure.facecolor'] = 'white'
        rcParams['figure.edgecolor'] = 'white'
        self.fig = Figure(figsize=(10, 8), dpi=dpi, facecolor='w')
        self.axis = []
        self.axis.append(self.fig.add_subplot(111))
        self.format_x = FormatStrFormatter(xformat)
        self.axis[0].xaxis.set_major_formatter(self.format_x)
        self.axis[0].yaxis.tick_left()
        self.line = []
        self.x_data = []
        self.y_data = []

        # variables used for grid plotting
        self.grid_data = None
        self.grid_mode = False
        self.grid_specs = None
        self.simulate_ring_buffer = loop
        self.buffer_size = buffer_size

        self.canvas = FigureCanvas(self.fig)  # a Gtk.DrawingArea
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toolbar = PlotterToolbar(self.canvas, dialogs.MAIN_WINDOW)

        box.pack_start(self.canvas, True, True, 0)
        box.pack_start(self.toolbar, False, False, 0)
        self.add(box)
        self.show_all()

    def add_line(self, xpoints, ypoints, pattern='', label='', lw=1, ax=0, alpha=1.0, color=None, redraw=True, markevery=[]):
        assert (len(xpoints) == len(ypoints))
        assert (ax < len(self.axis))

        self.axis[ax].autoscale(False)
        ymin_current, ymax_current = self.axis[ax].get_ylim()
        xmin_current, xmax_current = self.axis[ax].get_xlim()
        line, = self.axis[ax].plot(
            xpoints, ypoints, 'o', ls=pattern, lw=lw, markersize=3, markerfacecolor='w',
            label=label, alpha=alpha, markevery=markevery, color=color
        )
        self.line.append(line)

        self.x_data.append(list(xpoints))
        self.y_data.append(list(ypoints))

        # adjust axes limits as necessary
        xmin, xmax = misc.get_min_max(self.x_data[-1], ldev=0, rdev=0)
        ymin, ymax = misc.get_min_max(self.y_data[-1], ldev=1, rdev=1)

        ymin, ymax = min(ymin, ymin_current), max(ymax, ymax_current)
        xmin, xmax = min(xmin, xmin_current), max(xmax, xmax_current)

        self.line[-1].axes.set_xlim(xmin, xmax)
        self.line[-1].axes.set_ylim(ymin, ymax)
        self.line[-1].axes.xaxis.set_major_formatter(self.format_x)

        if redraw:
            self.canvas.draw_idle()
        return True

    def add_axis(self, label=""):
        ax = self.fig.add_axes(self.axis[0].get_position(), sharex=self.axis[0], frameon=False)
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position('right')
        ax.set_ylabel(label)
        for label in ax.get_xticklabels():
            label.set_visible(False)
        self.axis.append(ax)
        return len(self.axis) - 1

    def set_labels(self, title="", x_label="", y1_label=""):
        self.axis[0].set_title(title)
        self.axis[0].set_xlabel(x_label)
        self.axis[0].set_ylabel(y1_label)

    def set_time_labels(self, labels, fmt, maj_int, min_int):
        self.axis[0].xaxis.set_major_locator(MinuteLocator(interval=maj_int))
        self.axis[0].xaxis.set_minor_locator(SecondLocator(interval=min_int))
        if len(self.axis[0].xaxis.get_major_ticks()) < len(labels):
            labels.pop(0)
        self.axis[0].set_xticklabels([d is not ' ' and d.strftime(fmt) or '' for d in labels])

    def clear(self, grid=False):
        self.fig.clear()
        self.axis = []
        self.axis.append(self.fig.add_subplot(111))
        self.line = []
        self.x_data = []
        self.y_data = []
        self.grid_mode = grid
        if not self.grid_mode:
            self.grid_data = None
            self.grid_specs = None
            self.axis[0].xaxis.set_major_formatter(self.format_x)

    def set_grid(self, data):
        self.grid_data = numpy.zeros((data['steps'], data['steps']))
        self.grid_specs = data
        bounds = [data['start_1'], data['end_1'], data['start_2'], data['end_2']]
        self.grid_plot = self.axis[0].imshow(self.grid_data, interpolation='bicubic',
                                             origin='lower', extent=bounds, aspect="auto")

    def add_grid_point(self, xv, yv, z, redraw=True):
        if self.grid_data is not None and self.grid_specs is not None:
            xl = numpy.linspace(self.grid_specs['start_1'], self.grid_specs['end_1'], self.grid_specs['steps'])
            yl = numpy.linspace(self.grid_specs['start_2'], self.grid_specs['end_2'], self.grid_specs['steps'])
            x = numpy.abs(xl - xv).argmin()  # find index of value closest to xv
            y = numpy.abs(yl - yv).argmin()  # find index of value closest to yv
            my, mx = self.grid_data.shape
            if (0 <= x < mx) and (0 <= y < my):
                self.grid_data[y, x] = z
                self.grid_plot.set_array(self.grid_data)
                self.grid_plot.set_norm(Normalize(vmin=self.grid_data.min(), vmax=self.grid_data.max()))
                self.canvas.draw_idle()
        return True

    def add_point(self, x, y, lin=0, redraw=True, resize=False):
        if lin >= len(self.line):
            self.add_line([x], [y], '-', markevery=[-1])
        else:
            # when using ring buffer, remove first element before adding if full
            if self.simulate_ring_buffer and len(self.x_data[lin]) == self.buffer_size:
                self.x_data[lin] = self.x_data[lin][1:]
                self.y_data[lin] = self.y_data[lin][1:]

            # add points to end of line        
            self.x_data[lin].append(x)
            self.y_data[lin].append(y)

            # update the line data
            self.line[lin].set_data(self.x_data[lin], self.y_data[lin])

            # adjust axes limits as necessary
            ymin_current, ymax_current = self.line[lin].axes.get_ylim()

            ymin, ymax = misc.get_min_max(self.y_data[lin], ldev=1, rdev=1)
            xmin, xmax = misc.get_min_max(self.x_data[lin], ldev=0, rdev=0)

            if len(self.line) > 1:
                xmin_current, xmax_current = self.axis[0].get_xlim()
                self.axis[0].set_xlim(min(xmin, xmin_current), max(xmax, xmax_current))
            else:
                self.line[lin].axes.set_xlim(xmin, xmax)
            self.line[lin].axes.set_ylim(min(ymin, ymin_current), max(ymax, ymax_current))
            self.axis[0].xaxis.set_major_formatter(self.format_x)

            if redraw:
                self.redraw()

    def redraw(self):
        self.axis[0].legend()
        self.canvas.draw_idle()


class ScanPlotter(Gtk.Box):
    implements(IScanPlotter)

    def __init__(self):
        super(ScanPlotter, self).__init__(orientation=Gtk.Orientation.VERTICAL)
        self.plotter = Plotter(self)
        self.plotter.set_size_request(577, 400)
        self.pack_start(self.plotter, True, True, 0)
        self.prog_bar = ActiveProgressBar()
        self.prog_bar.set_fraction(0.0)
        self.prog_bar.idle_text('0%')

        self.pack_start(self.prog_bar, False, False, 0)
        globalRegistry.register([], IScanPlotter, '', self)
        self._sig_handlers = {}
        self.show_all()
        self.fit = {}
        self.grid_scan = False

    def connect_scanner(self, scan):
        _sig_map = {
            'started': self.on_start,
            'progress': self.on_progress,
            'new-point': self.on_new_point,
            'error': self.on_error,
            'done': self.on_done,
            'stopped': self.on_stop
        }

        # connect signals.
        scan.connect('started', self.on_start)
        scan.connect('new-point', self.on_new_point)
        scan.connect('progress', self.on_progress)
        scan.connect('done', self.on_done)
        scan.connect('error', self.on_error)
        scan.connect('error', self.on_stop)

    def on_start(self, scan, data=None):
        """Clear Scan and setup based on contents of data dictionary."""
        data = scan.get_specs()
        if data.get('type', '').lower() == 'grid':
            self.plotter.clear(grid=True)
            self.plotter.set_grid(data)
            self.grid_scan = True
        else:
            self.grid_scan = False
            self.plotter.clear()
        self._start_time = time.time()
        self.plotter.set_labels(title=scan.__doc__,
                                x_label=scan.data_names[0],
                                y1_label=scan.data_names[1])

    def on_progress(self, scan, fraction, msg):
        """Progress handler."""
        elapsed_time = time.time() - self._start_time
        if fraction > 0:
            time_unit = elapsed_time / fraction
        else:
            time_unit = 0.0

        eta_time = time_unit * (1 - fraction)
        # percent = fraction * 100
        text = "ETA %s" % (time.strftime('%H:%M:%S', time.gmtime(eta_time)))
        self.prog_bar.set_complete(fraction, text)

    def on_new_point(self, scan, data):
        """New point handler."""

        if self.grid_scan:
            self.plotter.add_grid_point(data[0], data[1], data[2])
        else:
            self.plotter.add_point(data[0], data[1])

    def on_stop(self, scan):
        """Stop handler."""
        self.prog_bar.set_text('Scan Stopped!')

    def on_error(self, scan, reason):
        """Error handler."""
        self.prog_bar.set_text('Scan Error: %s' % (reason,))

    def on_done(self, scan):
        """Done handler."""
        filename = scan.save()
        self.plot_file(filename)

    def plot_file(self, filename):
        """Do fitting and plot Fits"""
        # image_filename = "%s.ps" % filename
        info = self._get_scan_data(filename)
        if info['scan_type'] == 'GridScan':
            data = info['data']

            xd = data[:, 0]
            yd = data[:, 1]
            zd = data[:, 4]

            xlo = xd[0]
            xhi = xd[-1]
            ylo = yd[0]
            yhi = yd[-1]

            xmin = min(xd)
            xmax = max(xd)
            ymin = min(yd)
            ymax = max(yd)

            if info['dim'] != 0:
                szx = info['dim']
                szy = len(xd) / szx
            else:
                szx = int(numpy.sqrt(len(xd)))
                szy = szx

            x = numpy.linspace(xmin, xmax, szx)
            y = numpy.linspace(ymin, ymax, szy)
            z = zd.reshape(szy, szx)
            X, Y = numpy.meshgrid(x, y)

            if xlo > xhi:
                z = z[:, ::-1]
            if ylo > yhi:
                z = z[::-1, :]

            self.plotter.clear()
            ax = axes3d.Axes3D(self.plotter.fig)
            ax.set_title('%s\n%s' % (info['title'], info['subtitle']))
            ax.set_xlabel(info['x_label'])
            ax.set_ylabel(info['y_label'])
            ax.contour3D(X, Y, z, 50)
            self.plotter.canvas.draw()

        else:
            data = info['data']
            # image_filename = "%s.ps" % filename
            xo = data[:, 0]
            yo = data[:, -1]

            params, _ = fitting.peak_fit(xo, yo, 'gaussian')
            yc = fitting.gauss(xo, params)

            fwhm = params[1]
            # fwxl = [params[1]-0.5*fwhm, params[1]+0.5*fwhm]
            # fwyl = [0.5 * params[0] + params[3], 0.5 * params[0] + params[3]]
            # pkyl = [params[3],params[0]+params[3]]
            # pkxl = [params[1],params[1]]

            # [ymax, fwhm, xpeak, x_hpeak[0], x_hpeak[1], cema]
            histo_pars, _ = fitting.histogram_fit(xo, yo)

            self.plotter.clear()
            ax = self.plotter.axis[0]
            ax.set_title('%s\n%s' % (info['title'], info['subtitle']))
            ax.set_xlabel(info['x_label'])
            ax.set_ylabel(info['y_label'])
            # ax.plot(xo,yo,'b-+')
            # ax.plot(xo,yc,'r--')
            self.plotter.add_line(xo, yo, pattern='b-+', redraw=False)
            self.plotter.add_line(xo, yc, pattern='r--', redraw=False)
            hh = 0.5 * (max(yo) - min(yo)) + min(yo)
            ax.plot([histo_pars[2], histo_pars[2]], [min(yo), max(yo)], 'b:')
            ax.plot([histo_pars[3], histo_pars[4]], [hh, hh], 'b:')
            ax.set_xlim(min(xo), max(xo))

            # set font parameters for the ouput table
            fontpar = {}
            fontpar["family"] = "monospace"
            fontpar["size"] = 8
            info = "YMAX-fit = %11.4e\n" % params[0]
            info += "MIDP-fit = %11.4e\n" % params[2]
            info += "FWHM-fit = %11.4e\n" % fwhm
            print info
            self.plotter.fig.text(0.65, 0.75, info, fontdict=fontpar, color='r')
            info = "YMAX-his = %11.4e\n" % histo_pars[0]
            info += "MIDP-his = %11.4e\n" % histo_pars[2]
            info += "FWHM-his = %11.4e\n" % histo_pars[1]
            info += "CEMA-his = %11.4e\n" % histo_pars[5]
            self.plotter.fig.text(0.65, 0.60, info, fontdict=fontpar, color='b')
            self.plotter.canvas.draw()
            print info
            self.fit['midp'] = params[2]
            self.fit['fwhm'] = fwhm
            self.fit['ymax'] = params[0]

    def _get_scan_data(self, filename):
        lines = file(filename).readlines()
        title = lines[0].split(': ')[1][:-1]
        x_title = lines[3].split(': ')[1][:-1]
        y_title = lines[4].split(': ')[1][:-1]
        scan_type = title.split(' -- ')[0]
        data = numpy.loadtxt(filename, comments='#')
        t = os.stat(filename).st_ctime
        timestr = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.localtime(t))
        if scan_type == 'GridScan':
            # dim = int(lines[6].split(': ')[1][:-1])
            dim = 0
        else:
            dim = 0
        return {'scan_type': scan_type, 'x_label': x_title, 'y_label': y_title,
                'title': title, 'data': data, 'subtitle': timestr, 'dim': dim}


class ScanPlotWindow(Gtk.Window):
    def __init__(self):
        GObject.GObject.__init__(self)
        self.plot = ScanPlotter()
        self.add(self.plot)
        self.show_all()
