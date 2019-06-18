import os

import numpy
from gi.repository import Gtk
from matplotlib import rcParams
from matplotlib.backends.backend_gtk3 import NavigationToolbar2GTK3 as NavigationToolbar
from matplotlib.backends.backend_gtk3cairo import FigureCanvasGTK3Cairo as FigureCanvas
from matplotlib.colors import Normalize
from matplotlib.dates import MinuteLocator, SecondLocator
from matplotlib.figure import Figure
from matplotlib.ticker import FormatStrFormatter
from mxdc.utils import misc
from mxdc.widgets import dialogs

rcParams['legend.loc'] = 'best'
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


class PlotterToolbar(NavigationToolbar):
    toolitems = (
        ('Home', 'Reset original view', 'go-home-symbolic', 'home'),
        ('Back', 'Back to  previous view', 'go-previous-symbolic', 'back'),
        ('Forward', 'Forward to next view', 'go-next-symbolic', 'forward'),
        (None, None, None, None),
        ('Pan', 'Pan axes with left mouse, zoom with right', 'view-fullscreen-symbolic', 'pan'),
        ('Zoom', 'Zoom to rectangle', 'zoom-fit-best-symbolic', 'zoom'),
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
        rcParams['figure.facecolor'] = 'white'
        rcParams['figure.edgecolor'] = 'white'
        self.fig = Figure(figsize=(10, 8), dpi=dpi, facecolor='w')
        self.axis = []
        self.axis.append(self.fig.add_subplot(111))
        self.format_x = FormatStrFormatter(xformat)
        self.axis[0].ticklabel_format(scilimits=(4,4))
        #self.axis[0].xaxis.set_major_formatter(self.format_x)
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
            xpoints, ypoints, 'o', ls=pattern, lw=lw, markersize=4, markerfacecolor='w',
            label=label, alpha=alpha, markevery=markevery, color=color
        )
        self.line.append(line)

        self.x_data.append(list(xpoints))
        self.y_data.append(list(ypoints))

        # adjust axes limits as necessary
        xmin, xmax = misc.get_min_max(self.x_data[-1], ldev=0, rdev=0)
        ymin, ymax = misc.get_min_max(self.y_data[-1], ldev=1, rdev=1)

        #ymin, ymax = min(ymin, ymin_current), max(ymax, ymax_current)
        xmin, xmax = min(xmin, xmin_current), max(xmax, xmax_current)

        self.line[-1].axes.set_xlim(xmin, xmax)
        self.line[-1].axes.set_ylim(ymin, ymax)
        #self.line[-1].axes.xaxis.set_major_formatter(self.format_x)
        self.line[-1].axes.ticklabel_format(scilimits=(4, 4))

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
            #self.axis[0].xaxis.set_major_formatter(self.format_x)

    def set_grid(self, data):
        self.grid_data = numpy.zeros((data['steps'], data['steps']))
        self.grid_specs = data
        bounds = [data['start_1'], data['end_1'], data['start_2'], data['end_2']]
        self.grid_plot = self.axis[0].imshow(self.grid_data, interpolation='bicubic',
                                             origin='lower', extent=bounds, aspect="auto")

    def add_grid_point(self, xv, yv, z, redraw=True, resize=False):
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

            ymin, ymax = misc.get_min_max(self.y_data[lin], ldev=0.5, rdev=0.5)
            xmin, xmax = misc.get_min_max(self.x_data[lin], ldev=0, rdev=0)
            if len(self.line) > 1:
                xmin_current, xmax_current = self.axis[0].get_xlim()
                self.axis[0].set_xlim(min(xmin, xmin_current), max(xmax, xmax_current))
            else:
                self.line[lin].axes.set_xlim(xmin, xmax)
            self.line[lin].axes.set_ylim(ymin, ymax)
            self.line[lin].axes.ticklabel_format(scilimits=(4, 4))
            #self.axis[0].xaxis.set_major_formatter(self.format_x)

            if redraw:
                self.redraw()

    def redraw(self):
        self.axis[0].legend()
        self.canvas.draw_idle()
