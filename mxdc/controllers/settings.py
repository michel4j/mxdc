from gi.repository import Gio, Gtk
from mxdc.conf import settings
from mxdc.utils import gui
from mxdc import Object, Property
import re


TEMPLATE_VARIABLES = {'sample', 'group', 'container', 'position', 'port', 'date', 'activity'}
SCREENING_VARIABLES = {'autoprocess', 'mosflm'}


class Setting(Object):
    name = Property(type=str, default='')
    key = Property(type=str, default='')
    icon = Property(type=str, default='')
    info = Property(type=object)
    value = Property(type=str, default='')

    def __init__(self, key, icon, validator, kind='string'):
        super().__init__()
        self.props.icon = icon
        self.props.key = key
        self.kind = kind
        self.props.name = key.replace('-', ' ').title()
        self.props.info = settings.get_setting_properties(key)
        self.validator = validator

        self.props.value = settings.get_string(key)
        settings.Settings.bind(key, self, 'value', 0)

    def validate(self, value):
        return self.validator(value)


class SettingRow(gui.Builder):
    gui_roots = {
        'data/settings': ['setting_row']
    }
    ROW_SIZE_GROUP = Gtk.SizeGroup(Gtk.SizeGroupMode.VERTICAL)

    def __init__(self, item):
        super(SettingRow, self).__init__()
        self.item = item
        self.name.set_text(item.props.name)
        self.icon.set_from_icon_name(self.item.icon, Gtk.IconSize.SMALL_TOOLBAR)

    def get_widget(self):
        row = Gtk.ListBoxRow()
        self.ROW_SIZE_GROUP.add_widget(self.setting_row)
        row.get_style_context().add_class('setting-row')
        row.add(self.setting_row)
        row.item = self.item
        return row


def valid_template(txt):
    keys = set(re.findall('\{([\w]+?)\}', txt))
    valid = (
        re.match('^[{\w\d}/-]+$', txt) and
        re.match('^/(?:(?:\{[\w]+?\})*(?:[\d\w/-]*))*$', txt) and
        keys <= TEMPLATE_VARIABLES
    )
    return bool(valid)


def valid_screening(txt):
    return txt.strip().lower() in SCREENING_VARIABLES


def valid_mode(value):
    print (value)
    return bool(value)


class SettingsDialog(gui.BuilderMixin):
    gui_roots = {
        'data/settings': ['settings_dialog']
    }

    OPTIONS = [
        ('directory-template', 'dir-template-symbolic', valid_template),
        ('screening-method', 'error-correct-symbolic', valid_screening),
    ]

    def __init__(self, parent):
        self.setup_gui()
        self.settings = Gio.ListStore(item_type=Setting)
        self.settings_list.bind_model(self.settings, self.create_setting)
        self.settings_list.connect('row-selected', self.on_row_selected)
        self.active_item = None
        for key, icon, validator in self.OPTIONS:
            item = Setting(key, icon, validator)
            self.settings.append(item)
        self.settings_dialog.set_transient_for(parent)
        self.use_default_switch.connect('notify::active', self.on_default_switched)
        self.custom_entry.connect('changed', self.on_custom_changed)
        self.settings_dialog.connect('destroy', lambda x: self.settings_dialog.destroy())

    def create_setting(self, item):
        setting = SettingRow(item)
        return setting.get_widget()

    def run(self):
        self.settings_dialog.show()

    def on_custom_changed(self, entry):
        if self.active_item.validate(entry.get_text()):
            entry.get_style_context().remove_class('warning')
            self.active_item.props.value = entry.get_text().strip()
        else:
            entry.get_style_context().add_class('warning')

    def on_default_switched(self, switch, param):
        self.custom_entry.set_sensitive(not switch.get_active())
        if not switch.get_active():
            self.custom_entry.set_text(self.active_item.props.value)
        else:
            settings.Settings.reset(self.active_item.props.key)

    def on_row_selected(self, listbox, row):
        if row:
            item = row.item
            self.active_item = row.item
            value_now = settings.get_string(item.key)
            default_value = item.info['default'].get_string()
            self.summary_lbl.set_text(item.info.get('summary', '...'))
            self.description_lbl.set_text(item.info.get('description', '...'))
            self.default_lbl.set_text('"{}"'.format(default_value))
            self.value_lbl.set_text('"{}"'.format(value_now))

            self.use_default_switch.set_active(value_now == default_value)
            if value_now != default_value:
                self.custom_entry.set_text(value_now)

