import os
import time
from datetime import datetime

import common
from datasets import IDatasets
from enum import Enum
from gi.repository import Gtk, GObject, WebKit
from mxdc.beamline.mx import IBeamline
from mxdc.utils import colors
from mxdc.utils.gui import ColumnSpec, TreeManager, ColumnType
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs
from samplestore import ISampleStore
from twisted.python.components import globalRegistry

logger = get_module_logger(__name__)


class ReportManager(TreeManager):
    class Data(Enum):
        NAME, GROUP, TYPE, SCORE, SUMMARY, STATE, DATA = range(7)

    Types = [str, str, str, float, str, int, object]
    Columns = ColumnSpec(
        (Data.NAME, 'Name', ColumnType.TEXT, '{}'),
        (Data.TYPE, "Type", ColumnType.TEXT, '{}'),
        (Data.SCORE, 'Score', ColumnType.NUMBER, '{:0.2f}'),
        (Data.SUMMARY, "Summary", ColumnType.TEXT, '{}'),
        (Data.STATE, "", ColumnType.ICON, '{}'),
    )
    parent = Data.GROUP
    flat = True


class AnalysisController(GObject.GObject):
    def __init__(self, widget):
        super(AnalysisController, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        self.reports = ReportManager(self.widget.proc_reports_view)
        self.browser = WebKit.WebView()
        self.setup()

    def setup(self):
        self.widget.proc_browser_box.add(self.browser)
        browser_settings = WebKit.WebSettings()
        browser_settings.set_property("enable-file-access-from-file-uris", True)
        browser_settings.set_property("enable-plugins", False)
        browser_settings.set_property("default-font-size", 11)
        self.browser.set_settings(browser_settings)
        self.browser.load_uri('http://cmcf.lightsource.ca/')

    def add_dataset(self, dataset):
        self.reports.add(dataset)

