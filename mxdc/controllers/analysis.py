import os
from pathlib import Path

import gi
import numpy

gi.require_version('WebKit2', '4.0')
from gi.repository import GObject, WebKit2, Gtk, Gio
from mxdc import Registry, IBeamline, Object, Property
from mxdc.utils import misc
from mxdc.utils.log import get_module_logger
from mxdc.utils.data import analysis
from mxdc.utils import datatools
from mxdc.engines.analysis import Analyst
from mxdc.engines import auto
from mxdc.widgets import dialogs, reports

from mxdc.controllers.datasets import IDatasets
from .samplestore import ISampleStore
from . import common

logger = get_module_logger(__name__)


class ReportManager:

    def __init__(self):
        super().__init__()
        self.sample_store = None
        self.data_store = Gio.ListStore(item_type=analysis.SampleItem)
        self.samples = {}
        self.datasets = {}
        self.reports = {}

    def clear(self):
        self.samples = {}
        self.datasets = {}
        self.reports = {}
        self.data_store.remove_all()

    def add_data(self, data: dict):
        """
        Add a new dataset to the store or update an existing one
        :param data: Dataset metadata
        """
        self.sample_store = Registry.get_utility(ISampleStore)
        sample = {
            "id": data['sample_id'],
            "group": data["group"],
            "port": "",
            "container": data["container"]
        }
        if sample['id']:
            row = self.sample_store.find_by_id(sample['id'])
            if row:
                sample['name'] = row[self.sample_store.Data.DATA]['name']
                sample['port'] = row[self.sample_store.Data.DATA]['port']

        data_id = data.get('id')
        meta_file = data['directory'] + "/" + data["name"] + ".meta"
        key_src = data_id if data_id else data['directory'] + "/" + data["name"]
        data_key = analysis.make_key(f'{key_src}')
        new_data = analysis.Data(
            key=data_key, name=data["name"], kind=data["type"],
            file=meta_file, size=len(datatools.frameset_to_list(data["frames"])),
        )

        directory = Path(data["directory"])
        key_src = sample['id'] if sample['id'] else directory.parent
        sample_key = analysis.make_key(f'{key_src}')

        if sample_key in self.samples:
            sample_entry = self.samples[sample_key]
            sample_entry.add(new_data)
            self.datasets[new_data.key] = new_data
        else:
            sample_entry = analysis.SampleItem(
                name=sample.get('name', '...'), group=sample['group'],
                port=sample["port"], key=sample_key,
            )
            sample_entry.add(new_data)
            self.data_store.append(sample_entry)
            self.samples[sample_key] = sample_entry
            self.datasets[new_data.key] = new_data

    def add_report(self, report: dict, state: analysis.ReportState = analysis.ReportState.ACTIVE):
        """
        Add a new report to the store or replace an existing one.
        :param report: dictionary of report parameters
        :param state: state of the report
        """
        if 'uuid' in report:
            key = report['uuid']
        else:
            key = analysis.make_key(report['directory'])

        new_entry = analysis.Report(
            key=key,
            name=report["name"],
            kind=report['type'],
            score=report.get('score', 0.0),
            directory=report['directory'],
            strategy=report.get('strategy', {}),
            state=state
        )

        if key in self.reports:
            # replace existing entry
            report_entry = self.reports[new_entry.key]
            report_entry.update(**new_entry.to_dict())
        else:
            # create a new entry under each dataset
            self.reports[new_entry.key] = new_entry
            for data_id in report.get("data_id", []):
                data_key = analysis.make_key(f'{data_id}')
                if data_key in self.datasets:
                    data_entry = self.datasets[data_key]
                    data_entry.add(new_entry)

    def update_report(self, key, report: dict, success: bool = True):
        """
        Update the state and score of an existing report
        :param key:  key of the report
        :param report: information about the update
        :param success: State of the report
        """
        state = analysis.ReportState.SUCCESS if success else analysis.ReportState.FAILED
        if key in self.reports:
            report_entry = self.reports[key]
            report_entry.update(
                key=key,
                state=state,
                score=report.get('score', 0.0),
                directory=report['directory'],
                strategy=report.get('strategy', {}),
            )


