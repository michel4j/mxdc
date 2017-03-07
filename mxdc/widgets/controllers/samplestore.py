from collections import OrderedDict
from gi.repository import Gtk, Gdk, Pango
from twisted.python.components import globalRegistry
from mxdc.beamline.mx import IBeamline
from mxdc.engine import auto
from mxdc.utils.decorators import async
from mxdc.widgets.controllers import automounter


class SampleStore(object):
    class Data(object):
        (
            SELECTED,
            NAME,
            GROUP,
            CONTAINER,
            PORT,
            LOADED,
            BARCODE,
            PRIORITY,
            COMMENTS,
            STATE,
            CONTAINER_TYPE,
            PROCESSED,
            DATA,
        ) = range(13)

    class State(object):
        (
            EMPTY,
            GOOD,
            UNKNOWN,
            MOUNTED,
            JAMMED,
            NONE
        ) = range(6)

    Column = OrderedDict([
        (Data.SELECTED, ''),
        (Data.NAME, 'Name'),
        (Data.GROUP, 'Group'),
        (Data.CONTAINER, 'Container'),
        (Data.CONTAINER_TYPE, 'Type'),
        (Data.PORT, 'Port'),
        (Data.PRIORITY, 'Priority'),
    ])

    Color = {
        State.UNKNOWN: Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=0),
        State.EMPTY: Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=0.5),
        State.JAMMED: Gdk.RGBA(red=1.0, green=0, blue=0, alpha=0.5),
        State.MOUNTED: Gdk.RGBA(red=1.0, green=0, blue=1.0, alpha=0.5),
        State.NONE: Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=1.0),
        State.GOOD: Gdk.RGBA(red=0, green=1.0, blue=0, alpha=0.5)
    }

    def __init__(self, view, widget):
        self.model = Gtk.ListStore(
            bool, str, str, str, str, bool, str, int, str, int, str, bool, object
        )
        self.next_sample = {}
        self.current_sample = {}

        self.view = view
        self.widget = widget
        self.view.set_model(self.model)
        self.beamline = globalRegistry.lookup([], IBeamline)

        self.setup()

        self.widget.samples_selectall_btn.connect('clicked', lambda x: self.select_all(True))
        self.widget.samples_selectnone_btn.connect('clicked', lambda x: self.select_all(False))
        self.widget.samples_clear_btn.connect('clicked', lambda x: self.clear())
        self.view.connect('key-press-event', self.on_key_press)
        self.widget.mxlive_import_btn.connect('clicked', lambda x: self.import_mxlive())
        self.beamline.automounter.connect('mounted', self.on_sample_mounted)
        self.beamline.automounter.connect('samples-updated', self.on_automounter_states)
        self.widget.samples_mount_btn.connect('clicked', lambda x: self.mount_action())
        self.widget.samples_dismount_btn.connect('clicked', lambda x: self.dismount_action())

        self.load_data(TEST_DATA.values())

    def setup(self):
        # Selected Column
        for data, title in self.Column.items():
            if data == self.Data.SELECTED:
                renderer = Gtk.CellRendererToggle(activatable=True)
                renderer.connect('toggled', self.on_row_toggled, self.model)
                column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer, active=data)
                column.set_fixed_width(30)
                column.set_cell_data_func(renderer, self.format_state)
            else:
                renderer = Gtk.CellRendererText()
                column = Gtk.TreeViewColumn(title=title, cell_renderer=renderer, text=data)
                column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
                column.set_expand(True)
                column.set_sort_column_id(data)
                column.set_cell_data_func(renderer, self.format_processed)
                if data in [self.Data.NAME, self.Data.GROUP]:
                    column.set_resizable(True)
            column.set_clickable(True)
            column.props.sizing = Gtk.TreeViewColumnSizing.FIXED
            self.view.append_column(column)

        self.selection = self.view.get_selection()
        self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        self.view.props.activate_on_single_click = False
        self.view.connect('row-activated', self.on_row_activated)
        self.view.set_enable_search(True)
        self.view.set_search_entry(self.widget.samples_search_entry)
        self.view.set_search_column(self.Data.NAME)
        self.view.set_tooltip_column(self.Data.COMMENTS)
        self.view.set_search_column(self.Data.NAME)
        self.model.set_sort_column_id(self.Data.PRIORITY, Gtk.SortType.DESCENDING)
        self.model.connect('sort-column-changed', lambda x: self.update_next_sample())
        self.update_current_sample()
        self.update_next_sample()

        self.sample_dewar = automounter.DewarController(self.widget, self)
        self.sample_dewar.connect('selected', self.on_dewar_selected)

    def load_data(self, data):
        self.clear()
        for item in data:
            self.add_item(item)

    def add_item(self, item):
        itr = self.model.append()
        self.model.set(
            itr,
            self.Data.SELECTED, item.get('selected', False),
            self.Data.NAME, item.get('name', 'unknown'),
            self.Data.GROUP, item.get('group', ''),
            self.Data.CONTAINER, item.get('container_name', ''),
            self.Data.CONTAINER_TYPE, item.get('container_type', ''),
            self.Data.PORT, item.get('port', ''),
            self.Data.PRIORITY, item.get('priority', 0),
            self.Data.STATE, item.get('state', self.State.UNKNOWN),
            self.Data.COMMENTS, item.get('comments', ''),
            self.Data.BARCODE, item.get('barcode', ''),
            self.Data.LOADED, item.get('loaded', False),
            self.Data.PROCESSED, False,
            self.Data.DATA, item,
        )

    def import_mxlive(self):
        # data = self.beamline.lims.get_project_samples()
        self.load_data(TEST_DATA.values())

    def format_state(self, column, cell, model, itr, data):
        value = model.get_value(itr, self.Data.STATE)
        cell.set_property("cell-background-rgba", self.Color[value])

    def format_processed(self, column, cell, model, itr, data):
        value = model.get_value(itr, self.Data.PROCESSED)
        if value:
            cell.set_property("style", Pango.Style.ITALIC)
        else:
            cell.set_property("style", Pango.Style.NORMAL)

    def update_next_sample(self):
        items = self.get_selected()
        if items:
            self.widget.samples_info1_lbl.set_markup('{} Selected'.format(len(items)))
            self.next_sample = items[0]
            self.widget.samples_mount_btn.set_sensitive(True)
        else:
            self.widget.samples_info1_lbl.set_markup('')
            self.next_sample = {}
            self.widget.samples_mount_btn.set_sensitive(False)

        self.widget.samples_next_sample.set_markup(
            '<span color="blue">{}</span>'.format(self.next_sample.get('name', '...'))
        )
        self.widget.samples_next_port.set_markup(
            '{}/{}'.format(self.next_sample.get('container_name', '...'), self.next_sample.get('port', '...'))
        )

    def update_current_sample(self):
        if self.current_sample:
            self.widget.samples_dismount_btn.set_sensitive(True)
        else:
            self.widget.samples_dismount_btn.set_sensitive(False)

        self.widget.samples_cur_sample.set_markup(
            '<span color="blue">{}</span>'.format(self.current_sample.get('name', '...'))
        )
        self.widget.samples_cur_port.set_markup(
            '{}/{}'.format(self.current_sample.get('container_name', '...'), self.current_sample.get('port', '...'))
        )

    def get_next(self):
        itr = self.model.get_iter_first()
        while itr and not self.model.get_value(itr, self.Data.SELECTED):
            itr = self.model.iter_next(itr)
        if itr:
            return Gtk.TreeRowReference.new(self.model, self.model.get_path(itr))

    def find_by_port(self, port):
        itr = self.model.get_iter_first()
        while itr and self.model.get_value(itr, self.Data.PORT) != port:
            itr = self.model.iter_next(itr)
        if itr:
            return self.model.get_value(itr, self.Data.DATA), itr
        else:
            return {}, None

    def get_selected(self):
        itr = self.model.get_iter_first()
        items = []
        while itr:
            sel = self.model.get_value(itr, self.Data.SELECTED)
            state = self.model.get_value(itr, self.Data.STATE)
            if sel and state in [self.State.GOOD, self.State.UNKNOWN, self.State.MOUNTED]:
                item = self.model.get_value(itr, self.Data.DATA)
                item['path'] = self.model.get_path(itr)
                items.append(item)
            itr = self.model.iter_next(itr)
        return items

    def select_all(self, option=True):
        model, paths = self.selection.get_selected_rows()
        # toggle all selected rows otherwise toggle the whole list
        if len(paths) > 1:
            for path in paths:
                itr = self.model.get_iter(path)
                self.model.set_value(itr, self.Data.SELECTED, option)
        else:
            itr = self.model.get_iter_first()
            while itr:
                state = self.model.get_value(itr, self.Data.STATE)
                if state in [self.State.GOOD, self.State.UNKNOWN, self.State.MOUNTED]:
                    self.model.set_value(itr, self.Data.SELECTED, option)
                itr = self.model.iter_next(itr)
        self.update_next_sample()

    def clear(self):
        self.model.clear()
        self.update_next_sample()

    def toggle_row(self, path):
        itr = self.model.get_iter(path)
        value = self.model.get_value(itr, self.Data.SELECTED)
        state = self.model.get_value(itr, self.Data.STATE)
        if state in [self.State.GOOD, self.State.UNKNOWN, self.State.MOUNTED]:
            selected = not value
            self.model.set(itr, self.Data.SELECTED, selected)
            if selected:
                self.model.set(itr, self.Data.PROCESSED, False)
        self.update_next_sample()

    def update_states(self, states):
        itr = self.model.get_iter_first()
        while itr:
            port = self.model.get_value(itr, self.Data.PORT)
            if port in states:
                self.model.set(itr, self.Data.STATE, states[port])
            itr = self.model.iter_next(itr)

    def on_automounter_states(self, obj, states):
        self.update_states(states)

    def on_dewar_selected(self, obj, port):
        self.next_sample, itr = self.find_by_port(port)
        if self.next_sample:
            self.widget.samples_mount_btn.set_sensitive(True)
        else:
            self.widget.samples_mount_btn.set_sensitive(False)
        self.widget.samples_next_sample.set_markup(
            '<span color="blue">{}</span>'.format(self.next_sample.get('name', '...'))
        )
        self.widget.samples_next_port.set_markup(
            '{}/{}'.format(self.next_sample.get('container_name', '...'), self.next_sample.get('port', '...'))
        )

    def on_sample_mounted(self, obj, info):
        if info:
            port, barcode = info
            self.current_sample, itr = self.find_by_port(port)
            self.model.set(
                itr, self.Data.SELECTED, False, self.Data.PROCESSED, True
            )
            self.widget.samples_dismount_btn.set_sensitive(True)
        else:
            self.current_sample = {}

        self.widget.spinner.stop()
        self.update_next_sample()
        self.update_current_sample()

    def on_key_press(self, obj, event):
        return self.widget.samples_search_bar.handle_event(event)

    def on_row_activated(self, obj, path, column):
        self.toggle_row(path)

    def on_row_toggled(self, cell, path, model):
        self.toggle_row(path)

    @async
    def mount_action(self):
        self.widget.spinner.start()
        if self.next_sample and self.beamline.automounter.is_mountable(self.next_sample['port']):
            auto.auto_mount_manual(self.beamline, self.next_sample['port'])

    @async
    def dismount_action(self):
        self.widget.spinner.start()
        if self.current_sample and self.beamline.automounter.is_mounted(self.current_sample['port']):
            auto.auto_dismount_manual(self.beamline, self.current_sample['port'])


