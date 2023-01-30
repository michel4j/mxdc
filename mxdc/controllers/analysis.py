import os
import random
from enum import Enum
from pathlib import Path

import gi
import numpy

gi.require_version('WebKit2', '4.0')
from gi.repository import GObject, WebKit2, Gtk, Gdk, Gio
from mxdc import Registry, IBeamline, Object, Property
from mxdc.utils import colors, misc
from mxdc.utils.gui import ColumnSpec, TreeManager, ColumnType
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


class ReportManager(TreeManager):
    class Data(Enum):
        NAME, GROUP, ACTIVITY, TYPE, SCORE, TITLE, STATE, UUID, SAMPLE, DIRECTORY, DATA, REPORT, ERROR = list(range(13))

    Types = [str, str, str, str, float, str, int, str, object, str, object, object, object]

    class State:
        PENDING, ACTIVE, SUCCESS, FAILED = list(range(4))

    Columns = ColumnSpec(
        (Data.NAME, 'Name', ColumnType.TEXT, '{}', True),
        (Data.TITLE, "Title", ColumnType.TEXT, '{}', True),
        (Data.ACTIVITY, "Type", ColumnType.TEXT, '{}', False),
        (Data.SCORE, 'Score', ColumnType.NUMBER, '{:0.2f}', False),

        (Data.STATE, "", ColumnType.ICON, '{}', False),
    )
    Icons = {
        State.PENDING: ('content-loading-symbolic', colors.Category.CAT20[14]),
        State.ACTIVE: ('emblem-synchronizing-symbolic', colors.Category.CAT20[2]),
        State.SUCCESS: ('object-select-symbolic', colors.Category.CAT20[4]),
        State.FAILED: ('computer-fail-symbolic', colors.Category.CAT20[6]),
    }
    #
    # tooltips = Data.TITLE
    parent = Data.NAME
    flat = False
    select_multiple = True
    single_click = True

    directory = Property(type=str, default='')
    sample = Property(type=object)
    strategy = Property(type=object)

    def update_item(self, item_id, report=None, error=None, title='????'):
        itr = self.model.get_iter_first()
        row = None
        while itr and not row:
            if self.model[itr][self.Data.UUID.value] == item_id:
                row = self.model[itr]
                break
            elif self.model.iter_has_child(itr):
                child_itr = self.model.iter_children(itr)
                while child_itr:
                    if self.model[child_itr][self.Data.UUID.value] == item_id:
                        row = self.model[child_itr]
                        break
                    child_itr = self.model.iter_next(child_itr)
            itr = self.model.iter_next(itr)
        if row:
            if report:
                row[self.Data.REPORT.value] = report
                row[self.Data.SCORE.value] = report.get('score', 0.0)
                row[self.Data.STATE.value] = self.State.SUCCESS
            elif error:
                row[self.Data.ERROR.value] = error
                row[self.Data.STATE.value] = self.State.FAILED
            row[self.Data.TITLE.value] = title

    def row_activated(self, view, path, column):
        model = view.get_model()
        itr = model.get_iter(path)
        item = self.row_to_dict(model[itr])
        report = item['report'] or {}
        self.props.strategy = report.get('strategy')
        self.props.directory = item['directory']
        self.props.sample = item['sample']

    def format_cell(self, column, renderer, model, itr, spec):
        super(ReportManager, self).format_cell(column, renderer, model, itr, spec)
        if not model.iter_has_child(itr):
            row = model[itr]
            state = row[self.Data.STATE.value]
            if state == self.State.PENDING:
                renderer.set_property("foreground-rgba", Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=0.7))
            elif state == self.State.FAILED:
                renderer.set_property("foreground-rgba", Gdk.RGBA(red=0.35, green=0.0, blue=0.0, alpha=1.0))
            elif state == self.State.SUCCESS:
                renderer.set_property("foreground-rgba", Gdk.RGBA(red=0.0, green=0.35, blue=0.0, alpha=1.0))
            else:
                renderer.set_property("foreground-rgba", Gdk.RGBA(red=0.35, green=0.35, blue=0.0, alpha=1.0))
        else:
            renderer.set_property("foreground-rgba", None)