class AnalysisController(Object):

    folder: common.DataDirectory
    browser:  WebKit2.WebView
    reports: ReportManager
    analyst: Analyst
    sample = Property(type=object)
    strategy = Property(type=object)

    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.reports = ReportManager()
        self.analyst = Analyst()
        self.folder = common.DataDirectory(self.widget.proc_dir_btn, self.widget.proc_dir_fbk)
        self.browser = WebKit2.WebView()

        self.options = {}
        self.widget.proc_sample_view.bind_model(self.reports.data_store, reports.SampleView.factory)
        self.setup()
        Registry.add_utility(analysis.ControllerInterface, self)

    def setup(self):
        self.browser.set_zoom_level(0.90)
        self.analyst.connect('data', self.on_new_data)
        self.analyst.connect('report', self.on_new_report)
        self.analyst.connect('update', self.on_update_report)

        self.connect('notify::sample', self.on_sample)
        self.connect('notify::strategy', self.on_strategy)

        self.widget.proc_browser_box.add(self.browser)
        browser_settings = WebKit2.Settings()
        browser_settings.set_property("allow-universal-access-from-file-urls", True)
        browser_settings.set_property("enable-plugins", False)
        browser_settings.set_property("default-font-size", 11)
        self.browser.set_settings(browser_settings)
        self.browser.bind_property(
            'is-loading', self.widget.browser_progress, 'visible', GObject.BindingFlags.SYNC_CREATE
        )
        self.browser.connect('notify::estimated-load-progress', self.on_browser_progress)
        self.widget.proc_merge_option.set_active(True)
        self.directory = common.DataDirectory(self.widget.proc_dir_btn, self.widget.proc_dir_fbk)
        self.widget.proc_mount_btn.connect('clicked', self.mount_sample)
        self.widget.proc_strategy_btn.connect('clicked', self.use_strategy)
        self.widget.proc_sample_view.connect('row-selected', self.on_row_selected)
        self.widget.proc_run_btn.connect('clicked', self.on_run_analysis)
        self.widget.proc_clear_btn.connect('clicked', self.clear_reports)
        self.widget.proc_open_btn.connect('clicked', self.import_metafile)

        self.options = {
            'screen': self.widget.proc_screen_option,
            'merge': self.widget.proc_merge_option,
            'calibrate': self.widget.proc_calib_option,
            'integrate': self.widget.proc_integrate_option,
            'anomalous': self.widget.proc_anom_btn
        }

    def clear_reports(self, *args, **kwargs):
        response = dialogs.warning(
            "Clear Progress Information",
            "All items in the progress list will be removed. \n"
            "This operation cannot be undone!",
            buttons=(('Cancel', Gtk.ButtonsType.CANCEL), ('Proceed', Gtk.ButtonsType.OK))
        )
        if response == Gtk.ButtonsType.OK:
            self.reports.clear()

    def import_data(self, meta_file: str):
        data = misc.load_metadata(meta_file)
        if data.get('type') in ['DATA', 'SCREEN', 'XRD']:
            self.reports.add_data(data)
        else:
            self.widget.notifier.notify('Only MX or XRD Meta-Files can be imported')

    def import_report(self, json_file: str):
        report_types = {
            'MX Native Analysis': 'NATIVE',
            'MX Screening Analysis': 'SCREEN',
            'MX Anomalous Analysis': 'ANOMALOUS',
        }
        info = misc.load_json(json_file)
        for kind in ['NATIVE', 'SCREEN', 'ANOMALOUS']:
            if kind in info['kind'].upper():
                info['type'] = kind

        info['name'] = info.get('title')
        info['type'] = report_types.get(info['kind'], 'NATIVE')
        self.reports.add_report(info, state=analysis.ReportState.SUCCESS)

    def import_metafile(self, *args, **kwargs):
        filters = {
            'all': dialogs.SmartFilter(name='All Compatible Files', patterns=["*.meta", "*.json", "*.html"]),
            'data': dialogs.SmartFilter(name='MxDC Meta-File', patterns=["*.meta"]),
            'report': dialogs.SmartFilter(name='AutoProcess Report', patterns=["*.json"]),
            'html': dialogs.SmartFilter(name='HTML Report', patterns=["*.html"]),
        }
        file_names, file_filter = dialogs.select_opensave_file(
            'Select Files',
            Gtk.FileChooserAction.OPEN,
            parent=dialogs.MAIN_WINDOW,
            filters=filters.values(),
            multiple=True
        )

        for file_name in file_names:
            if filters["data"].match(file_name):
                self.import_data(file_name)
            elif filters['report'].match(file_name):
                self.import_report(file_name)
            elif filters['html'].match(file_name):
                uri = 'file://{}?v={}'.format(file_name, numpy.random.rand())
                GObject.idle_add(self.browser.load_uri, uri)

    def set_folder(self, folder: str):
        self.folder.set_directory(folder)

    def set_strategy(self, strategy: dict):
        self.props.strategy = strategy

    def set_sample(self, sample: dict):
        self.props.sample = sample

    def browse_file(self, path):
        if os.path.exists(path):
            uri = 'file://{}?v={}'.format(path, numpy.random.rand())
            GObject.idle_add(self.browser.load_uri, uri)

    def mount_sample(self, *args, **kwargs):
        sample = self.props.sample
        if sample:
            port = sample['port']
            if port and self.beamline.automounter.is_mountable(port):
                self.widget.spinner.start()
                auto.auto_mount(self.beamline, port)

    def use_strategy(self, *args, **kwargs):
        strategy = self.props.strategy
        dataset_controller = Registry.get_utility(IDatasets)
        if strategy:
            default_rate = self.beamline.config['default_delta'] / self.beamline.config['default_exposure']
            exposure_rate = strategy.get('exposure_rate', default_rate)
            max_delta = strategy.get('max_delta', self.beamline.config['default_delta'])

            run = {
                'attenuation': strategy.get('attenuation', 0.0),
                'start': strategy.get('start_angle', 0.0),
                'range': strategy.get('total_angle', 180),
                'resolution': strategy.get('resolution', 2.0),
                'exposure': max_delta / exposure_rate,
                'delta': max_delta,
                'name': 'data',
            }

            dataset_controller.add_runs([run])
            data_page = self.widget.main_stack.get_child_by_name('Data')
            self.widget.main_stack.child_set(data_page, needs_attention=True)
            self.widget.notifier.notify("Datasets added. Switch to Data page to proceed.")

    def get_options(self):
        return [k for k, w in list(self.options.items()) if w.get_active()]

    def on_sample(self, *args, **kwargs):
        sample = self.props.sample
        self.widget.proc_mount_btn.set_sensitive(bool(sample))
        mountable = False
        if sample and sample.get('port'):
            mountable = True
            sample_text = '{name}|{port}'.format(
                name=sample.get('name', '...'),
                port=sample.get('port', '...')
            ).replace('|...', '')
            self.widget.proc_sample_fbk.set_text(sample_text)
        else:
            self.widget.proc_sample_fbk.set_text('...')
        self.widget.proc_revealer.set_reveal_child(mountable or bool(self.props.strategy))

    def on_strategy(self, *args, **kwargs):
        self.widget.proc_revealer.set_reveal_child(bool(self.props.sample) or bool(self.props.strategy))

    def on_browser_progress(self, *args, **kwargs):
        self.widget.browser_progress.set_fraction(self.browser.props.estimated_load_progress)

    def on_new_data(self, analyst, data):
        self.reports.add_data(data)

    def on_new_report(self, analyst, report):
        self.reports.add_report(report)
        logger.debug('New Analysis Started')

    def on_update_report(self, analyst, key, report, success):
        self.reports.update_report(key, report, success=success)

    def on_row_selected(self, listbox, row):
        # fetch the item from the row
        item = row.get_child().item
        self.props.sample = item.to_dict()
        selected_types = [
            data.kind for data in item.children if data.selected
        ]
        print(selected_types)
        if 'DATA' in selected_types:
            self.widget.proc_mx_box.set_sensitive(True)
            self.widget.proc_powder_box.set_sensitive(False)
            self.widget.proc_run_btn.set_sensitive(True)
        elif 'XRD' in selected_types:
            self.widget.proc_mx_box.set_sensitive(False)
            self.widget.proc_powder_box.set_sensitive(True)
            self.widget.proc_run_btn.set_sensitive(True)
        else:
            self.widget.proc_mx_box.set_sensitive(False)
            self.widget.proc_powder_box.set_sensitive(False)
            self.widget.proc_run_btn.set_sensitive(False)

    def on_run_analysis(self, *args, **kwargs):
        options = self.get_options()
        model, selected = self.reports.selection.get_selected_rows()
        metas = []
        data_type = None
        sample = None
        for path in selected:
            row = model[path]
            item = self.reports.row_to_dict(row)
            metas.append(item['data'])
            data_type = item['type']
            sample = item['sample']
        if data_type in ['DATA', 'SCREEN']:
            if len(metas) > 1:
                self.analyst.process_multiple(*metas, flags=options, sample=sample)
            elif 'screen' in options:
                self.analyst.screen_dataset(metas[0], flags=options, sample=sample)
            else:
                self.analyst.process_dataset(metas[0], flags=options, sample=sample)
        elif data_type == 'XRD':
            self.analyst.process_powder(metas[0], flags=options, sample=sample)
