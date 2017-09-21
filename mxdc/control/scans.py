import os
import time
import copy
from datetime import datetime
import uuid

import common
from datasets import IDatasets
from enum import Enum
from gi.repository import Gtk, GObject
from mxdc.beamline.mx import IBeamline
from mxdc.engine.spectroscopy import XRFScanner, MADScanner, XASScanner
from mxdc.utils import colors, runlists, misc, science, converter
from mxdc.utils.gui import ColumnSpec, TreeManager, ColumnType
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs, periodictable, plotter
from samplestore import ISampleStore
from twisted.python.components import globalRegistry

logger = get_module_logger(__name__)


def summarize_lines(data):
    name_dict = {
        'L1M2,3,L2M4': 'L1,2M',
        'L1M3,L2M4': 'L1,2M',
        'L1M,L2M4': 'L1,2M',
    }

    def join(a, b):
        if a == b:
            return [a]
        if abs(b[1] - a[1]) < 0.200:
            if a[0][:-1] == b[0][:-1]:
                # nm = '%s,%s' % (a[0], b[0][-1])
                nm = b[0][:-1]
            else:
                nm = os.path.commonprefix([a[0], b[0]])
            nm = name_dict.get(nm, nm)
            ht = (a[2] + b[2])
            pos = (a[1] * a[2] + b[1] * b[2]) / ht
            return [(nm, round(pos, 4), round(ht, 2))]
        else:
            return [a, b]

    # data.sort(key=lambda x: x[1])
    data.sort()
    # print data
    new_data = [data[0]]
    for entry in data:
        old = new_data[-1]
        _new = join(old, entry)
        new_data.remove(old)
        new_data.extend(_new)
    # print new_data
    return new_data


