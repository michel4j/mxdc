
import numpy

from gi.repository import Gtk, GObject
from matplotlib.backends.backend_gtk3 import NavigationToolbar2GTK3, ToolbarGTK3
from matplotlib.backends.backend_gtk3cairo import FigureCanvasGTK3Cairo as FigureCanvas
from matplotlib.colors import Normalize
from matplotlib import cm, transforms
from matplotlib.dates import MinuteLocator, SecondLocator
from matplotlib.figure import Figure
from matplotlib.ticker import FormatStrFormatter, ScalarFormatter
from mxdc.utils import misc
from mxdc.widgets import dialogs

GRID_COLORMAP = 'viridis'
GRID_INTERPOLATION = 'nearest'  # nearest


class PlotterToolbar(NavigationToolbar2GTK3):

    toolitems = (
        ('Home', 'Reset original view', 'go-home', 'home'),
        ('Back', 'Back to  previous view', 'go-previous', 'back'),
        ('Forward', 'Forward to next view', 'go-next', 'forward'),
        (None, None, None, None),
        ('Pan', 'Pan axes with left mouse, zoom with right', 'view-fullscreen', 'pan'),
        ('Zoom', 'Zoom to rectangle', 'zoom-fit-best', 'zoom'),
        (None, None, None, None),
        ('Save', 'Save the figure', 'media-floppy', 'save_figure'),
    )

    def __init__(self, canvas, window):
        super().__init__(canvas, window)
        for i, toolitem in enumerate(self):
            if isinstance(toolitem, Gtk.ToolButton):
                icon_name = f'{self.toolitems[i][2]}-symbolic'
                image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.SMALL_TOOLBAR)
                toolitem.set_icon_widget(image)


    # toolitems = (
    #     ('Home', 'Reset original view', 'go-home-symbolic', 'home'),
    #     ('Back', 'Back to  previous view', 'go-previous-symbolic', 'back'),
    #     ('Forward', 'Forward to next view', 'go-next-symbolic', 'forward'),
    #     (None, None, None, None),
    #     ('Pan', 'Pan axes with left mouse, zoom with right', 'view-fullscreen-symbolic', 'pan'),
    #     ('Zoom', 'Zoom to rectangle', 'zoom-fit-best-symbolic', 'zoom'),
    #     (None, None, None, None),
    #     ('Save', 'Save the figure', 'media-floppy-symbolic', 'save_figure'),
    # )
    #
    # def _init_toolbar(self):
    #     self.set_style(Gtk.ToolbarStyle.ICONS)
    #
    #     self._gtk_ids = {}
    #     for text, tooltip_text, icon, callback in self.toolitems:
    #         if text is None:
    #             self.insert(Gtk.SeparatorToolItem(), -1)
    #             continue
    #         self._gtk_ids[text] = tbutton = Gtk.ToolButton.new(
    #             Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR)
    #         )
    #         tbutton.set_label(text)
    #         self.insert(tbutton, -1)
    #         tbutton.connect('clicked', getattr(self, callback))
    #         tbutton.set_tooltip_text(tooltip_text)
    #
    #     toolitem = Gtk.SeparatorToolItem()
    #     self.insert(toolitem, -1)
    #     toolitem.set_draw(False)
    #     toolitem.set_expand(True)
    #
    #     toolitem = Gtk.ToolItem()
    #     self.insert(toolitem, -1)
    #     self.message = Gtk.Label()
    #     toolitem.add(self.message)
    #     self.set_icon_size(Gtk.IconSize.SMALL_TOOLBAR)
    #     self.show_all()


