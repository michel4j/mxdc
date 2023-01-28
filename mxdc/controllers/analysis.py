import os
from enum import Enum

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
    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.sample_store = None

        self.data_store = Gio.ListStore(item_type=analysis.SampleItem)
        self.widget.proc_sample_view.bind_model(self.data_store, reports.create_sample_row)

        self.reports = ReportManager(self.widget.proc_data_view)
        self.analyst = Analyst(self.reports)
        self.browser = WebKit2.WebView()
        self.browser.set_zoom_level(0.85)
        self.options = {}
        self.setup()

    def setup(self):
        self.widget.proc_browser_box.add(self.browser)
        browser_settings = WebKit2.Settings()
        browser_settings.set_property("allow-universal-access-from-file-urls", True)
        browser_settings.set_property("enable-plugins", False)
        browser_settings.set_property("default-font-size", 11)
        self.browser.set_settings(browser_settings)
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

    def clear_reports(self, *args, **kwargs):
        self.reports.clear_selection()

    def import_metafile(self, *args, **kwargs):
        filters = [
            ('MxDC Meta-File', ["*.meta"]),
            ('AutoProcess Report', ["*.html"]),
        ]
        directory = os.path.join(misc.get_project_home(), self.beamline.session_key)
        file_name, file_filter = dialogs.select_opensave_file(
            'Select File', Gtk.FileChooserAction.OPEN, parent=dialogs.MAIN_WINDOW, filters=filters,
            default_folder=directory
        )
        self.sample_store = Registry.get_utility(ISampleStore)
        if not file_name:
            return

        if file_filter.get_name() == filters[0][0]:
            data = misc.load_metadata(file_name)
            print(data)
            if data.get('type') in ['DATA', 'SCREEN', 'XRD']:
                if data.get('sample_id'):
                    row = self.sample_store.find_by_id(data['sample_id'])
                    sample = {} if not row else row[self.sample_store.Data.DATA]
                else:
                    sample = {}
                params = {
                    'title': '',
                    'state': self.reports.State.PENDING,
                    'data': data,
                    'sample_id': data['sample_id'],
                    'sample': sample,
                    'name': data['name'],
                    'type': data['type'],
                    'directory': data['directory'],
                    'activity': data['type'].replace('_', '-').lower()
                }
                self.reports.add_item(params)

                # create and add sample data item
                new_data = analysis.Data(
                    name=data.get('name', '...'),
                    key=data.get('id', 0),
                    kind=data.get('type', ''),
                    size=len(datatools.frameset_to_list(data.get('frames', ''))),
                    file=file_name,
                )

                sample_id = 0 if not data.get('sample_id', 0) else data['sample_id']
                for entry in self.data_store:
                    if entry.key == sample_id:
                        entry.add_data(new_data)
                        break
                else:
                    new_entry = analysis.SampleItem(
                        name=sample.get('name', '...'),
                        group=sample.get('group', '...'),
                        port=sample.get('port', '...'),
                        key=sample_id,
                    )
                    new_entry.add_data(new_data)
                    self.data_store.append(new_entry)
            else:
                self.widget.notifier.notify('Only MX or XRD Meta-Files can be imported')

        else:
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