class ScanController(GObject.GObject):

    class StateType:
        READY, ACTIVE, PAUSED = range(3)

    state = GObject.Property(type=int, default=StateType.READY)
    config = GObject.Property(type=object)
    desc = 'MAD Scan'
    result_class = None
    ConfigSpec = None
    prefix = 'mad'

    def __init__(self, scanner, plotter, widget, edge_selector):
        super(ScanController, self).__init__()
        self.widget = widget
        self.plotter = plotter
        self.scanner = scanner
        self.edge_selector = edge_selector
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        self.start_time = 0
        self.axis = 0
        self.pause_dialog = None
        self.results = self.result_class(self.results_view)
        self.setup()

    def setup(self):
        self.connect('notify::state', self.on_state_changed)
        self.scanner.connect('new-point', self.on_new_point)
        self.scanner.connect('paused', self.on_paused)
        self.scanner.connect('stopped', self.on_stopped)
        self.scanner.connect('progress', self.on_progress)
        self.scanner.connect('started', self.on_started)
        self.scanner.connect('error', self.on_error)
        self.scanner.connect('done', self.on_done)
        self.start_btn.connect('clicked', self.start)
        self.stop_btn.connect('clicked', self.stop)

        self.edge_btn.set_popover(self.widget.scans_ptable_pop)
        self.edge_btn.connect('toggled', self.prepare_ptable, self.edge_entry)
        self.edge_entry.connect('changed', self.hide_ptable)
        self.edge_entry.connect('changed', self.on_edge_changed)

    def update_directory(self, directory):
        home = misc.get_project_home()
        dir_text = directory.replace(home, '~')
        self.widget.scans_dir_fbk.set_text(dir_text)
        self.widget.scans_dir_fbk.set_tooltip_text(directory)

    def prepare_ptable(self, btn, entry):
        if btn.get_active():
            self.edge_selector.set_entry(entry)

    def hide_ptable(self, *args, **kwargs):
        self.widget.scans_ptable_pop.popdown()

    def start(self, *args, **kwargs):
        if self.props.state == self.StateType.ACTIVE:
            self.progress_lbl.set_text("Pausing {} ...".format(self.desc))
            self.scanner.pause()
        elif self.props.state == self.StateType.PAUSED:
            self.progress_lbl.set_text("Resuming {} ...".format(self.desc))
            self.scanner.resume()
        elif self.props.state == self.StateType.READY:
            self.progress_lbl.set_text("Starting {} ...".format(self.desc))
            params = self.get_parameters()
            params['uuid'] = str(uuid.uuid4())
            params['name'] = datetime.now().strftime('%y%m%d-%H%M')
            params['activity'] = '{}-scan'.format(self.prefix)
            params = runlists.update_for_sample(params, self.sample_store.get_current())
            self.props.config = params
            self.scanner.configure(self.props.config)
            self.scanner.start()

    def stop(self, *args, **kwargs):
        self.progress_lbl.set_text("Stopping {} ...".format(self.desc))
        self.scanner.stop()

    def configure(self, info, disable=()):
        if not self.ConfigSpec: return
        for name, details in self.ConfigSpec.items():
            field_type, fmt, conv, default = details
            field_name = '{}_{}'.format(name, field_type)
            value = info.get(name, default)
            field = getattr(self, field_name, None)
            if not field: continue
            if field_type == 'entry':
                field.set_text(fmt.format(value))
            elif field_type == 'check':
                field.set_active(value)
            elif field_type == 'spin':
                field.set_value(value)
            elif field_type == 'cbox':
                field.set_active_id(str(value))
            elif field_type == 'pbox':
                if value:
                    name, point = value
                    field.set_active_id(name)
                else:
                    field.set_active_id(None)
            if name in disable:
                field.set_sensitive(False)
            try:
                conv(value)
                field.get_style_context().remove_class('error')
            except (TypeError, ValueError):
                field.get_style_context().add_class('error')

    def get_parameters(self):
        info = {}
        if not self.ConfigSpec: return info
        for name, details in self.ConfigSpec.items():
            field_type, fmt, conv, default = details
            field_name = '{}_{}'.format(name, field_type)
            field = getattr(self, field_name, None)
            if not field: continue
            raw_value = default
            if field_type == 'entry':
                raw_value = field.get_text()
            elif field_type == 'switch':
                raw_value = field.get_active()
            elif field_type == 'cbox':
                raw_value = field.get_active_id()
            elif field_type == 'spin':
                raw_value = field.get_value()
            elif field_type == 'pbox':
                point_name = field.get_active_id()
                raw_value = self.get_point(point_name)
                if not raw_value: continue
            try:
                value = conv(raw_value)
            except (TypeError, ValueError):
                value = default
            info[name] = value
        return info

    def on_edge_changed(self, entry):
        edge = entry.get_text()
        if edge:
            absorption, emission = self.edge_selector.get_edge_specs(edge)
            self.absorption_entry.set_text('{:0.4f}'.format(absorption))
            self.emission_entry.set_text('{:0.4f}'.format(emission))

    def on_state_changed(self, *args, **kwargs):
        if self.props.state == self.StateType.ACTIVE:
            self.start_icon.set_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON)
            self.stop_btn.set_sensitive(True)
            self.start_btn.set_sensitive(True)
            self.config_box.set_sensitive(False)

        elif self.props.state == self.StateType.PAUSED:
            self.progress_lbl.set_text("{} paused!".format(self.desc))
            self.start_icon.set_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
            self.stop_btn.set_sensitive(True)
            self.start_btn.set_sensitive(True)
            self.config_box.set_sensitive(False)
        else:
            self.start_icon.set_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
            self.config_box.set_sensitive(True)
            self.start_btn.set_sensitive(True)
            self.stop_btn.set_sensitive(False)

    def on_new_point(self, scanner, point):
        self.plotter.add_point(point[0], point[1], lin=self.axis)

    def on_progress(self, scanner, fraction, message):
        used_time = time.time() - self.start_time
        remaining_time = (1 - fraction) * used_time / fraction
        eta_time = remaining_time
        self.eta.set_text('{:0>2.0f}:{:0>2.0f} ETA'.format(*divmod(eta_time, 60)))
        self.pbar.set_fraction(fraction)
        self.progress_lbl.set_text(message)

    def on_paused(self, scanner, paused, reason):
        if paused:
            self.props.state = self.StateType.PAUSED
            if reason:
                # Build the dialog message
                self.pause_dialog = dialogs.make_dialog(
                    Gtk.MessageType.WARNING, '{} Paused'.format(self.desc), reason,
                    buttons=(('OK', Gtk.ResponseType.OK),)
                )
                self.pause_dialog.run()
                self.pause_dialog.destroy()
                self.pause_dialog = None
        else:
            self.props.state = self.StateType.ACTIVE
            if self.pause_dialog:
                self.pause_dialog.destroy()
                self.pause_dialog = None

    def on_started(self, scanner):
        self.axis = 0
        self.start_time = time.time()
        self.plotter.clear()
        self.props.state = self.StateType.ACTIVE
        logger.info("{} Started.".format(self.desc))
        self.update_directory(scanner.config['directory'])

    def on_stopped(self, scanner):
        self.props.state = self.StateType.READY
        self.progress_lbl.set_text("{} Stopped.".format(self.desc))
        self.eta.set_text('--:--')

    def on_error(self, scanner, message):
        error_dialog = dialogs.make_dialog(
            Gtk.MessageType.WARNING, '{} Error!'.format(self.desc), message,
            buttons=(('OK', Gtk.ResponseType.OK),)
        )
        error_dialog.run()
        error_dialog.destroy()

    def on_done(self, scanner):
        self.props.state = self.StateType.READY
        self.progress_lbl.set_text("{} Completed.".format(self.desc))
        self.eta.set_text('--:--')
        self.pbar.set_fraction(1.0)

    def __getattr__(self, item):
        try:
            return getattr(self.widget, '{}_{}'.format(self.prefix, item))
        except AttributeError:
            raise AttributeError('{} does not have attribute: {}'.format(self, item))


