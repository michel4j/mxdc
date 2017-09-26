import os
import gi

gi.require_version('WebKit', '3.0')
from enum import Enum
from gi.repository import GObject, WebKit
from mxdc.beamline.mx import IBeamline
from mxdc.utils import colors
from mxdc.utils.gui import ColumnSpec, TreeManager, ColumnType
from mxdc.utils.log import get_module_logger
from mxdc.engines.analysis import Analyst
from samplestore import ISampleStore
from twisted.python.components import globalRegistry

logger = get_module_logger(__name__)


class ReportManager(TreeManager):
    class Data(Enum):
        NAME, GROUP, ACTIVITY, SCORE, SUMMARY, STATE, UUID, SAMPLE, DATA = range(9)

    class State:
        PENDING, ACTIVE, SUCCESS, FAILED = range(4)

    Types = [str, str, str, float, str, int, str, object, object]
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

    def setup(self):
        self.widget.proc_browser_box.add(self.browser)
        browser_settings = WebKit.WebSettings()
        browser_settings.set_property("enable-file-access-from-file-uris", True)
        browser_settings.set_property("enable-plugins", False)
        browser_settings.set_property("default-font-size", 11)
        self.browser.set_settings(browser_settings)
        self.browser.load_uri('http://cmcf.lightsource.ca/')

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
