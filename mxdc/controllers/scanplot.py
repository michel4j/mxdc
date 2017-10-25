from __future__ import print_function

import time

import numpy
from mpl_toolkits.mplot3d import axes3d
from mxdc.engines.interfaces import IScanPlotter
from mxdc.utils import fitting
from mxdc.utils import xdi
from mxdc.widgets import plotter
from twisted.python.components import globalRegistry
from zope.interface import implements


class ScanPlotter(object):
    implements(IScanPlotter)

    def __init__(self, widget):
        self.plotter = plotter.Plotter()
        self.widget = widget
        self.widget.scan_box.pack_start(self.plotter, True, True, 0)
        self._sig_handlers = {}

        self.fit = {}
        self.grid_scan = False
        self.start_time = 0
        globalRegistry.register([], IScanPlotter, '', self)

    def link_scan(self, scan):
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
        self.start_time = time.time()

        xname = scan.data_types['names'][0]
        yname = scan.data_types['names'][1]
        self.plotter.set_labels(
            title=scan.__doc__,
            x_label='{} ({})'.format(xname, scan.units.get(xname, '...')),
            y1_label='{} ({})'.format(yname, scan.units.get(yname, '...')),
        )

    def on_progress(self, scan, fraction, message):
        used_time = time.time() - self.start_time
        remaining_time = (1 - fraction) * used_time / fraction
        eta_time = remaining_time
        self.widget.scan_eta.set_text('{:0>2.0f}:{:0>2.0f} ETA'.format(*divmod(eta_time, 60)))
        self.widget.scan_pbar.set_fraction(fraction)
        self.widget.scan_progress_lbl.set_text(message)

    def on_new_point(self, scan, data):
        if self.grid_scan:
            self.plotter.add_grid_point(data[0], data[1], data[2])
        else:
            self.plotter.add_point(data[0], data[1])

    def on_stop(self, scan):
        """Stop handler."""
        self.widget.scan_progress_lbl.set_text('Scan Stopped!')

    def on_error(self, scan, reason):
        """Error handler."""
        self.widget.scan_progress_lbl.set_text('Scan Error: %s' % (reason,))

    def on_done(self, scan):
        """Done handler."""
        filename = scan.save()
        self.plot_file(filename)

    def plot_file(self, filename):
        """Do fitting and plot Fits"""
        info = xdi.read_xdi(filename)
        columns = info['Column'].items()
        data = info.data
        if info['CMCF.scan_type'] == 'GridScan':
            xcol = columns[0]
            ycol = columns[1]
            zcol = columns[4]

            x_label = '{} {}'.format(xcol.value[1].title(), '({})'.format(xcol[1].units) if xcol[1].units else '')
            y_label = '{} {}'.format(ycol.value[1].title(), '({})'.format(ycol[1].units) if ycol[1].units else '')

            xd = data[xcol[1].value]
            yd = data[ycol[1].value]
            zd = data[zcol[1].value]

            xlo = xd[0]
            xhi = xd[-1]
            ylo = yd[0]
            yhi = yd[-1]

            xmin = min(xd)
            xmax = max(xd)
            ymin = min(yd)
            ymax = max(yd)

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
            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            ax.contour3D(X, Y, z, 50)
            self.plotter.canvas.draw()

        else:
            xcol = columns[0]
            ycol = columns[1]

            x_label = '{} {}'.format(xcol[1].value.title(), '({})'.format(xcol[1].units) if xcol[1].units else '')
            y_label = '{} {}'.format(ycol[1].value.title(), '({})'.format(ycol[1].units) if ycol[1].units else '')

            xo = data[xcol[1].value]
            yo = data[ycol[1].value]

            params, _ = fitting.peak_fit(xo, yo, 'gaussian')
            yc = fitting.gauss(xo, params)

            fwhm = params[1]
            histo_pars, _ = fitting.histogram_fit(xo, yo)

            self.plotter.clear()
            ax = self.plotter.axis[0]

            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            self.plotter.add_line(xo, yo, '-')
            self.plotter.add_line(xo, yc, '-')
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
            print(info)
            self.plotter.fig.text(0.65, 0.75, info, fontdict=fontpar, color='r')
            info = "YMAX-his = %11.4e\n" % histo_pars[0]
            info += "MIDP-his = %11.4e\n" % histo_pars[2]
            info += "FWHM-his = %11.4e\n" % histo_pars[1]
            info += "CEMA-his = %11.4e\n" % histo_pars[5]
            self.plotter.fig.text(0.65, 0.60, info, fontdict=fontpar, color='b')
            self.plotter.canvas.draw()
            print(info)
            self.fit['midp'] = params[2]
            self.fit['fwhm'] = fwhm
            self.fit['ymax'] = params[0]