class MADResultsManager(TreeManager):
    class Data(Enum):
        NAME, LABEL, ENERGY, EDGE, WAVELENGTH, FPP, FP = range(7)

    Types = [str, str, float, str, float, float, float]
    Columns = ColumnSpec(
        (Data.LABEL, 'Label', ColumnType.TEXT, '{}'),
        (Data.ENERGY, 'Energy', ColumnType.NUMBER, '{:0.3f}'),
        (Data.WAVELENGTH, u"\u03BB", ColumnType.NUMBER, '{:0.4f}'),
        (Data.FP, "f'", ColumnType.NUMBER, '{:0.1f}'),
        (Data.FPP, 'f"', ColumnType.NUMBER, '{:0.1f}'),
    )
    parent = Data.NAME
    run_info = GObject.Property(type=object)
    run_name = GObject.Property(type=str, default='')

    def selection_changed(self, selection):
        model, itr = selection.get_selected()
        if not itr:
            self.props.run_name = ''
            self.props.run_info = None
        else:
            self.props.run_name = model[itr][self.Data.NAME.value]
            self.props.run_info = self.get_items(itr)

    def make_parent(self, row):
        parent_row = super(MADResultsManager, self).make_parent(row)
        parent_row[self.Data.ENERGY.value] = row[self.Data.EDGE.value]
        return parent_row


class XRFResultsManager(TreeManager):
    class Data(Enum):
        SELECTED, SYMBOL, NAME, PERCENT = range(4)

    Types = [bool, str, str, float]
    Columns = ColumnSpec(
        (Data.SYMBOL, '', ColumnType.TEXT, '{}'),
        (Data.NAME, 'Element', ColumnType.TEXT, '{}'),
        (Data.PERCENT, 'Amount', ColumnType.NUMBER, '{:0.1f} %'),
        (Data.SELECTED, '', ColumnType.TOGGLE, '{}'),
    )
    flat = True

    def format_cell(self, column, renderer, model, itr, spec):
        super(XRFResultsManager, self).format_cell(column, renderer, model, itr, spec)
        index = model.get_path(itr)[0]
        renderer.set_property("foreground", colors.Category.GOOG20[index % 20])


