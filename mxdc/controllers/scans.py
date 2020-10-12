import copy
import os
import time
import uuid
from datetime import datetime
from enum import Enum

from gi.repository import Gtk

from mxdc import Registry, Object, IBeamline, Property
from mxdc.engines.spectroscopy import XRFScan, MADScan, XASScan
from mxdc.utils import colors, datatools, misc, scitools
from mxdc.utils.gui import ColumnSpec, TreeManager, ColumnType, FormManager, Validator, FieldSpec
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs, periodictable, plotter
from . import common
from .datasets import IDatasets
from .samplestore import ISampleStore

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

    new_data = [data[0]]
    for entry in data:
        old = new_data[-1]
        _new = join(old, entry)
        new_data.remove(old)
        new_data.extend(_new)

    return new_data


class ScanController(Object):
    class StateType:
        READY, ACTIVE, PAUSED = list(range(3))

    state = Property(type=int, default=StateType.READY)
    config = Property(type=object)
    desc = 'MAD Scan'
    result_class = None
    ConfigSpec = None
    prefix = 'mad'
    Fields = ()
    disabled = ()

    def __init__(self, scanner, plotter, widget, edge_selector):
        super().__init__()
        self.widget = widget
        self.plotter = plotter
        self.scanner = scanner
        self.form = FormManager(self.widget, fields=self.Fields, prefix=self.prefix, persist=True, disabled=self.disabled)
        self.edge_selector = edge_selector
        self.sample_store = Registry.get_utility(ISampleStore)

        self.pause_dialog = None
        self.start_time = 0
        self.scan = None
        self.scan_links = []

        self.results = self.result_class(self.results_view)
        self.setup()

    def setup(self):
        self.scanner.connect('started', self.on_started)
        self.scanner.connect('new-point', self.on_new_point)
        self.scanner.connect('progress', self.on_progress)
        self.scanner.connect('paused', self.on_paused)
        self.scanner.connect('stopped', self.on_stopped)
        self.scanner.connect('error', self.on_error)
        self.scanner.connect('done', self.on_done)

        self.start_btn.connect('clicked', self.start)
        self.stop_btn.connect('clicked', self.stop)

        self.edge_btn.set_popover(self.widget.scans_ptable_pop)
        self.edge_btn.connect('toggled', self.prepare_ptable, self.edge_entry)
        self.edge_entry.connect('changed', self.hide_ptable)
        self.edge_entry.connect('changed', self.on_edge_changed)
        self.connect('notify::state', self.on_state_changed)

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
            params = self.form.get_values()
            params['uuid'] = str(uuid.uuid4())
            params['name'] = datetime.now().strftime('%y%m%d-%H%M')
            params['activity'] = '{}-scan'.format(self.prefix)
            params = datatools.update_for_sample(params, self.sample_store.get_current())
            self.props.config = params
            self.scanner.configure(**self.props.config)
            self.scanner.start()

    def stop(self, *args, **kwargs):
        self.progress_lbl.set_text("Stopping {} ...".format(self.desc))
        self.scanner.stop()

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

    def on_new_point(self, scanner, data):
        self.plotter.add_point(data)

    def on_progress(self, scanner, fraction, message):
        if fraction > 0.0:
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

    def on_started(self, scan, specs):
        """
        Clear Scan and setup based on contents of data dictionary.
        """
        self.plotter.clear(specs)
        self.start_time = time.time()

        self.props.state = self.StateType.ACTIVE
        logger.info("{} Started.".format(self.desc))
        self.update_directory(scan.config.directory)

        x_name = specs['data_type']['names'][0]
        x_unit = specs['units'].get(x_name, '').strip()
        self.plotter.set_labels(
            title=specs['scan_type'],
            x_label='{}{}'.format(x_name, ' ({})'.format(x_unit) if x_unit else ''),
        )

    def on_stopped(self, scanner, data):
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

    def on_done(self, scan, data):
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
        NAME, LABEL, ENERGY, EDGE, WAVELENGTH, FPP, FP, DIRECTORY = list(range(8))

    Types = [str, str, float, str, float, float, float, str]
    Columns = ColumnSpec(
        (Data.LABEL, 'Label', ColumnType.TEXT, '{}', True),
        (Data.ENERGY, 'Energy', ColumnType.NUMBER, '{:0.3f}', True),
        (Data.WAVELENGTH, "\u03BB", ColumnType.NUMBER, '{:0.4f}', True),
        (Data.FP, "f'", ColumnType.NUMBER, '{:0.1f}', True),
        (Data.FPP, 'f"', ColumnType.NUMBER, '{:0.1f}', True),
    )
    parent = Data.NAME
    run_info = Property(type=object)
    run_name = Property(type=str, default='')
    directory = Property(type=str, default='')

    def selection_changed(self, model, itr):
        if itr:
            self.props.directory = model[itr][self.Data.DIRECTORY.value]
            self.props.run_name = model[itr][self.Data.NAME.value]
            self.props.run_info = self.get_items(itr)

        else:
            self.props.directory = ''
            self.props.run_name = ''
            self.props.run_info = None

    def make_parent(self, row):
        parent_row = super(MADResultsManager, self).make_parent(row)
        parent_row[self.Data.ENERGY.value] = row[self.Data.EDGE.value]
        return parent_row