TEST_DATA = {
    "46889": {
        "barcode": "",
        "group": "N110A+NADH",
        "name": "N110A_NADH_16_1",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46889,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "9",
        "experiment_id": 7652,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB9"
    },
    "46888": {
        "barcode": "",
        "group": "W128Y+NADH",
        "name": "W128Y_NADH_15_4",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46888,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "8",
        "experiment_id": 7648,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB8"
    },
    "46883": {
        "barcode": "",
        "group": "ScabinWT+nicotinamide",
        "name": "WT_nico_14_3",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46883,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "3",
        "experiment_id": 7651,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB3"
    },
    "46882": {
        "barcode": "",
        "group": "ScabinWT+nicotinamide",
        "name": "WT_nico_10_2",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46882,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "2",
        "experiment_id": 7651,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB2"
    },
    "46881": {
        "barcode": "",
        "group": "ScabinWT+nicotinamide",
        "name": "WT_nico_11_1",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46881,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "1",
        "experiment_id": 7651,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB1"
    },
    "46880": {
        "barcode": "",
        "group": "S117A",
        "name": "S117A_14_4",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46880,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "15",
        "experiment_id": 7650,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC15"
    },
    "46887": {
        "barcode": "",
        "group": "W128Y+NADH",
        "name": "W128Y_NADH_15_3",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46887,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "7",
        "experiment_id": 7648,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB7"
    },
    "46886": {
        "barcode": "",
        "group": "W128Y+NADH",
        "name": "W128Y_NADH_15_2",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46886,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "6",
        "experiment_id": 7648,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB6"
    },
    "46885": {
        "barcode": "",
        "group": "W128Y+NADH",
        "name": "W128Y_NADH_15_1",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46885,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "5",
        "experiment_id": 7648,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB5"
    },
    "46884": {
        "barcode": "",
        "group": "ScabinWT+nicotinamide",
        "name": "WT_nico_12_4",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46884,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "4",
        "experiment_id": 7651,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB4"
    },
    "46869": {
        "barcode": "",
        "group": "W128Y ",
        "name": "W128Y_14_4",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46869,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "4",
        "experiment_id": 7647,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC4"
    },
    "46868": {
        "barcode": "",
        "group": "W128Y ",
        "name": "W128Y_14_3",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46868,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "3",
        "experiment_id": 7647,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC3"
    },
    "46902": {
        "barcode": "",
        "group": "W155A",
        "name": "W155A_15_2",
        "container_id": 3988,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46902,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "6",
        "experiment_id": 7656,
        "container_name": "CLS-0057",
        "loaded": True,
        "project_id": 47,
        "port": "RA6"
    },
    "46903": {
        "barcode": "",
        "group": "W155A",
        "name": "W155A_15_3",
        "container_id": 3988,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46903,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "7",
        "experiment_id": 7656,
        "container_name": "CLS-0057",
        "loaded": True,
        "project_id": 47,
        "port": "RA7"
    },
    "46900": {
        "barcode": "",
        "group": "WT+ADPr",
        "name": "WT_ADPr_11_4",
        "container_id": 3988,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46900,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "4",
        "experiment_id": 7653,
        "container_name": "CLS-0057",
        "loaded": True,
        "project_id": 47,
        "port": "RA4"
    },
    "46901": {
        "barcode": "",
        "group": "W155A",
        "name": "W155A_15_1",
        "container_id": 3988,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46901,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "5",
        "experiment_id": 7656,
        "container_name": "CLS-0057",
        "loaded": True,
        "project_id": 47,
        "port": "RA5"
    },
    "46865": {
        "barcode": "",
        "group": "W128Y ",
        "name": "W128Y_14_2",
        "container_id": 3985,
        "comments": "12% glycerol cryo",
        "id": 46865,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "4",
        "experiment_id": 7647,
        "container_name": "CLS-0054",
        "loaded": True,
        "project_id": 47,
        "port": "RD4"
    },
    "46864": {
        "barcode": "",
        "group": "W128Y ",
        "name": "W128Y_14_1",
        "container_id": 3985,
        "comments": "12% glycerol cryo",
        "id": 46864,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "3",
        "experiment_id": 7647,
        "container_name": "CLS-0054",
        "loaded": True,
        "project_id": 47,
        "port": "RD3"
    },
    "46867": {
        "barcode": "",
        "group": "N110A",
        "name": "N110A_14_1",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46867,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "2",
        "experiment_id": 7649,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC2"
    },
    "46905": {
        "barcode": "",
        "group": "Plx2Atest",
        "name": "Plx2Atest",
        "container_id": 3988,
        "comments": "",
        "id": 46905,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "10",
        "experiment_id": 7657,
        "container_name": "CLS-0057",
        "loaded": True,
        "project_id": 47,
        "port": "RA10"
    },
    "46862": {
        "barcode": "",
        "group": "W128Y ",
        "name": "W128Y_16",
        "container_id": 3985,
        "comments": "12% glycerol cryo",
        "id": 46862,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "1",
        "experiment_id": 7647,
        "container_name": "CLS-0054",
        "loaded": True,
        "project_id": 47,
        "port": "RD1"
    },
    "46894": {
        "barcode": "",
        "group": "WT+ADPr+nicotinamide",
        "name": "WT_ADPr_nico_13_2",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46894,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "14",
        "experiment_id": 7654,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB14"
    },
    "46895": {
        "barcode": "",
        "group": "WT+ADPr+nicotinamide",
        "name": "WT_ADPr_nico_13_3",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46895,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "15",
        "experiment_id": 7654,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB15"
    },
    "46896": {
        "barcode": "",
        "group": "WT+ADPr+nicotinamide",
        "name": "WT_ADPr_nico_12_4",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46896,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "16",
        "experiment_id": 7654,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB16"
    },
    "46897": {
        "barcode": "",
        "group": "WT+ADPr",
        "name": "WT_ADPr_11_1",
        "container_id": 3988,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46897,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "1",
        "experiment_id": 7653,
        "container_name": "CLS-0057",
        "loaded": True,
        "project_id": 47,
        "port": "RA1"
    },
    "46890": {
        "barcode": "",
        "group": "N110A+NADH",
        "name": "N110A_NADH_15_2",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46890,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "10",
        "experiment_id": 7652,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB10"
    },
    "46904": {
        "barcode": "",
        "group": "S117A+NADH",
        "name": "S117A_NADH_16_1",
        "container_id": 3988,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46904,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "8",
        "experiment_id": 7655,
        "container_name": "CLS-0057",
        "loaded": True,
        "project_id": 47,
        "port": "RA8"
    },
    "46892": {
        "barcode": "",
        "group": "N110A+NADH",
        "name": "N110A_NADH_16_4",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46892,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "12",
        "experiment_id": 7652,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB12"
    },
    "46893": {
        "barcode": "",
        "group": "WT+ADPr+nicotinamide",
        "name": "WT_ADPr_nico_13_1",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46893,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "13",
        "experiment_id": 7654,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB13"
    },
    "46866": {
        "barcode": "",
        "group": "W128Y ",
        "name": "W128Y_15_1",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46866,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "1",
        "experiment_id": 7647,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC1"
    },
    "46898": {
        "barcode": "",
        "group": "WT+ADPr",
        "name": "WT_ADPr_14_2",
        "container_id": 3988,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46898,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "2",
        "experiment_id": 7653,
        "container_name": "CLS-0057",
        "loaded": True,
        "project_id": 47,
        "port": "RA2"
    },
    "46899": {
        "barcode": "",
        "group": "WT+ADPr",
        "name": "WT_ADPr_14_3",
        "container_id": 3988,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46899,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "3",
        "experiment_id": 7653,
        "container_name": "CLS-0057",
        "loaded": True,
        "project_id": 47,
        "port": "RA3"
    },
    "46891": {
        "barcode": "",
        "group": "N110A+NADH",
        "name": "N110A_NADH_16_3",
        "container_id": 3987,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46891,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "11",
        "experiment_id": 7652,
        "container_name": "CLS-0056",
        "loaded": True,
        "project_id": 47,
        "port": "RB11"
    },
    "46863": {
        "barcode": "",
        "group": "W128Y ",
        "name": "W128Y_16_2",
        "container_id": 3985,
        "comments": "12% glycerol cryo",
        "id": 46863,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "2",
        "experiment_id": 7647,
        "container_name": "CLS-0054",
        "loaded": True,
        "project_id": 47,
        "port": "RD2"
    },
    "46878": {
        "barcode": "",
        "group": "S117A",
        "name": "S117A_15_2",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46878,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "13",
        "experiment_id": 7650,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC13"
    },
    "46879": {
        "barcode": "",
        "group": "S117A",
        "name": "S117A_14_3",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46879,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "14",
        "experiment_id": 7650,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC14"
    },
    "46872": {
        "barcode": "",
        "group": "N110A",
        "name": "N110A_14_3",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46872,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "7",
        "experiment_id": 7649,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC7"
    },
    "46873": {
        "barcode": "",
        "group": "N110A",
        "name": "N110A_14_4",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46873,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "8",
        "experiment_id": 7649,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC8"
    },
    "46870": {
        "barcode": "",
        "group": "W128Y ",
        "name": "W128Y_15_2",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46870,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "5",
        "experiment_id": 7647,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC5"
    },
    "46871": {
        "barcode": "",
        "group": "N110A",
        "name": "N110A_14_2",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46871,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "6",
        "experiment_id": 7649,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC6"
    },
    "46876": {
        "barcode": "",
        "group": "S117A",
        "name": "S117A_14_2",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46876,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "11",
        "experiment_id": 7650,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC11"
    },
    "46877": {
        "barcode": "",
        "group": "S117A",
        "name": "S117A_15_1",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46877,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "12",
        "experiment_id": 7650,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC12"
    },
    "46874": {
        "barcode": "",
        "group": "N110A",
        "name": "N110A_14_5",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46874,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "9",
        "experiment_id": 7649,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC9"
    },
    "46875": {
        "barcode": "",
        "group": "S117A",
        "name": "S117A_14_1",
        "container_id": 3986,
        "comments": "12%->13.5%->15% glycerol cryo",
        "id": 46875,
        "state": 1,
        "container_type": "Uni-Puck",
        "container_location": "10",
        "experiment_id": 7650,
        "container_name": "CLS-0055",
        "loaded": True,
        "project_id": 47,
        "port": "RC10"
    }
}