class XASResultsManager(TreeManager):
    class Data(Enum):
        NAME, EDGE, SCAN, TIME, X_PEAK, Y_PEAK = range(6)

    Types = [str, str, int, str, float, float]
    Columns = ColumnSpec(
        (Data.SCAN, 'Scan', ColumnType.TEXT, '{}'),
        (Data.TIME, 'TIME', ColumnType.TEXT, '{}'),
        (Data.X_PEAK, 'X-Peak', ColumnType.NUMBER, '{:0.3f}'),
        (Data.Y_PEAK, 'Y-Peak', ColumnType.NUMBER, '{:0.1f}'),
    )
    parent = Data.NAME

    def make_parent(self, row):
        parent_row = super(XASResultsManager, self).make_parent(row)
        parent_row[self.Data.TIME.value] = row[self.Data.EDGE.value]
        return parent_row


class MADScanController(ScanController):
    ConfigSpec = {
        'edge': ['entry', '{}', str, 'Se-K'],
        'exposure': ['entry', '{:0.3g}', float, 1.0],
        'attenuation': ['entry', '{:0.3g}', float, 50.0],
    }
    desc = 'MAD Scan'
    prefix = 'mad'
    result_class = MADResultsManager

    def setup(self):
        super(MADScanController, self).setup()
        self.datasets = globalRegistry.lookup([], IDatasets)
        self.widget.mad_runs_btn.connect('clicked', self.add_mad_runs)
        self.results.connect('notify::run-info', self.on_run_info)

    def add_mad_runs(self, btn, *args, **kwargs):
        if self.results.props.run_info:
            runs = copy.deepcopy(self.results.props.run_info)
            for run in runs:
                run['name'] = '{}-{}'.format(run['name'], run['label'])
            self.datasets.add_runs(runs)
            btn.set_sensitive(False)

            data_page = self.widget.main_stack.get_child_by_name('Data')
            self.widget.main_stack.child_set(data_page, needs_attention=True)
            self.widget.notifier.notify("Datasets added. Switch to Data page to proceed.")

    def on_run_info(self, *args, **kwargs):
        if self.results.props.run_info:
            self.widget.mad_runs_btn.set_sensitive(True)
            self.widget.mad_selected_lbl.set_text(self.results.props.run_name)
        else:
            self.widget.mad_runs_btn.set_sensitive(False)
            self.widget.mad_selected_lbl.set_text('')

    def on_done(self, scanner):
        super(MADScanController, self).on_done(scanner)
        choices = scanner.results['analysis'].get('choices')
        if choices is None:
            dialogs.warning('Error Analysing Scan', 'Analysis of MAD Scan failed')
            return

        new_axis = self.plotter.add_axis(label="Anomalous scattering factors (f', f'')")
        for choice in choices:
            self.plotter.axis[0].axvline(choice['energy'], color='#999999', linestyle='--', linewidth=1)

        data = scanner.results['analysis'].get('esf')
        if data:
            self.plotter.add_line(
                data['energy'], data['fpp'], '-', color=colors.Category.GOOG20[1], label='f"',  ax=new_axis
            )
            self.plotter.add_line(
                data['energy'], data['fp'], '-', color=colors.Category.CAT20[5], label="f'", ax=new_axis, redraw=True
            )
            self.plotter.set_labels(
                title='{} Edge MAD Scan'.format(scanner.config['edge']),
                x_label='Energy (keV)', y1_label='Fluorescence'
            )

        for choice in choices:
            parent, child = self.results.add_item({
                'edge': scanner.config['edge'],
                'name': scanner.config['name'],
                'label': choice['label'],
                'fpp': choice['fpp'],
                'fp': choice['fp'],
                'energy': choice['energy'],
                'wavelength': choice['wavelength'],
            })
            if parent:
                self.results_view.expand_row(parent, False)
            self.results_view.scroll_to_cell(child, None, True, 0.5, 0.5)


