
import random
from pathlib import Path

import gi

gi.require_version('WebKit2', '4.0')

from mxdc import Registry, Property
from mxdc.utils.data import analysis
from gi.repository import Gtk, GLib


@Gtk.Template.from_resource('/org/gtk/mxdc/data/report_view.ui')
class ReportView(Gtk.Button):
    __gtype_name__ = 'ReportView'

    report_type = Gtk.Template.Child()
    report_score = Gtk.Template.Child()
    item = Property(type=object)

    def set_item(self, item: analysis.Report):
        self.props.item = item
        self.item.connect('notify', self.on_update)
        self.on_update()

    def on_update(self, *args, **kwargs):
        context = self.get_style_context()
        out_going = [f'report-score-{i}' for i in range(11)] + ['report-failed', 'report-active', 'report-unknown']
        _ = [context.remove_class(cls) for cls in out_going]

        if self.item.state == analysis.ReportState.SUCCESS:
            self.report_type.set_text(self.item.kind[:3].upper())
            self.report_score.set_text(f"{self.item.score:0.2f}")
            context.add_class(f"report-score-{round(self.item.score * 10):0.0f}")
        elif self.item.state == analysis.ReportState.FAILED:
            self.report_type.set_text(self.item.kind[:3].upper())
            self.report_score.set_text(f" ❌ ")
            context.add_class(f"report-failed")
        elif self.item.state == analysis.ReportState.ACTIVE:
            self.report_type.set_text(self.item.kind[:3].upper())
            self.report_score.set_text(f" 🏃 ")
            context.add_class(f"report-active")
        else:
            self.report_type.set_text(self.item.kind[:3].upper())
            self.report_score.set_text(f" ︎❔ ")
            context.add_class(f"report-unknown")

    def do_clicked(self, *args, **kwargs):
        browser = Registry.get_utility(analysis.ReportBrowserInterface)
        path = Path(self.item.file).parent / "report.html"
        if path.exists():
            uri = f'file://{path}?v={random.random()}'
            GLib.idle_add(browser.load_uri, uri)

    @classmethod
    def factory(cls, item: analysis.Report) -> "ReportView":
        """
        Create a new report view for the given report item
        :param item: Report
        """
        entry = cls()
        entry.get_style_context().add_class('report-pill')
        entry.set_item(item)
        return entry


@Gtk.Template.from_resource('/org/gtk/mxdc/data/data_view.ui')
class DataView(Gtk.Box):
    __gtype_name__ = 'DataView'

    data_label = Gtk.Template.Child()
    report_list = Gtk.Template.Child()
    item = Property(type=object)

    def set_item(self, item: analysis.Data):
        self.props.item = item
        num_items = item.children.get_n_items()
        self.report_list.props.max_children_per_line = max(1, min(num_items, 5))
        item.children.connect('items-changed', self.on_items_changed)
        self.report_list.bind_model(item.children, ReportView.factory)
        self.props.item.connect('notify', self.on_update)
        self.data_label.connect('toggled', self.on_toggle)
        self.on_update()

    def on_items_changed(self, store, *args, **kwargs):
        num_items = store.get_n_items()
        self.report_list.props.max_children_per_line = max(1, min(num_items, 5))

    def on_update(self, *args, **kwargs):
        self.data_label.set_label(f'{self.item.kind[:3]} / {self.item.size} img / {self.item.name}')

    def on_toggle(self, btn):
        print(f'Data {self.item} selected={btn.get_active()}')

    @classmethod
    def factory(cls, item: analysis.Data) -> Gtk.ListBoxRow:
        """
        Create a new data view for the given data item
        :param item: Data
        """
        entry = cls()
        entry.set_item(item)
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        row.get_style_context().add_class('data-data-row')
        row.add(entry)
        return row


@Gtk.Template.from_resource('/org/gtk/mxdc/data/sample_view.ui')
class SampleView(Gtk.Box):
    __gtype_name__ = 'SampleView'

    name_label = Gtk.Template.Child()
    group_label = Gtk.Template.Child()
    port_label = Gtk.Template.Child()
    data_list = Gtk.Template.Child()
    item = Property(type=object)

    def set_item(self, item: analysis.SampleItem):
        self.props.item = item
        self.data_list.bind_model(item.children, DataView.factory)
        self.item.connect('notify', self.on_update)
        self.on_update()

    def on_update(self, *args, **kwargs):
        self.name_label.set_text(self.item.name)
        self.group_label.set_text(self.item.group)
        self.port_label.set_text(self.item.port)

    @classmethod
    def factory(cls, item: analysis.SampleItem) -> Gtk.ListBoxRow:
        """
        Create a new Analysis Sample View for a given Sample item
        :param item: Sample
        """
        entry = cls()
        entry.set_item(item)
        row = Gtk.ListBoxRow(activatable=True, selectable=True)
        row.get_style_context().add_class('data-sample-row')
        row.add(entry)
        return row