class XRFResultsManager(TreeManager):
    class Data(Enum):
        SELECTED, SYMBOL, NAME, PERCENT, DIRECTORY = list(range(5))

    Types = [bool, str, str, float, str]
    Columns = ColumnSpec(
        (Data.SYMBOL, 'Symbol', ColumnType.TEXT, '{}', True),
        (Data.NAME, 'Element', ColumnType.TEXT, '{}', True),
        (Data.PERCENT, 'Amount', ColumnType.NUMBER, '{:0.1f} %', True),
        (Data.SELECTED, '', ColumnType.TOGGLE, '{}', False),
    )
    flat = True
    directory = Property(type=str, default='')

    def format_cell(self, column, renderer, model, itr, spec):
        super(XRFResultsManager, self).format_cell(column, renderer, model, itr, spec)
        index = model.get_path(itr)[0]
        renderer.set_property("foreground", colors.Category.GOOG20[index % 20])

    def selection_changed(self, model, itr):
        if itr:
            self.props.directory = model[itr][self.Data.DIRECTORY.value]
        else:
            self.props.directory = ''


class XASResultsManager(TreeManager):
    class Data(Enum):
        NAME, EDGE, SCAN, TIME, X_PEAK, Y_PEAK, DIRECTORY = list(range(7))

    Types = [str, str, int, str, float, float, str]
    Columns = ColumnSpec(
        (Data.SCAN, 'Scan', ColumnType.TEXT, '{}', True),
        (Data.TIME, 'TIME', ColumnType.TEXT, '{}', True),
        (Data.X_PEAK, 'X-Peak', ColumnType.NUMBER, '{:0.3f}', True),
        (Data.Y_PEAK, 'Y-Peak', ColumnType.NUMBER, '{:0.1f}', True),
    )
    parent = Data.NAME
    directory = Property(type=str, default='')

    def make_parent(self, row):
        parent_row = super(XASResultsManager, self).make_parent(row)
        parent_row[self.Data.TIME.value] = row[self.Data.EDGE.value]
        return parent_row

    def selection_changed(self, model, itr):
        if itr:
            self.props.directory = model[itr][self.Data.DIRECTORY.value]
        else:
            self.props.directory = ''


