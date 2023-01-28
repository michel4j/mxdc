import random

from mxdc.utils.data import analysis
from gi.repository import Gtk, GObject


@Gtk.Template.from_resource('/org/gtk/mxdc/data/data_sample.ui')
class DataSample(Gtk.Box):
    __gtype_name__ = 'DataSample'

    name_label = Gtk.Template.Child()
    group_label = Gtk.Template.Child()
    port_label = Gtk.Template.Child()
    data_list = Gtk.Template.Child()

    item = GObject.Property(type=object)
    report_group = Gtk.SizeGroup(Gtk.SizeGroupMode.BOTH)

    def set_item1(self, item: analysis.SampleItem):
        self.props.item  = item
        self.group_label.set_text(item.group)
        self.name_label.set_text(item.name)
        self.port_label.set_text(item.port)

        for j in range(3):
            data_type = random.choice(['DAT', 'SCR', 'XRD'])
            size = random.choice([360, 12, 720, 900, 1800, 3600, 60, 90, 2])

            data_label = Gtk.CheckButton(f'{data_type} - {size} imgs',active=False)
            data_label.get_style_context().add_class('sample-dataset-label')

            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            box.pack_start(data_label, False, False, 6)
            box.pack_start(Gtk.Label(''), True, True, 6)

            for i in range(random.randint(0, 3)):
                report_type = random.choice(['NAT', 'SCR', 'XRD'])
                score = random.random()
                label = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
                label.pack_start(Gtk.Label(label=report_type), False, False, 0)
                label.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 6)
                label.pack_end(Gtk.Label(f'{score:0.2f}'), True, True, 0)
                report_button = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
                report_button.add(label)
                report_button.get_style_context().add_class('sample-report-button')
                report_button.get_style_context().add_class(f"report-score-{round(score / 0.1):0.0f}")
                print(f"report-score-{round(score / 0.1):0.0f}")
                self.report_group.add_widget(report_button)

                box.pack_end(report_button, False, False, 0)

            self.data_list.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
            self.data_list.pack_start(box, False, False, 0)
            self.data_list.show_all()

    def set_item(self, item: analysis.SampleItem):
        self.props.item  = item
        self.group_label.set_text(item.group)
        self.name_label.set_text(item.name)
        self.port_label.set_text(item.port)

        for data in self.item.datasets.values():
            data_label = Gtk.CheckButton(f'{data.kind} - {data.size} imgs',active=False)
            data_label.get_style_context().add_class('sample-dataset-label')

            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            box.pack_start(data_label, False, False, 6)
            box.pack_start(Gtk.Label(''), True, True, 6)

            for report in data.reports.values():
                label = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
                label.pack_start(Gtk.Label(label=report.kind), False, False, 0)
                label.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 6)
                label.pack_end(Gtk.Label(f'{report.score:0.2f}'), True, True, 0)
                report_button = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
                report_button.add(label)
                report_button.get_style_context().add_class('sample-report-button')
                report_button.get_style_context().add_class(f"report-score-{round(report.score / 0.1):0.0f}")
                self.report_group.add_widget(report_button)

                box.pack_end(report_button, False, False, 0)

            self.data_list.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
            self.data_list.pack_start(box, False, False, 0)
            self.data_list.show_all()




def create_sample_row(item):
    entry = DataSample()
    entry.set_item(item)
    row = Gtk.ListBoxRow(activatable=True, selectable=True)
    row.get_style_context().add_class('data-row')
    row.add(entry)
    return row