import copy
import os
import time
from collections import OrderedDict
from datetime import datetime

from gi.repository import Gtk, GObject
from twisted.python.components import globalRegistry

import common
from mxdc.beamline.mx import IBeamline
from mxdc.engine.spectroscopy import XRFScanner, MADScanner, XASScanner
from mxdc.utils import colors, runlists, config, misc, science, converter
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs, periodictable, plotter
from samplestore import ISampleStore

_logger = get_module_logger(__name__)


class MAD:
    class Data:
        NAME, LABEL, ENERGY, WAVELENGTH, FPP, FP, PARENT, DIRECTORY = range(8)

    Types = [str, str, float, float, float, float, bool, str]
    Keys = [
        ('name', ''),
        ('label', ''),
        ('energy', 0.0),
        ('wavelength', 0.0),
        ('fpp', 0.0),
        ('fp', 0.0),
        ('parent', False),
        ('directory', '')
    ]
    Columns = OrderedDict([
        (Data.LABEL, 'Label'),
        (Data.ENERGY, 'Energy'),
        (Data.WAVELENGTH, u"\u03BB"),
        (Data.FP, "f'"),
        (Data.FPP, 'f"'),
    ])
    Formats = {
        Data.LABEL: '{}',
        Data.ENERGY: '{:0.4f}',
        Data.WAVELENGTH: '{:0.4f}',
        Data.FP: '{:0.2f}',
        Data.FPP: '{:0.2f}'
    }


class XRF:
    class Data:
        SELECTED, SYMBOL, NAME, PERCENT = range(4)

    Types = [bool, str, str, float]
    Keys = [
        ('selected', False),
        ('symbol', ''),
        ('name', ''),
        ('percent', 0.0)
    ]
    Columns = OrderedDict([
        (Data.SELECTED, ''),
        (Data.NAME, 'Element'),
        (Data.SYMBOL, ''),
        (Data.PERCENT, 'Relative Amount'),
    ])
    Formats = {
        Data.NAME: '{}',
        Data.SYMBOL: '{}',
        Data.PERCENT: '{:0.1f} %',
    }


class XAS:
    pass


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
    specs = None
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
        self.template_dir = config.get_activity_template('{}-scan'.format(self.prefix))
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
            params['name'] = datetime.now().strftime('%Y%m%d-%H%M')
            params['activity'] = '{}-scan'.format(self.prefix)
            params = runlists.update_for_sample(params, self.sample_store.get_current())
            self.props.config = params
            self.scanner.configure(self.props.config)
            self.scanner.start()

    def stop(self, *args, **kwargs):
        self.progress_lbl.set_text("Stopping {} ...".format(self.desc))
        self.scanner.stop()

    def configure(self, info, disable=()):
        if not self.specs: return
        for name, details in self.specs.items():
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
        if not self.specs: return info
        for name, details in self.specs.items():
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
        _logger.info("{} Started.".format(self.desc))

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


class MADScanController(ScanController):
    specs = {
        'edge': ['entry', '{}', str, 'Se-K'],
        'exposure': ['entry', '{:0.3g}', float, 1.0],
        'attenuation': ['entry', '{:0.3g}', float, 50.0],
    }
    desc = 'MAD Scan'
    prefix = 'mad'


class XRFScanController(ScanController):
    specs = {
        'energy': ['entry', '{:0.3f}', float, 12.658],
        'exposure': ['entry', '{:0.3g}', float, 0.5],
        'attenuation': ['entry', '{:0.3g}', float, 50.0],
    }
    desc = 'XRF Scan'
    prefix = 'xrf'

    def on_edge_changed(self, entry):
        super(XRFScanController, self).on_edge_changed(entry)
        energy = self.edge_selector.get_excitation_for(entry.get_text())
        self.energy_entry.set_text('{:0.3f}'.format(energy))


class XASScanController(ScanController):
    specs = {
        'edge': ['entry', '{}', str, 'Se-K'],
        'exposure': ['entry', '{:0.3g}', float, 1.0],
        'attenuation': ['entry', '{:0.3g}', float, 50.0],
        'kmax': ['spin', '{}', int, 10],
        'scans': ['spin', '{}', int, 5],
    }
    desc = 'XAS Scan'
    prefix = 'xas'

    def setup(self):
        super(XASScanController, self).setup()
        # fix adjustments
        self.kmax_spin.set_adjustment(Gtk.Adjustment(12, 1, 18, 1, 1, 0))
        self.scans_spin.set_adjustment(Gtk.Adjustment(1, 1, 128, 1, 10, 0))
        self.scanner.connect('new-scan', self.on_new_scan)

    def on_new_scan(self, scanner, scan):
        self.axis = scan