class MADScanController(ScanController):
    Fields = (
        FieldSpec('edge','entry', '{}', Validator.Slug(10, 'Se-K')),
        FieldSpec('exposure','entry', '{:0.3g}', Validator.Float(.1, 20, 0.5)),
        FieldSpec('attenuation','entry', '{:0.3g}', Validator.Float(0, 100, 50.0)),
    )
    desc = 'MAD Scan'
    prefix = 'mad'
    result_class = MADResultsManager

    def setup(self):
        super().setup()
        self.datasets = Registry.get_utility(IDatasets)
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
            self.widget.scans_dir_fbk.set_text(self.results.props.directory)
        else:
            self.widget.mad_runs_btn.set_sensitive(False)
            self.widget.mad_selected_lbl.set_text('')

    def on_done(self, scanner, config):
        super().on_done(scanner, config)
        choices = scanner.results.get('choices')
        if choices is None:
            dialogs.warning('Error Analysing Scan', 'Analysis of MAD Scan failed')
            return

        for choice in choices:
            self.plotter.axis['default'].axvline(choice['energy'], color='#999999', linestyle='--', linewidth=1)

        self.plotter.add_axis(name="sfactors", label="Anomalous factors")
        data = scanner.results.get('esf')
        if data is not None:
            self.plotter.add_line(data['energy'], data['fpp'], '-', name='fpp', axis='sfactors', lw=0.5)
            self.plotter.add_line(data['energy'], data['fp'], '-', name="fp", axis='sfactors',redraw=True, lw=0.5)
            self.plotter.set_labels(x_label='Energy (keV)', y1_label='Fluorescence')

        for choice in choices:
            self.results.add_item({
                'edge': scanner.config['edge'],
                'name': scanner.config['name'],
                'label': choice['label'],
                'fpp': choice['fpp'],
                'fp': choice['fp'],
                'energy': choice['energy'],
                'wavelength': choice['wavelength'],
                'directory': scanner.config['directory'],
            })

    def load_data(self, meta, data, analysis):
        choices = analysis.get('choices')
        if choices is None:
            return

        new_axis = self.plotter.add_axis(name="sfactors", label="Anomalous scattering factors (ƒ', ƒ"")")
        for choice in choices:
            self.plotter.axis["sfactors"].axvline(choice['energy'], color='#999999', linestyle='--', linewidth=1)

        if data:
            self.plotter.add_line(data['energy'], data['normfluor'], '-', axis="sfactors", name="normfluor")

        esf = analysis.get('esf')
        if esf is not None:
            self.plotter.add_line(esf['energy'], esf['fpp'], '-', name='fpp', axis=new_axis)
            self.plotter.add_line(esf['energy'], esf['fp'], '-', name="fp", axis=new_axis, redraw=True)
            self.plotter.set_labels(x_label='Energy (keV)', y1_label='Fluorescence')