class XRFScanController(ScanController):
    ConfigSpec = {
        'energy': ['entry', '{:0.3f}', float, 12.658],
        'exposure': ['entry', '{:0.3g}', float, 0.5],
        'attenuation': ['entry', '{:0.3g}', float, 50.0],
    }
    desc = 'XRF Scan'
    prefix = 'xrf'
    result_class = XRFResultsManager

    def setup(self):
        super(XRFScanController, self).setup()
        # fix adjustments
        self.annotations = {}
        self.results.model.connect('row-changed', self.on_annotation)

    def on_started(self, scanner):
        super(XRFScanController, self).on_started(scanner)
        self.results.clear()

    def on_done(self, scanner):
        super(XRFScanController, self).on_done(scanner)
        self.annotations = {}

        data = scanner.results['data']
        analysis = scanner.results['analysis']
        ys = analysis['counts']
        energy = scanner.config['energy']
        assignments = analysis['assignments']

        self.plotter.set_labels(
            title='X-Ray Fluorescence from Excitation at {:0.3f} keV'.format(energy),
            x_label='Energy (keV)', y1_label='Fluorescence'
        )
        self.plotter.add_line(analysis['energy'], analysis['fit'], ':', color=colors.Category.GOOG20[4], label='Fit')
        self.plotter.axis[0].axhline(0.0, color='gray', linewidth=0.5)
        self.plotter.add_line(
            data['energy'], data['counts'], '-', color=colors.Category.CAT20C[16],
            label='Experimental', lw=1, alpha=0.2
        )
        self.plotter.add_line(
            analysis['energy'], analysis['counts'], '-', color=colors.Category.GOOG20[0], label='Smoothed'
        )

        ax = self.plotter.axis[0]
        ax.axis('tight')
        ax.set_xlim(-0.25, energy + 1.5)

        # get list of elements sorted in descending order of prevalence
        element_list = [(v[0], k) for k, v in assignments.items()]
        element_list.sort(reverse=True)

        for index, (amount, symbol) in enumerate(element_list):
            element = science.PERIODIC_TABLE[symbol]
            if amount < 0.005 * element_list[0][0] or index > 20: continue
            visible = (amount >= 0.1 * element_list[0][0])
            self.results.add_item({
                'name': element['name'],
                'selected': visible,
                'symbol': symbol,
                'percent': amount
            })
            color = colors.Category.GOOG20[index % 20]
            element_info = assignments.get(symbol)
            line_list = summarize_lines(element_info[1])
            line_points = []
            self.annotations[symbol] = []
            for name, position, height in line_list:
                if position > energy: continue
                line_points.extend(([position, position], [0.0, height * 0.95]))
                annotation = ax.text(
                    position, -0.5, "{}-{}".format(symbol, name), rotation=90, fontsize=8,
                    horizontalalignment='center', verticalalignment='top', color=color
                )
                self.annotations[symbol].append(annotation)
            arts = ax.plot(*line_points, **{'linewidth': 1.0, 'color': color})
            self.annotations[symbol].extend(arts)
            for annotation in self.annotations[symbol]:
                annotation.set_visible(visible)

        ax.axvline(energy, c='#cccccc', ls='--', lw=0.5, label='Excitation Energy')
        self.plotter.axis[0].legend()

        ymin, ymax = misc.get_min_max(ys, ldev=1, rdev=1)
        ax.axis(ymin=ymin, ymax=ymax)
        self.plotter.redraw()

        # Upload scan to lims
        # lims_tools.upload_scan(self.beamline, [scanner.results])

    def on_edge_changed(self, entry):
        super(XRFScanController, self).on_edge_changed(entry)
        energy = self.edge_selector.get_excitation_for(entry.get_text())
        self.energy_entry.set_text('{:0.3f}'.format(energy))

    def on_annotation(self, model, path, itr):
        itr = model.get_iter(path)
        element = model[itr][self.results.Data.SYMBOL.value]
        state = model[itr][self.results.Data.SELECTED.value]
        for annotation in self.annotations[element]:
            annotation.set_visible(state)

        self.plotter.redraw()


