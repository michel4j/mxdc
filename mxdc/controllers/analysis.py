import os
import gi

gi.require_version('WebKit', '3.0')
from enum import Enum
from gi.repository import GObject, WebKit
from mxdc.beamlines.mx import IBeamline
from mxdc.utils import colors, misc
from mxdc.utils.decorators import async_call
from mxdc.utils.gui import ColumnSpec, TreeManager, ColumnType
from mxdc.utils.log import get_module_logger
from mxdc.engines.analysis import Analyst
from samplestore import ISampleStore
from twisted.python.components import globalRegistry
from mxdc.engines import auto

logger = get_module_logger(__name__)

DOCS_PATH = os.path.join(os.environ['MXDC_PATH'], 'docs', '_build', 'html', 'index.html')


class ReportManager(TreeManager):
    class Data(Enum):
        NAME, GROUP, ACTIVITY, SCORE, SUMMARY, STATE, UUID, SAMPLE, DIRECTORY, DATA = range(10)

    Types = [str, str, str, float, str, int, str, object, str, object]

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
    tooltips = Data.SUMMARY
    parent = Data.GROUP
    flat = True

    directory = GObject.Property(type=str, default='')
    sample = GObject.Property(type=object)
    strategy = GObject.Property(type=object)

    def update_item(self, item_id, data=None, error=None, summary='????'):
        for item in self.model:
            if item[self.Data.UUID.value] == item_id:
                if data:
                    item[self.Data.DATA.value] = data
                    item[self.Data.SCORE.value] = data.get('score', 0.0)
                    item[self.Data.STATE.value] = self.State.SUCCESS
                elif error:
                    item[self.Data.DATA.value] = None
                    item[self.Data.STATE.value] = self.State.FAILED
                item[self.Data.SUMMARY.value] = summary
                break

    def selection_changed(self, model, itr):
        item = self.item_to_dict(itr, model)
        data = item['data'] or {}
        self.props.strategy = data.get('strategy')
        self.props.directory = item['directory']
        self.props.sample = item['sample']


class AnalysisController(GObject.GObject):

    def __init__(self, widget):
        super(AnalysisController, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        self.reports = ReportManager(self.widget.proc_reports_view)
        self.analyst = Analyst(self.reports)
        self.browser = WebKit.WebView()
        self.setup()
        self.widget.proc_reports_view.connect('row-activated', self.on_row_activated)
        self.reports.connect('notify::directory', self.on_directory)
        self.reports.connect('notify::sample', self.on_sample)
        self.reports.connect('notify::strategy', self.on_strategy)
        self.widget.proc_dir_btn.connect('clicked', self.open_terminal)
        self.widget.proc_mount_btn.connect('clicked', self.mount_sample)

    def setup(self):
        self.widget.proc_browser_box.add(self.browser)
        browser_settings = WebKit.WebSettings()
        browser_settings.set_property("enable-file-access-from-file-uris", True)
        browser_settings.set_property("enable-plugins", False)
        browser_settings.set_property("default-font-size", 11)
        self.browser.set_settings(browser_settings)
        self.browser.load_uri('file://{}'.format(DOCS_PATH))

    def on_strategy(self, *args, **kwargs):
        self.widget.proc_strategy_btn.set_sensitive(bool(self.reports.strategy))
        self.widget.proc_revealer.set_reveal_child(bool(self.reports.sample) or bool(self.reports.strategy))

    def open_terminal(self, button):
        directory = self.widget.proc_dir_fbk.get_text()
        misc.open_terminal(directory)

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

    def on_directory(self, *args, **kwargs):
        directory = self.reports.directory
        if directory:
            home_dir = misc.get_project_home()
            current_dir = directory.replace(home_dir, '~')
            self.widget.proc_dir_fbk.set_text(current_dir)
            self.widget.proc_dir_btn.set_sensitive(True)
        else:
            self.widget.proc_dir_fbk.set_text('')
            self.widget.proc_dir_btn.set_sensitive(False)

    def on_row_activated(self, view, path, column):
        model = view.get_model()
        itr = model.get_iter(path)
        data = model[itr][ReportManager.Data.DATA.value]
        if data:
            filename = os.path.join(data['url'], 'report', 'index.html')
            if os.path.exists(filename):
                uri = 'file://{}'.format(filename)
                GObject.idle_add(self.browser.load_uri, uri)

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