class XRFScanController(ScanController):
    Fields = (
        FieldSpec('edge','entry', '{}', Validator.Slug(10, 'Se-K')),
        FieldSpec('energy','entry', '{:0.3f}', Validator.Float(4, 25., 12.658)),
        FieldSpec('exposure','entry', '{:0.3g}', Validator.Float(.1, 20, 0.5)),
        FieldSpec('attenuation','entry', '{:0.3g}', Validator.Float(0, 100, 50.0)),
    )
    desc = 'XRF Scan'
    prefix = 'xrf'
    result_class = XRFResultsManager

    def setup(self):
        super().setup()
        # fix adjustments
        self.annotations = {}
        self.results.model.connect('row-changed', self.on_annotation)
        self.results.connect('notify::directory', self.on_scan_selected)

    def on_started(self, scanner, data):
        super().on_started(scanner, data)
        self.results.clear()

    def on_scan_selected(self, *args, **kwargs):
        if self.results.props.directory:
            self.widget.scans_dir_fbk.set_text(self.results.props.directory)

    def on_done(self, scanner, data):
        super().on_done(scanner, data)
        self.annotations = {}
        data = scanner.data
        analysis = scanner.results
        energy = scanner.config['energy']
        assignments = analysis['assignments']

        self.plotter.set_labels(
            title='X-Ray Fluorescence from Excitation at {:0.3f} keV'.format(energy),
            x_label='Energy (keV)', y1_label='Fluorescence'
        )
        self.plotter.add_line(analysis['energy'], analysis['fit'], ':', name='fit')
        self.plotter.axis['default'].axhline(0.0, color='gray', linewidth=0.5)
        self.plotter.add_line(data['energy'], data['normfluor'], '-', name='expt', lw=1, alpha=0.2)
        self.plotter.add_line(
            analysis['energy'], analysis['counts'], '-', name='smooth'
        )

        ax = self.plotter.axis['default']
        ax.axis('tight')
        ax.set_xlim(-0.25, energy + 0.5)

        # get list of elements sorted in descending order of prevalence
        element_list = [(v[0], k) for k, v in list(assignments.items())]
        element_list.sort(reverse=True)

        for index, (amount, symbol) in enumerate(element_list):
            element = scitools.PERIODIC_TABLE[symbol]
            if amount < 0.005 * element_list[0][0] or index > 20: continue
            visible = (amount >= 0.1 * element_list[0][0])
            self.results.add_item({
                'name': element['name'],
                'selected': visible,
                'symbol': symbol,
                'percent': amount,
                'directory': scanner.config['directory'],
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
                    position, -0.5, "{}-{}".format(symbol, name), rotation=90, fontsize=10,
                    horizontalalignment='center', verticalalignment='top', color=color
                )
                self.annotations[symbol].append(annotation)
            arts = ax.plot(*line_points, **{'linewidth': 1.0, 'color': color})
            self.annotations[symbol].extend(arts)
            for annotation in self.annotations[symbol]:
                annotation.set_visible(visible)

        ax.axvline(energy, c='#cccccc', ls='--', lw=0.5, label='Excitation Energy')
        self.plotter.axis['default'].legend()

        ymin, ymax = misc.get_min_max(analysis['counts'], ldev=1, rdev=2)
        ax.axis(ymin=ymin, ymax=ymax)
        self.plotter.redraw()

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
    Fields = (
        FieldSpec('edge','entry', '{}', Validator.Slug(10, 'Se-K')),
        FieldSpec('kmax','spin', '{}', Validator.Int(1, 16, 4)),
        FieldSpec('exposure', 'entry', '{:0.3g}', Validator.Float(.1, 20, 0.5)),
        FieldSpec('attenuation', 'entry', '{:0.3g}', Validator.Float(0, 100, 50.0)),
        FieldSpec('scans', 'spin', '{}', Validator.Int(1, 100, 10))
    )

    desc = 'XAS Scan'
    prefix = 'xas'
    result_class = XASResultsManager

    def setup(self):
        super(XASScanController, self).setup()
        # fix adjustments
        self.kmax_spin.set_adjustment(
            Gtk.Adjustment(value=8, lower=1, upper=16, step_increment=1, page_increment=1, page_size=0)
        )
        self.scans_spin.set_adjustment(
            Gtk.Adjustment(value=4, lower=1, upper=128, step_increment=1, page_increment=10, page_size=0)
        )
        self.scanner.connect('new-row', self.on_new_scan)
        self.results.connect('notify::directory', self.on_scan_selected)

    def on_new_scan(self, scanner, scan):
        self.axis = scan
        self.results.add_item(scanner.results['scans'][-1])

    def on_scan_selected(self, *args, **kwargs):
        if self.results.props.directory:
            self.widget.scans_dir_fbk.set_text(self.results.props.directory)


class ScanManager(Object):
    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.sample_store = Registry.get_utility(ISampleStore)
        self.plotter = plotter.Plotter(xformat='%g', dpi=90)
        min_energy, max_energy = self.beamline.config['energy_range']
        self.edge_selector = periodictable.EdgeSelector(
            min_energy=min_energy, max_energy=max_energy, xrf_offset=self.beamline.config['xrf_energy_offset']
        )
        self.xrf_scanner = XRFScanController(XRFScan(), self.plotter, widget, self.edge_selector)
        self.xas_scanner = XASScanController(XASScan(), self.plotter, widget, self.edge_selector)
        self.mad_scanner = MADScanController(MADScan(), self.plotter, widget, self.edge_selector)

        # connect scanners
        self.status_monitor = common.StatusMonitor(
            self.widget, devices=(self.mad_scanner.scanner, self.xas_scanner.scanner, self.xrf_scanner.scanner)
        )
        self.setup()

    def setup(self):
        self.widget.scans_ptable_box.add(self.edge_selector)
        self.widget.scans_plot_frame.add(self.plotter)
        self.widget.scans_dir_btn.connect('clicked', self.open_terminal)
        self.sample_store.connect('updated', self.on_sample_updated)
        labels = {
            'energy': (self.beamline.energy, self.widget.scans_energy_fbk, {'format': '{:0.3f} keV'}),
            'attenuation': (self.beamline.attenuator, self.widget.scans_attenuation_fbk, {'format': '{:0.0f} %'}),
            'aperture': (self.beamline.aperture, self.widget.scans_aperture_fbk, {'format': '{:0.0f} µm'}),
            'deadtime': (
                self.beamline.mca, self.widget.scans_deadtime_fbk,
                {'format': '{:0.0f} %', 'signal': 'deadtime', 'warning': 20.0, 'error': 40.0}
            ),
        }
        self.monitors = {
            name: common.DeviceMonitor(dev, lbl, **kw)
            for name, (dev, lbl, kw) in list(labels.items())
        }

        if hasattr(self.beamline, 'multi_mca'):
            self.beamline.multi_mca.connect('active', self.enable_xas)

    def enable_xas(self, dev, state):
        self.widget.xas_control_box.set_sensitive(state)

    def open_terminal(self, button):
        directory = self.widget.scans_dir_fbk.get_text()
        misc.open_terminal(directory)

    def on_sample_updated(self, obj):
        sample = self.sample_store.get_current()
        sample_text = '{name}|{port}'.format(
            name=sample.get('name', '...'),
            port=sample.get('port', '...')
        ).replace('|...', '')
        self.widget.scans_sample_fbk.set_text(sample_text)