class XASScanController(ScanController):
    ConfigSpec = {
        'edge': ['entry', '{}', str, 'Se-K'],
        'exposure': ['entry', '{:0.3g}', float, 1.0],
        'attenuation': ['entry', '{:0.3g}', float, 50.0],
        'kmax': ['spin', '{}', int, 10],
        'scans': ['spin', '{}', int, 5],
    }
    desc = 'XAS Scan'
    prefix = 'xas'
    result_class = XASResultsManager

    def setup(self):
        super(XASScanController, self).setup()
        # fix adjustments
        self.kmax_spin.set_adjustment(Gtk.Adjustment(8, 1, 16, 1, 1, 0))
        self.scans_spin.set_adjustment(Gtk.Adjustment(4, 1, 128, 1, 10, 0))
        self.scanner.connect('new-scan', self.on_new_scan)

    def on_new_scan(self, scanner, scan):
        self.axis = scan
        parent, child = self.results.add_item(scanner.results['scans'][-1])
        if parent:
            self.results_view.expand_row(parent, False)
        self.results_view.scroll_to_cell(child, None, True, 0.5, 0.5)


class ScanManager(GObject.GObject):
    def __init__(self, widget):
        super(ScanManager, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        self.plotter = plotter.Plotter(xformat='%g')
        min_energy, max_energy = self.beamline.config['energy_range']
        self.edge_selector = periodictable.EdgeSelector(
            min_energy=min_energy, max_energy=max_energy, xrf_offset=self.beamline.config['xrf_energy_offset']
        )
        self.xrf_scanner = XRFScanController(XRFScanner(), self.plotter, widget, self.edge_selector)
        self.xas_scanner = XASScanController(XASScanner(), self.plotter, widget, self.edge_selector)
        self.mad_scanner = MADScanController(MADScanner(), self.plotter, widget, self.edge_selector)

        # connect scanners
        self.status_monitor = common.StatusMonitor(
            self.widget.status_lbl, self.widget.spinner,
            devices=(self.mad_scanner.scanner, self.xas_scanner.scanner, self.xrf_scanner.scanner)
        )
        self.setup()

    def setup(self):
        self.widget.scans_ptable_box.add(self.edge_selector)
        self.widget.scans_plot_frame.add(self.plotter)
        self.sample_store.connect('updated', self.on_sample_updated)
        labels = {
            'energy': (self.beamline.energy, self.widget.scans_energy_fbk, {'format': '{:0.3f} keV'}),
            'attenuation': (self.beamline.attenuator, self.widget.scans_attenuation_fbk, {'format': '{:0.0f} %'}),
            'aperture': (self.beamline.aperture, self.widget.scans_aperture_fbk, {'format': '{:0.0f} \xc2\xb5m'}),
            'deadtime': (
                self.beamline.mca, self.widget.scans_deadtime_fbk,
                {'format': '{:0.0f} %', 'signal': 'deadtime', 'warning': 20.0, 'error': 40.0}
            ),
        }
        self.monitors = {
            name: common.DeviceMonitor(dev, lbl, **kw)
            for name, (dev, lbl, kw) in labels.items()
        }

    def on_sample_updated(self, obj):
        sample = self.sample_store.get_current()
        sample_text = '{name}|{group}|{container}|{port}'.format(
            name=sample.get('name', '...'), group=sample.get('group', '...'), container=sample.get('container', '...'),
            port=sample.get('port', '...')
        ).replace('|...', '')
        self.widget.scans_sample_fbk.set_text(sample_text)
