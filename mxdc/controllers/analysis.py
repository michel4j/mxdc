import os
import gi

gi.require_version('WebKit', '3.0')
from enum import Enum
from gi.repository import GObject, WebKit, Gtk, Gdk
from mxdc.conf import settings
from mxdc.beamlines.mx import IBeamline
from mxdc.utils import colors, misc
from mxdc.utils.decorators import async_call
from mxdc.utils.gui import ColumnSpec, TreeManager, ColumnType
from mxdc.utils.log import get_module_logger
from mxdc.engines.analysis import Analyst
from samplestore import ISampleStore
from twisted.python.components import globalRegistry
from mxdc.engines import auto
from mxdc.widgets import dialogs

logger = get_module_logger(__name__)

#DOCS_PATH = os.path.join(os.environ['MXDC_PATH'], 'docs', '_build', 'html', 'index.html')


class ReportManager(TreeManager):
    class Data(Enum):
        NAME, GROUP, ACTIVITY, TYPE, SCORE, SUMMARY, STATE, UUID, SAMPLE, DIRECTORY, DATA, REPORT, ERROR = range(13)

    Types = [str, str, str, str, float, str, int, str, object, str, object, object, object]

    class State:
        PENDING, ACTIVE, SUCCESS, FAILED = range(4)

    Columns = ColumnSpec(
        (Data.NAME, 'Name', ColumnType.TEXT, '{}', True),
        (Data.ACTIVITY, "Type", ColumnType.TEXT, '{}', True),
        (Data.SCORE, 'Score', ColumnType.NUMBER, '{:0.2f}', False),
        (Data.SUMMARY, "Summary", ColumnType.TEXT, '{}', True),
        (Data.STATE, "", ColumnType.ICON, '{}', False),
    )
    Icons = {
        State.PENDING: ('content-loading-symbolic', colors.Category.CAT20[14]),
        State.ACTIVE: ('emblem-synchronizing-symbolic', colors.Category.CAT20[2]),
        State.SUCCESS: ('object-select-symbolic', colors.Category.CAT20[4]),
        State.FAILED: ('computer-fail-symbolic', colors.Category.CAT20[6]),
    }
    #
    # tooltips = Data.SUMMARY
    parent = Data.NAME
    flat = False
    select_multiple = True
    single_click = True

    directory = GObject.Property(type=str, default='')
    sample = GObject.Property(type=object)
    strategy = GObject.Property(type=object)

    def update_item(self, item_id, report=None, error=None, summary='????'):
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
            row[self.Data.SUMMARY.value] = summary


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


class AnalysisController(GObject.GObject):
    def __init__(self, widget):
        super(AnalysisController, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.sample_store = None
        self.reports = ReportManager(self.widget.proc_reports_view)
        self.analyst = Analyst(self.reports)
        self.browser = WebKit.WebView()
        self.options = {}
        self.setup()

    def setup(self):
        self.widget.proc_browser_box.add(self.browser)
        browser_settings = WebKit.WebSettings()
        browser_settings.set_property("enable-file-access-from-file-uris", True)
        browser_settings.set_property("enable-plugins", False)
        browser_settings.set_property("default-font-size", 11)
        self.browser.set_settings(browser_settings)

        self.widget.proc_dir_btn.connect('clicked', self.open_terminal)
        self.widget.proc_mount_btn.connect('clicked', self.mount_sample)
        self.widget.proc_reports_view.connect('row-activated', self.on_row_activated)
        self.widget.proc_run_btn.connect('clicked', self.on_run_analysis)
        self.widget.proc_clear_btn.connect('clicked', self.clear_reports)
        self.widget.proc_open_btn.connect('clicked', self.import_metafile)

        self.options = {
            'screen': self.widget.proc_screen_btn,
            'merge': self.widget.proc_merge_option,
            'mad': self.widget.proc_mad_option,
            'calibrate': self.widget.proc_calib_option,
            'integrate': self.widget.proc_integrate_option,
            'anomalous': self.widget.proc_anom_btn
        }

    def open_terminal(self, button):
        directory = self.widget.proc_dir_fbk.get_text()
        misc.open_terminal(directory)

    def clear_reports(self, *args, **kwargs):
        self.reports.clear()

    def import_metafile(self, *args, **kwargs):
        filters = [
                ('MxDC Meta-File', ["*.meta"]),
                ('AutoProcess Meta-File', ["*.json"]),
        ]
        directory = os.path.join(misc.get_project_home(), settings.get_session())
        filename, filter =  dialogs.select_opensave_file(
            'Select Meta-File', Gtk.FileChooserAction.OPEN, parent=dialogs.MAIN_WINDOW, filters=filters,
            default_folder=directory
        )
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        if not filename:
            return
        if filter.get_name() == filters[0][0]:
            data = misc.load_metadata(filename)
            if data.get('type') in ['MX_DATA', 'MX_SCREEN', 'XRD_DATA']:
                if data.get('sample_id'):
                    row = self.sample_store.find_by_id(data['sample_id'])
                    sample = row[self.sample_store.Data.DATA]
                else:
                    sample = {}
                params = {
                    'summary': '',
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
            else:
                self.widget.notifier.notify('Only MX or XRD Meta-Files can be imported')

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

        sample = item.get('sample')
        strategy = report.get('strategy')
        self.widget.proc_mount_btn.set_sensitive(bool(sample) and item['state'] == self.reports.State.SUCCESS)
        if sample:
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
            filename = os.path.join(report['url'], 'report', 'index.html')
            if os.path.exists(filename):
                uri = 'file://{}'.format(filename)
                GObject.idle_add(self.browser.load_uri, uri)

        self.widget.proc_mx_box.set_sensitive(item['type'] in ['MX_DATA', 'MX_SCREEN'])
        self.widget.proc_powder_box.set_sensitive(item['type'] in ['XRD_DATA'])

    def add_dataset(self, dataset):
        self.reports.add(dataset)

    @async_call
    def mount_sample(self, *args, **kwargs):
        if self.reports.props.sample:
            port = self.reports.props.sample['port']
            if port and self.beamline.automounter.is_mountable(port):
                self.widget.spinner.start()
                auto.auto_mount_manual(self.beamline, port)
            elif not port:
                # FIXME: Manual mounting here
                pass

    def get_options(self):
        return [k for k, w in self.options.items() if w.get_active()]

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
        if data_type in ['MX_DATA', 'MX_SCREEN']:
            if len(metas) > 1:
                self.analyst.process_multiple(*metas, flags=options, sample=sample)
            elif 'screen' in options:
                self.analyst.screen_dataset(metas[0], flags=options, sample=sample)
            else:
                self.analyst.process_dataset(metas[0], flags=options, sample=sample)
        elif data_type == 'XRD_DATA':
            self.analyst.process_powder(metas[0], flags=options, sample=sample)