class DataStore(Gtk.TreeStore):
    def __init__(self, specs, tree=False):
        self.specs = specs
        self.use_tree = tree
        super(DataStore, self).__init__(*self.specs.Types)

    def find_parent(self, name):
        parent = self.get_iter_first()
        while parent:
            if self[parent][self.specs.Data.NAME] == name:
                break
            parent = self.iter_next(parent)
        return parent

    def add_item(self, item, parent=None):
        row = [
            item.get(key, default) for key, default in self.specs.Keys
        ]
        if self.use_tree:
            if not parent:
                parent = self.find_parent(item['name'])
            if not parent:
                parent_row = copy.deepcopy(row)
                parent_row[self.specs.Data.PARENT] = True
                parent = self.append(None, row=parent_row)
        child = self.append(parent, row=row)
        if not parent:
            return None, self.get_path(child)
        else:
            return self.get_path(parent), self.get_path(child)

    def add_items(self, items):
        """Add a list of items to the tree store with the same parent. The tree will be cleared first"""
        self.clear()
        for item in items:
            self.add_item(item)


class ScanManager(GObject.GObject):
    run_info = GObject.Property(type=object)

    def __init__(self, datasets, widget):
        super(ScanManager, self).__init__()
        self.widget = widget
        self.datasets = datasets
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        min_energy, max_energy = self.beamline.config['energy_range']
        self.edge_selector = periodictable.EdgeSelector(min_energy=min_energy, max_energy=max_energy)
        self.setup()

        # XRF Scans
        self.xrf_scanner = XRFScanController(XRFScanner(), self.plotter, widget, self.edge_selector)
        self.xrf_scanner.scanner.connect('started', self.on_xrf_started)
        self.xrf_scanner.scanner.connect('done', self.on_xrf_done)
        self.xrf_results = DataStore(XRF, tree=False)
        self.widget.xrf_results_view.set_model(self.xrf_results)
        self.xrf_annotations = {}

        # XAS Scans
        self.xas_scanner = XASScanController(XASScanner(), self.plotter, widget, self.edge_selector)

        # MAD Scans
        self.mad_scanner = MADScanController(MADScanner(), self.plotter, widget, self.edge_selector)
        self.mad_scanner.scanner.connect('started', self.on_mad_started)
        self.mad_scanner.scanner.connect('done', self.on_mad_done)
        self.mad_results = DataStore(MAD, tree=True)
        self.widget.mad_results_view.set_model(self.mad_results)

        self.make_columns()

    def setup(self):
        self.widget.scans_ptable_box.add(self.edge_selector)
        self.plotter = plotter.Plotter(xformat='%g')
        self.widget.scans_plot_frame.add(self.plotter)

        self.sample_store.connect('updated', self.on_sample_updated)
        self.widget.mad_runs_btn.connect('clicked', self.add_mad_runs)
        selection = self.widget.mad_results_view.get_selection()
        selection.connect('changed', self.on_mad_results_selected)

        labels = {
            'energy': (self.beamline.energy, self.widget.scans_energy_fbk, {'format': '{:0.3f} keV'}),
            'attenuation': (self.beamline.attenuator, self.widget.scans_attenuation_fbk, {'format': '{:0.0f} %'}),
            'aperture': (self.beamline.aperture, self.widget.scans_aperture_fbk, {'format': '{:0.0f} \xc2\xb5m'}),
            'deadtime': (
                self.beamline.mca, self.widget.scans_deadtime_fbk,
                {'format': '{:0.0f} %', 'signal': 'deadtime', 'warning': 20.0, 'error': 40.0}
            ),
        }
        self.group_selectors = []
        self.monitors = {
            name: common.DeviceMonitor(dev, lbl, **kw)
            for name, (dev, lbl, kw) in labels.items()
        }

    def make_columns(self):
        # Selected Column
        for data, title in MAD.Columns.items():
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer)
            column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
            column.set_sort_column_id(data)
            if data not in [MAD.Data.LABEL]:
                renderer.set_alignment(0.8, 0.5)
                renderer.props.family = 'Monospace'
            column.set_cell_data_func(renderer, self.format_cell, data)
            column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
            self.widget.mad_results_view.append_column(column)

        # Selected Column
        for data, title in XRF.Columns.items():
            if data == XRF.Data.SELECTED:
                renderer = Gtk.CellRendererToggle(activatable=True)
                renderer.connect('toggled', self.on_xrf_toggled, self.xrf_results)
                column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer, active=data)
                column.set_fixed_width(40)
            else:
                renderer = Gtk.CellRendererText()
                column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                if data == XRF.Data.PERCENT:
                    renderer.set_alignment(0.8, 0.5)
                    renderer.props.family = 'Monospace'
                column.set_cell_data_func(renderer, self.color_cell, data)
            column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
            self.widget.xrf_results_view.append_column(column)

    def format_cell(self, column, renderer, model, itr, data):
        if model[itr][model.specs.Data.PARENT] and data == model.specs.Columns.keys()[0]:
            renderer.set_property('text', model[itr][model.specs.Data.NAME])
        elif model[itr][model.specs.Data.PARENT]:
            renderer.set_property('text', '')
        else:
            renderer.set_property('text', model.specs.Formats[data].format(model[itr][data]))

    def color_cell(self, column, renderer, model, itr, data):
        index = model.get_path(itr)[0]
        renderer.set_property("foreground", colors.Category.GOOG20[index % 20])
        value = model[itr][data]
        renderer.set_property('text', model.specs.Formats[data].format(value))

    def add_mad_runs(self, btn, *args, **kwargs):
        if self.props.run_info:
            confirm_dialog = dialogs.make_dialog(
                Gtk.MessageType.QUESTION, 'Add MAD Datasets',
                ("Three datasets will be added for interactive acquisition. \n"
                 "Please switch to the Data Collection page after this, to proceed with acquitision."),
                buttons=(('Cancel', Gtk.ResponseType.CANCEL), ('Add Datasets', Gtk.ResponseType.OK),)
            )
            response = confirm_dialog.run()
            confirm_dialog.destroy()
            if response == Gtk.ResponseType.OK:
                self.datasets.add_runs(self.props.run_info)
                btn.set_sensitive(False)

    def update_directory(self, directory):
        home = misc.get_project_home()
        dir_text = directory.replace(home, '~')
        self.widget.scans_dir_fbk.set_text(dir_text)

    def on_sample_updated(self, obj):
        sample = self.sample_store.get_current()
        sample_text = '{name}|{group}|{container}|{port}'.format(
            name=sample.get('name', '...'), group=sample.get('group', '...'), container=sample.get('container', '...'),
            port=sample.get('port', '...')
        ).replace('|...', '')
        self.widget.scans_sample_fbk.set_text(sample_text)

    def on_mad_results_selected(self, selection):
        model, itr = selection.get_selected()
        if not itr:
            self.widget.mad_runs_btn.set_sensitive(False)
            return
        if model.iter_has_child(itr):
            parent = itr
        else:
            parent = model.iter_parent(itr)
        itr = model.iter_children(parent)
        keys = ['name', 'label', 'energy', 'wavelength', 'fpp', 'fp', 'parent', 'directory']
        runs = []
        while itr:
            info = dict(zip(keys, model[itr]))
            itr = model.iter_next(itr)
            runs.append({
                'name': info['label'],
                'energy': info['energy'],
            })
        self.widget.mad_selected_lbl.set_text(model[parent][MAD.Data.NAME])
        self.props.run_info = runs
        self.widget.mad_runs_btn.set_sensitive(True)

    def on_mad_started(self, scanner):
        self.update_directory(scanner.config['directory'])

    def on_xrf_started(self, scanner):
        self.update_directory(scanner.config['directory'])
        self.xrf_results.clear()

    def on_mad_done(self, scanner):
        results = scanner.results.get('energies')
        if results is None:
            dialogs.warning('Error Analysing Scan', 'CHOOCH Analysis of XANES Scan failed')
            return

        new_axis = self.plotter.add_axis(label="Anomalous scattering factors (f', f'')")

        if 'infl' in results.keys():
            self.plotter.axis[0].axvline(results['infl'][1], color='#999999', linestyle='--', linewidth=1)
        if 'peak' in results.keys():
            self.plotter.axis[0].axvline(results['peak'][1], color='#999999', linestyle='--', linewidth=1)
        if 'remo' in results.keys():
            self.plotter.axis[0].axvline(results['remo'][1], color='#999999', linestyle='--', linewidth=1)

        data = scanner.results.get('efs')
        self.plotter.add_line(data['energy'], data['fpp'], 'r', label='f"', ax=new_axis)
        self.plotter.add_line(data['energy'], data['fp'], 'g', label="f'", ax=new_axis, redraw=True)
        self.plotter.set_labels(
            title='{} Edge MAD Scan'.format(scanner.config['edge']), x_label='Energy (keV)', y1_label='Fluorescence'
        )

        for key in ['peak', 'infl', 'remo']:
            values = results[key]
            parent, child = self.mad_results.add_item({
                'name': scanner.config['name'],
                'label': key,
                'fpp': values[2],
                'fp': values[3],
                'energy': values[1],
                'wavelength': converter.energy_to_wavelength(values[1]),
                'directory': scanner.config['directory']
            })
            self.widget.mad_results_view.expand_row(parent, False)
            self.widget.mad_results_view.scroll_to_cell(child, None, True, 0.5, 0.5)

    def on_xrf_done(self, scanner):
        self.xrf_annotations = {}
        x = scanner.results['data']['energy']
        y = scanner.results['data']['raw']
        ys = scanner.results['data']['counts']
        yc = scanner.results['data']['fit']
        energy = scanner.config['energy']
        xrf_results = scanner.results['assigned']

        self.plotter.set_labels(title='X-Ray Fluorescence', x_label='Energy (keV)', y1_label='Fluorescence')

        self.plotter.add_line(x, yc, 'm:', label='Fit')
        self.plotter.axis[0].axhline(0.0, color='gray', linewidth=0.5)
        self.plotter.add_line(x, y, 'k-', label='Experimental', alpha=0.2)
        self.plotter.add_line(x, ys, 'b-', label='Smoothed')

        ax = self.plotter.axis[0]
        ax.axis('tight')
        ax.set_xlim(
            -0.25 * self.beamline.config['xrf_energy_offset'],
            energy + 0.25 * self.beamline.config['xrf_energy_offset']
        )

        # get list of elements sorted in descending order of prevalence
        element_list = [(v[0], k) for k, v in xrf_results.items()]
        element_list.sort()
        element_list.reverse()

        peak_log = "%7s %7s %5s %8s %8s\n" % (
            "Element",
            "%Cont",
            "Trans",
            "Energy",
            "Height")

        for index, (prob, el) in enumerate(element_list):
            element = science.PERIODIC_TABLE[el]
            peak_log += 39 * "-" + "\n"
            peak_log += "%7s %7.2f %5s %8s %8s\n" % (el, prob, "", "", "")
            contents = scanner.results['assigned'][el]
            for trans, _nrg, height in contents[1]:
                peak_log += "%7s %7s %5s %8.3f %8.2f\n" % (
                    "", "", trans, _nrg, height)
            if prob < 0.005 * element_list[0][0] or index > 20:
                del xrf_results[el]
                continue
            show = (prob >= 0.1 * element_list[0][0])
            self.xrf_results.add_item({
                'name': element['name'],
                'selected': show,
                'symbol': el,
                'percent': prob
            })
            _color = colors.Category.GOOG20[index % 20]
            element_info = xrf_results.get(el)
            line_list = summarize_lines(element_info[1])
            ln_points = []
            self.xrf_annotations[el] = []
            for _nm, _pos, _ht in line_list:
                if _pos > energy: continue
                ln_points.extend(([_pos, _pos], [0.0, _ht * 0.95]))
                txt = ax.text(_pos, -0.5,
                              "%s-%s" % (el, _nm),
                              rotation=90,
                              fontsize=8,
                              horizontalalignment='center',
                              verticalalignment='top',
                              color=_color
                              )
                self.xrf_annotations[el].append(txt)
            lns = ax.plot(*ln_points, **{'linewidth': 1.0, 'color': _color})
            self.xrf_annotations[el].extend(lns)
            for antn in self.xrf_annotations[el]:
                antn.set_visible(show)
        ax.axvline(energy, c='#cccccc', ls='--', lw=0.5, label='Excitation Energy')

        # self.output_log.add_text(peak_log)
        self.plotter.axis[0].legend()

        # Upload scan to lims
        # lims_tools.upload_scan(self.beamline, [scanner.results])

        ymin, ymax = misc.get_min_max(ys, ldev=1, rdev=1)
        alims = ax.axis()
        ax.axis(ymin=ymin, ymax=ymax)
        self.plotter.redraw()

    def on_xrf_toggled(self, cell, path, model):
        itr = model.get_iter(path)
        index = model.get_path(itr)[0]

        element = model.get_value(itr, XRF.Data.SYMBOL)
        state = model.get_value(itr, XRF.Data.SELECTED)
        model.set(itr, XRF.Data.SELECTED, (not state))
        if state:
            # Hide drawings
            for anotation in self.xrf_annotations[element]:
                anotation.set_visible(False)
        else:
            # Show Drawings
            for anotation in self.xrf_annotations[element]:
                anotation.set_visible(True)
        self.plotter.redraw()