class AnalysisController(Object):

    data_folder: common.DataDirectory

    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.sample_store = None

        self.data_store = Gio.ListStore(item_type=analysis.SampleItem)
        self.widget.proc_sample_view.bind_model(self.data_store, reports.SampleView.factory)

        self.reports = ReportManager(self.widget.proc_data_view)
        self.analyst = Analyst(self.reports)
        self.browser = WebKit2.WebView()
        self.browser.set_zoom_level(0.85)
        self.options = {}
        self.setup()
        Registry.add_utility(analysis.ReportBrowserInterface, self.browser)

    def setup(self):
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
        self.widget.proc_single_option.set_active(True)
        self.data_folder = common.DataDirectory(self.widget.proc_dir_btn, self.widget.proc_dir_fbk)
        self.widget.proc_mount_btn.connect('clicked', self.mount_sample)
        self.widget.proc_strategy_btn.connect('clicked', self.use_strategy)
        self.widget.proc_data_view.connect('row-activated', self.on_row_activated)
        self.widget.proc_run_btn.connect('clicked', self.on_run_analysis)
        self.widget.proc_clear_btn.connect('clicked', self.clear_reports)
        self.widget.proc_open_btn.connect('clicked', self.import_metafile)

        self.options = {
            'screen': self.widget.proc_screen_option,
            'merge': self.widget.proc_merge_option,
            'mad': self.widget.proc_mad_option,
            'calibrate': self.widget.proc_calib_option,
            'integrate': self.widget.proc_integrate_option,
            'anomalous': self.widget.proc_anom_btn
        }

    def on_browser_progress(self, *args, **kwargs):
        self.widget.browser_progress.set_fraction(self.browser.props.estimated_load_progress)

    def clear_reports(self, *args, **kwargs):
        response = dialogs.warning(
            "Clear Progress Information",
            "All items in the progress list will be removed. \n"
            "This operation cannot be undone!",
            buttons=(('Cancel', Gtk.ButtonsType.CANCEL), ('Proceed', Gtk.ButtonsType.OK))
        )
        if response == Gtk.ButtonsType.OK:
            self.data_store.remove_all()

    def import_data(self, meta_file: str):
        data = misc.load_metadata(meta_file)
        if data.get('type') in ['DATA', 'SCREEN', 'XRD']:
            sample = {
                "id": data['sample_id'],
                "group": data["group"],
                "port": data["port"],
                "container": data["container"]
            }

            if sample['id']:
                row = self.sample_store.find_by_id(sample['id'])
                if row:
                    sample['name'] = row[self.sample_store.Data.DATA]['name']

            data_id = data.get('id')
            key_src = data_id if data_id else meta_file
            data_key = analysis.make_key(f'{key_src}')
            new_data = analysis.Data(
                key=data_key, name=data["name"], kind=data["type"],
                file=meta_file, size=len(datatools.frameset_to_list(data["frames"])),
                children=[
                    # analysis.Report(
                    #     key=analysis.make_key(f'analysis-{i}'),
                    #     name=f'Analysis {i}',
                    #     kind=random.choice(['NAT', 'SCR', 'XRD']),
                    #     score=random.random(),
                    #     file=analysis.get_random_json(),
                    #     strategy={}
                    # )
                    # for i in range(random.randint(0, 7))
                ]
            )
            directory = Path(data["directory"])
            sample_key = analysis.make_key(str(directory.parent))

            for entry in self.data_store:
                if entry.key == sample_key:
                    entry.add(new_data)
                    break
            else:
                new_entry = analysis.SampleItem(
                    name=sample.get('name', f'Sample-{random.randint(1,100)}'), group=sample.get('group', f'Group-{random.randint(1,100)}'),
                    port=sample["port"], key=sample_key,
                )
                new_entry.add(new_data)
                self.data_store.append(new_entry)
        else:
            self.widget.notifier.notify('Only MX or XRD Meta-Files can be imported')

    def import_report(self, json_file: str):
        report_types = {
            'MX Native Analysis': 'NAT',
            'MX Screening Analysis': 'SCR',
        }
        info = misc.load_json(json_file)
        if info.get("data_id"):
            report = analysis.Report(
                key=analysis.make_key(f'{info["directory"]}'),
                name=info['title'],
                kind=report_types.get(info['kind'], 'NAT'),
                score=info['score'],
                file=json_file,
                state=analysis.ReportState.SUCCESS,
                strategy=info.get('strategy', {})
            )
            found = False
            for data_id in info['data_id']:
                data_key = analysis.make_key(f'{data_id}')
                for sample in self.data_store:
                    data = sample.find(data_key)
                    if data:
                        data.add(report)
                        found = True
                        break

            # not found just load the report
            if not found:
                path = Path(json_file).parent / "report.html"
                uri = 'file://{}?v={}'.format(path, numpy.random.rand())
                GObject.idle_add(self.browser.load_uri, uri)

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
        self.sample_store = Registry.get_utility(ISampleStore)

        for file_name in file_names:
            if filters["data"].match(file_name):
                self.import_data(file_name)
            elif filters['report'].match(file_name):
                self.import_report(file_name)
            elif filters['html'].match(file_name):
                uri = 'file://{}?v={}'.format(file_name, numpy.random.rand())
                GObject.idle_add(self.browser.load_uri, uri)

    def on_sample(self, *args, **kwargs):
        sample = self.reports.sample
        self.widget.proc_mount_btn.set_sensitive(bool(sample))
        if sample:
            sample_text = '{name}|{port}'.format(
                name=sample.get('name', '...'),
                port=sample.get('port', '...')
            ).replace('|...', '')
            self.widget.proc_sample_fbk.set_text(sample_text)
        else:
            self.widget.proc_sample_fbk.set_text('...')
        self.widget.proc_revealer.set_reveal_child(bool(self.reports.sample) or bool(self.reports.strategy))

    def on_row_activated(self, view, path, column):
        model = view.get_model()
        itr = model.get_iter(path)
        item = self.reports.row_to_dict(model[itr])
        report = item['report'] or {}

        sample = item.get('sample', {})
        strategy = report.get('strategy')

        self.widget.proc_mount_btn.set_sensitive(
            bool(sample) and bool(sample.get('port')) and item['state'] == self.reports.State.SUCCESS)
        self.widget.proc_strategy_btn.set_sensitive(bool(self.reports.strategy))
        if sample and sample.get('port'):
            sample_text = '{name}|{port}'.format(
                name=sample.get('name', '...'),
                port=sample.get('port', '...')
            ).replace('|...', '')
            self.widget.proc_sample_fbk.set_text(sample_text)
        else:
            self.widget.proc_sample_fbk.set_text('...')
        self.widget.proc_revealer.set_reveal_child(bool(sample) or bool(strategy))

        directory = item['directory']
        home_dir = misc.get_project_home()
        current_dir = directory.replace(home_dir, '~')
        self.widget.proc_dir_fbk.set_text(current_dir)
        self.widget.proc_dir_btn.set_sensitive(bool(directory))

        if report:
            filename = os.path.join(report['directory'], 'report.html')
            if os.path.exists(filename):
                uri = 'file://{}?v={}'.format(filename, numpy.random.rand())
                GObject.idle_add(self.browser.load_uri, uri)

        self.widget.proc_mx_box.set_sensitive(item['type'] in ['DATA', 'SCREEN'])
        self.widget.proc_powder_box.set_sensitive(item['type'] in ['XRD'])

    def add_dataset(self, dataset):
        self.reports.add(dataset)

    def mount_sample(self, *args, **kwargs):
        if self.reports.props.sample:
            port = self.reports.props.sample['port']
            if port and self.beamline.automounter.is_mountable(port):
                self.widget.spinner.start()
                auto.auto_mount(self.beamline, port)

    def use_strategy(self, *args, **kwargs):
        strategy = self.reports.strategy
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
