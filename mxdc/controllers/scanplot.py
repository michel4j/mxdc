

import time

import numpy
from zope.interface import implementer

from mxdc import Registry
from mxdc.engines.interfaces import IScanPlotter
from mxdc.utils import fitting
from mxdc.widgets import plotter


class Fit(object):
    def __init__(self, plot):
        self.name = "Scan Fitter"
        self.plotter = plot
        self.info = {
            'midp': None, 'ymax': None, 'fwhm': None, 'cema': None,
            'midp_hist': None, 'fwhm_hist': None, 'ymax_hist': None
        }

        self.fit_functions = {
            'gaussian': fitting.gauss,
            'lorentz': fitting.lorentz,
            'voigt': fitting.voigt,
        }

    def __getattr__(self, key):
        if key in self.info:
            return self.info.get(key)
        else:
            raise AttributeError('Attribute "{}" does not exist in {}'.format(key, self.__class__.__name__))

    def __repr__(self):
        state_info = '\n'.join(f'    {name}: {value}' for name, value in self.info.items())
        obj_id = hex(id(self))
        return (
            f"< {self.__class__.__name__} | {self.name} | {obj_id}\n"
            f"{state_info}"
            f"\n/>"
        )

    def do_fit(self, method, column):
        values = self.plotter.get_records()

        # only run if values are available
        if not values:
            return

        names = list(values.dtype.fields.keys())
        x_name = names[0]
        y_name = column if column is not None else names[1]
        xo, yo = values.data[x_name], values.data[y_name]
        coeffs, success = fitting.peak_fit(xo, yo, method)
        ymax, fwhm, midp = coeffs[:3]
        hist_coeffs, success = fitting.histogram_fit(xo, yo)
        ymax_hist, fwhm_hist, xmax_hist, hm_left_hist, hm_right_hist, cema = hist_coeffs
        midp_hist = (hm_left_hist + hm_right_hist) / 2.
        fwhm_hist = abs(hm_left_hist - hm_right_hist)

        self.info = {
            'ymax': yo.max(),
            'midp': midp,
            'fwhm': fwhm,
            'cema': cema,
            'midp_hist': midp_hist,
            'fwhm_hist': fwhm_hist,
            'ymax_hist': ymax_hist,
        }

        ax = self.plotter.get_axis_for(y_name)

        xc = numpy.linspace(min(xo.min(), midp - fwhm), max(xo.max(), midp + fwhm), 1000)
        yc = self.fit_functions[method](xc, coeffs)

        ax.plot(xc, yc, '--', alpha=0.25, lw=3, c='r')
        hh = 0.5 * (yo.max() - yo.min()) + yo.min()
        ax.axvline(cema, label='CEMA-his', c='c', ls='--', lw=0.5)
        ax.axvline(midp_hist, label='MIDP-his', c='b', ls='--', lw=0.5)
        ax.plot([hm_left_hist, hm_right_hist], [hh, hh], c='b', ls='--', lw=0.5)

        # refresh plot
        self.plotter.redraw()
        return self.info

    def gaussian(self, column=None):
        return self.do_fit('gaussian', column)

    def lorentz(self, column=None):
        return self.do_fit('lorentz', column)

    def voigt(self, column=None):
        return self.do_fit('voigt', column)


@implementer(IScanPlotter)
class ScanPlotter(object):

    def __init__(self, widget):
        self.plotter = plotter.Plotter()
        self.fit = Fit(self.plotter)
        self.widget = widget
        self.widget.scan_box.pack_start(self.plotter, True, True, 0)
        self.axis = self.plotter.axis.get('default')
        self.start_time = 0
        self.scan = None
        self.scan_links = []
        self.scan_callbacks = {
            'started': self.on_start,
            'new-point': self.on_new_point,
            'progress': self.on_progress,
            'done': self.on_done,
            'error': self.on_error,
            'stopped': self.on_stop,
            'new-row': self.on_new_row,
        }
        Registry.add_utility(IScanPlotter, self)

    def link_scan(self, scan):
        for link in self.scan_links:
            self.scan.disconnect(link)

        self.scan = scan
        # connect signals.
        self.scan_links = [
            self.scan.connect(sig, callback) for sig, callback in self.scan_callbacks.items()
        ]

    def on_start(self, scan, specs):
        """
        Clear Scan and setup based on contents of data dictionary.
        """

        if not specs.get('extension'):
            self.plotter.clear(specs)
            self.start_time = time.time()
            x_name = specs['data_type']['names'][0]
            x_unit = specs['units'].get(x_name, '').strip()
            self.plotter.set_labels(
                title=specs['scan_type'],
                x_label='{}{}'.format(x_name, '({})'.format(x_unit) if x_unit else ''),
            )

    def on_progress(self, scan, fraction, message):
        if fraction > 0.0:
            used_time = time.time() - self.start_time
            remaining_time = (1 - fraction) * used_time / fraction
            eta_time = remaining_time
            self.widget.scan_eta.set_text('{:0>2.0f}:{:0>2.0f} ETA'.format(*divmod(eta_time, 60)))
        self.widget.scan_pbar.set_fraction(fraction)
        self.widget.scan_progress_lbl.set_text(message)

    def on_new_point(self, scan, data):
        self.plotter.add_point(data)

    def on_new_row(self, scan, index):
        self.plotter.new_row(index)

    def on_stop(self, scan):
        self.widget.scan_progress_lbl.set_text('Scan Stopped!')

    def on_error(self, scan, reason):
        self.widget.scan_progress_lbl.set_text('Scan Error: {}'.format(reason, ))

    def on_done(self, scan, info):
        scan.save()