class Plotter(Gtk.Alignment):
    def __init__(self, loop=False, buffer_size=2500, xformat='%g', dpi=80):
        super().__init__()
        self.set(0.5, 0.5, 1, 1)

        self.format_x = FormatStrFormatter(xformat)
        self.ring_buffer = loop
        self.buffer_size = buffer_size
        self.colormap = cm.get_cmap('Dark2')
        self.axis_space = 0.92
        self.cursor_line = None
        self.cursor_points = {}
        self.plot_scales = {}
        self.lines = {}

        self.axis = {}
        self.data_type = {}
        self.values = None

        self.grid_mode = False
        self.grid_specs = {}
        self.grid_image = None
        self.grid_norm = Normalize()
        self.grid_snake = False

        self.fig = Figure(figsize=(10, 6), dpi=dpi)
        self.clear()

        self.canvas = FigureCanvas(self.fig)  # a Gtk.DrawingArea
        self.canvas.mpl_connect('motion_notify_event', self.on_mouse_motion)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toolbar = PlotterToolbar(self.canvas, dialogs.MAIN_WINDOW)

        box.pack_start(self.canvas, True, True, 0)
        box.pack_start(self.toolbar, False, False, 0)
        self.add(box)
        self.show_all()

    def clear(self, specs=None):
        """
        Clear the plot and configure it for the given specifications.

        :param specs: dictionary containing configuration parameters
        """
        self.fig.clear()
        self.fig.subplots_adjust(bottom=0.1, left=0.05, top=0.90, right=self.axis_space)
        specs = {} if specs is None else specs
        self.grid_mode = 'grid' in specs.get('scan_type', '')
        self.data_type = specs.get('data_type')
        self.values = misc.RecordArray(self.data_type, size=self.buffer_size, loop=self.ring_buffer)
        self.cursor_line = None
        self.lines = {}
        self.grid_snake = specs.get('grid_snake', False)
        self.grid_specs = {}
        self.grid_image = None
        self.grid_norm = Normalize()

        ax = self.fig.add_subplot(111)
        ax.yaxis.tick_right()
        ax.yaxis.set_major_formatter(ScalarFormatter())
        self.axis = {'default': ax}


        if specs:
            names = self.data_type['names'][1:]
            scales = specs.get('data_scale')
            if scales:
                self.plot_scales = {
                    ('default' if i == 0 else 'axis-{}'.format(i)): scale
                    for i, scale in enumerate(scales)
                }
            else:
                self.plot_scales = {
                    ('default' if i == 0 else 'axis-{}'.format(i)): (name,)
                    for i, name in enumerate(names)
                }

    def get_axis_for(self, name):
        """
        Return the axis for the named line

        :param name: line name
        :return: an axis object
        """
        return self.lines[name].axes

    def add_axis(self, name=None, label=""):
        """
        Add a named axis to the plot with the

        :param name: axis name
        :param label: axis label
        :return: matplotlib axis object
        """
        name = 'axis-{}'.format(len(self.axis)) if not name else name
        default = self.axis.get('default')
        index = len(self.axis) + 1
        axis_position = 1 / (self.axis_space ** (index - 1))
        self.fig.subplots_adjust(right=self.axis_space ** index)
        ax = self.fig.add_axes(default.get_position(), sharex=default, frameon=False)
        ax.spines['right'].set_position(('axes', axis_position))
        ax.yaxis.set_major_formatter(ScalarFormatter())
        ax.set_frame_on(True)
        ax.patch.set_visible(False)

        ax.yaxis.tick_right()
        ax.yaxis.set_label_position('right')
        ax.set_ylabel(label)
        for label in ax.get_xticklabels():
            label.set_visible(False)
        self.axis[name] = ax
        self.plot_scales[name] = ()
        return ax

    def add_line(self, xpoints, ypoints, style='-', name='', lw=1, axis="default", alpha=1.0, color=None, redraw=True,
                 markevery=[]):
        """
        Add a named line to the plot

        :param xpoints: initial x axis values
        :param ypoints: initial y axis values
        :param style: matplotlib line style string
        :param name: line name, optional
        :param lw: line width
        :param axis: optional name of axis of add line to
        :param alpha: line transparency
        :param color: line color
        :param redraw: whether to redraw the line or note
        :param markevery: matplotlit 'markevery' parameter, set to None to show markers at every point
        """
        assert (len(xpoints) == len(ypoints))

        if axis not in self.axis:
            self.add_axis(axis)

        name = 'line-{}'.format(len(self.lines)) if not name else name
        color = self.colormap(len(self.lines)) if not color else color
        self.axis[axis].autoscale(False)
        xmin_current, xmax_current = self.axis[axis].get_xlim()
        ymin_current, ymax_current = self.axis[axis].get_ylim()
        line, = self.axis[axis].plot(
            xpoints, ypoints, '.', ls=style, lw=lw, markersize=8,
            label=name, alpha=alpha, markevery=markevery, color=color
        )

        # adjust axes limits as necessary
        xmin, xmax = misc.get_min_max(xpoints, ldev=0, rdev=0)
        ymin, ymax = misc.get_min_max(ypoints, ldev=1, rdev=1)

        xmin, xmax = min(xmin, xmin_current), max(xmax, xmax_current)
        ymin, ymax = min(ymin, ymin_current), max(ymax, ymax_current)
        line.axes.set_xlim(xmin, xmax)
        line.axes.set_ylim(ymin, ymax)
        self.lines[name] = line
        if name not in self.plot_scales[axis]:
            self.plot_scales[axis] += (name,)

        if len(xpoints) > 1:
            self.values.add_func(name, xpoints, ypoints)

        if redraw:
            self.redraw()

    def add_point(self, row, redraw=True):
        """
        Add a row of scan points to the data table

        :param row: sequence of values to add
        :param redraw: Whether to redraw the plot
        """

        if numpy.nan in row:
            return

        self.values.append(row)
        x_name = self.data_type['names'][0]
        if self.grid_mode:
            # no lines for grid mode
            self.update_grid_data()
        elif not self.lines:
            count = 0
            for axis, lines in self.plot_scales.items():
                if axis != 'default':
                    self.add_axis(name=axis)
                for line in lines:
                    self.add_line(
                        self.values.data[x_name], self.values.data[line], color=self.colormap(count),
                        name=line, axis=axis, markevery=[-1]
                    )
                    count += 1
        else:
            xmin, xmax = misc.get_min_max(self.values.data[x_name], ldev=0, rdev=0)
            for axis, lines in self.plot_scales.items():
                ymin = ymax = None
                ax = None
                for name in lines:
                    line = self.lines[name]
                    line.set_data(self.values.data[x_name], self.values.data[name])
                    ax = line.axes
                    ylo, yhi = misc.get_min_max(self.values.data[name], ldev=0.5, rdev=0.5)
                    if ymin is None:
                        ymin, ymax = ylo, yhi
                    else:
                        ymin, ymax = min(ymin, ylo), max(ymax, yhi)
                        ymin, ymax = ymin, ymax

                # adjust axes limits as necessary
                if ax is not None:
                    offset = (ymax - ymin) * .1
                    ax.set_ylim(ymin - offset, ymax + offset)
                    ax.set_xlim(xmin, xmax)

            if len(self.lines) > 1:
                default = self.axis.get('default')
                xmin_current, xmax_current = default.get_xlim()
                default.set_xlim(min(xmin, xmin_current), max(xmax, xmax_current))

        if redraw:
            self.redraw()

    def new_row(self, index):
        """
        Prepare for A new row of data
        :param index: row index for next row
        """

        if self.grid_mode and index > 1:
            # for slew grid scans, data needs to be padded/truncated
            y_name = self.data_type['names'][1]
            yo = self.values.data[y_name]

            x_size = (yo == yo[0]).sum()
            y_size = index
            pad = x_size * y_size - yo.shape[0]
            if pad == 0:
                return
            elif pad > 0:
                for i in range(pad):
                    self.values.append(self.values.data[-1])  # padding
            elif pad < 0:
                self.values.length = x_size * y_size
            self.update_grid_data()

    def update_grid_data(self):
        """
        Update the grid image values
        """
        x_name, y_name, counts_name = self.data_type['names'][:3]
        xo = self.values.data[x_name]
        yo = self.values.data[y_name]
        counts = self.values.data[counts_name]

        x_min, x_max = xo.min(), xo.max()
        y_min, y_max = yo.min(), yo.max()

        self.grid_norm.autoscale(counts)

        xsize = (yo == yo[0]).sum()
        ysize = int(numpy.ceil(yo.shape[0] / xsize))

        # pad unfilled values with nan
        blanks = xsize * ysize - counts.shape[0]
        if blanks:
            counts = numpy.pad(counts, (0, blanks), 'constant', constant_values=(numpy.nan, numpy.nan))

        count_data = numpy.resize(counts, (ysize, xsize))

        # flip alternate rows
        if self.grid_snake:
            count_data[1::2, :] = count_data[1::2, ::-1]

        self.grid_specs.update({
            'x': xo,
            'y': yo,
            'counts': count_data,
        })
        extent = [
            x_min, x_max,
            y_min, y_max,
        ]
        if self.grid_image is None:
            default = self.axis.get('default')
            self.grid_image = default.imshow(
                self.grid_specs['counts'], cmap=cm.get_cmap(GRID_COLORMAP), origin='lower',
                norm=self.grid_norm, extent=extent, aspect='auto',
                interpolation=GRID_INTERPOLATION,
            )
        else:
            self.grid_image.set_data(self.grid_specs['counts'])
            self.grid_image.set_extent(extent)

        # set axis limits
        self.grid_image.axes.set_xlim(extent[:2])
        self.grid_image.axes.set_ylim(extent[-2:])
        self.redraw()

    def get_records(self):
        """
        Return the data array manager for the plot
        """
        return self.values

    def set_labels(self, title="", x_label="", y1_label=""):
        default = self.axis.get('default')
        default.set_xlabel(x_label, ha='right', va='top')
        default.set_ylabel(y1_label)
        default.xaxis.set_label_coords(1.0, -0.075)

    def set_time_labels(self, labels, fmt, maj_int, min_int):
        default = self.axis.get('default')
        default.xaxis.set_major_locator(MinuteLocator(interval=maj_int))
        default.xaxis.set_minor_locator(SecondLocator(interval=min_int))
        if len(default.xaxis.get_major_ticks()) < len(labels):
            labels.pop(0)
        default.set_xticklabels([d != ' ' and d.strftime(fmt) or '' for d in labels])

    def redraw(self):
        if not self.grid_mode:
            lines = list(self.lines.values())
            labels = list(self.lines.keys())
            self.axis['default'].legend(
                lines, labels, loc='upper left', bbox_to_anchor=(0, 1.075), ncol=8, fancybox=False,
                framealpha=0.0, edgecolor='inherit', borderaxespad=0, fontsize=9
            )
        self.canvas.draw_idle()

    def on_mouse_motion(self, event):
        default = self.axis.get('default')

        if event.inaxes and self.lines and not self.grid_mode:
            x, y = event.xdata, event.ydata

            if self.cursor_line is None:
                self.cursor_line = default.axvline(x, lw=1, color='#3a7ca8', antialiased=None)
                for axis, lines in self.plot_scales.items():
                    for name in lines:
                        y_value = self.values(name, x)
                        ax = self.axis[axis]
                        if name in self.lines:
                            line = self.lines[name]
                            trans = transforms.blended_transform_factory(
                                ax.get_yticklabels()[0].get_transform(), ax.transData
                            )
                            self.cursor_points[name] = ax.text(
                                1, y_value, "< {}".format(name), color=line.get_color(), transform=trans, ha="left",
                                va="center"
                            )
            else:
                self.cursor_line.set_xdata(x)
                for axis, lines in self.plot_scales.items():
                    for name in lines:
                        if name in self.lines:
                            y_value = self.values(name, x)
                            if name in self.cursor_points:
                                self.cursor_points[name].set_position((1, y_value))
            self.canvas.draw_idle()
        else:
            if self.cursor_line:
                self.cursor_line.remove()
                self.cursor_line = None
                for name in list(self.cursor_points.keys()):
                    mark = self.cursor_points.pop(name)
                    mark.remove()
                self.canvas.draw_idle()
