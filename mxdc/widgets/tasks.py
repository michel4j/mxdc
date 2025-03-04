import pprint
from contextlib import contextmanager
from enum import IntEnum, auto
from typing import Any

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from mxdc.conf import save_cache, load_cache
from mxdc.utils.datatools import StrategyType, Strategy, TaskType
from mxdc.utils.gui import Validator
from mxdc import Property, Object

ANALYSIS_DESCRIPTIONS = {
    "strategy": "Screening and Strategy Determination",
    "process": "Full Data Processing",
    "powder": "Powder Azimuthal Integration"
}


class HiddenWidget:
    def __init__(self):
        self.value = None

    def set_value(self, value):
        self.value = value

    def set_visible(self, visible):
        pass

    def set_sensitive(self, sensitive):
        pass

    def get_value(self):
        return self.value


class FormField:
    def __init__(self, name, widget: Any, fmt: str = None, validator: callable = None):
        self.name = name
        self.widget = widget
        self.validator = validator
        self.text_format = fmt
        self.handler_id = None
        self.callbacks = set()
        self.monitor_changes()

    def disable(self):
        """
        Disable the form field
        :return:
        """

        self.widget.set_visible(False)
        self.widget.set_sensitive(False)

    def enable(self):
        """
        Enable the form field
        :return:
        """
        self.widget.set_sensitive(True)
        self.widget.set_visible(True)

    def connect(self, callback: callable):
        """
        Connect a callback to the field
        :param callback: Callback function must take three arguments: field instance, name, value
        """
        self.callbacks.add(callback)

    def monitor_changes(self):
        if isinstance(self.widget, (Gtk.Switch, Gtk.CheckButton, Gtk.RadioButton)):
            self.handler_id = self.widget.connect('activate', self.on_changed)
        elif isinstance(self.widget, (Gtk.Entry, Gtk.ComboBox)):
            self.handler_id = self.widget.connect('changed', self.on_changed)
        elif isinstance(self.widget, (Gtk.SpinButton, Gtk.Scale)):
            self.handler_id = self.widget.connect('value-changed', self.on_changed)
        elif isinstance(self.widget, Gtk.TextView):
            buffer = self.widget.get_buffer()
            self.handler_id = buffer.connect('changed', self.on_changed)
        elif isinstance(self.widget, HiddenWidget):
            pass
        else:
            self.handler_id = self.widget.connect('focus-out-event', self.on_changed)

    def get_default(self) -> Any:
        """
        Get the default value from the validator
        """
        return self.validator(None) if self.validator else None

    def get_value(self):
        """
        Get the value contained in the GUI input widget and validate it
        """
        if isinstance(self.widget, (Gtk.Switch, Gtk.CheckButton, Gtk.RadioButton)):
            raw_value = self.widget.get_active()
        elif isinstance(self.widget, Gtk.Entry):
            raw_value = self.widget.get_text()
        elif isinstance(self.widget, Gtk.ComboBoxText):
            raw_value = self.widget.get_active_id()
        elif isinstance(self.widget, Gtk.ComboBox):
            raw_value = self.widget.get_active_id()
        elif isinstance(self.widget, Gtk.SpinButton):
            raw_value = self.widget.get_value()
        elif isinstance(self.widget, Gtk.Scale):
            raw_value = self.widget.get_value()
        elif isinstance(self.widget, Gtk.TextView):
            buffer = self.widget.get_buffer()
            raw_value = buffer.props.text
        elif isinstance(self.widget, HiddenWidget):
            raw_value = self.widget.get_value()
        else:
            raw_value = None

        return raw_value if not self.validator else self.validator(raw_value)

    def set_value(self, value, propagate: bool = True):
        """
         Validate and update the value of the GUI input widget
        :param value: proposed value
        :param propagate: If True, propagate the change to the callbacks
        """
        if propagate:
            self.set_raw_value(value)
        else:
            with self.ignore_changes():
                self.set_raw_value(value)

    def set_raw_value(self, value):
        """
        Validate and update the value of the GUI input widget
        :param value: proposed value
        """
        new_value = self.validator(value) if self.validator else value
        if isinstance(self.widget, (Gtk.Switch, Gtk.CheckButton, Gtk.RadioButton)):
            self.widget.set_active(new_value)
        elif isinstance(self.widget, Gtk.Entry):
            self.widget.set_text(self.text_format.format(new_value))
        elif isinstance(self.widget, Gtk.ComboBoxText):
            self.widget.set_active_id(str(new_value))
        elif isinstance(self.widget, Gtk.ComboBox):
            model = self.widget.get_model()
            for row in model:
                if row[0] == new_value:
                    break
            else:
                new_value = None
            self.widget.set_active_id(new_value)
        elif isinstance(self.widget, (Gtk.SpinButton, Gtk.Scale)):
            self.widget.set_value(new_value)
        elif isinstance(self.widget, Gtk.TextView):
            buffer = self.widget.get_buffer()
            buffer.set_text(new_value)
        elif isinstance(self.widget, HiddenWidget):
            self.widget.set_value(new_value)

    def on_changed(self, widget, *args):
        """
        Callback for the widget changed event
        :param widget: widget
        :param args: additional arguments
        """
        value = self.get_value()
        for callback in self.callbacks:
            callback(None, self, self.name, value)

    @contextmanager
    def ignore_changes(self):
        """
        Temporarily ignore changes to the widget
        """
        available = self.handler_id is not None
        if available:
            self.widget.handler_block(self.handler_id)
        try:
            yield available
        finally:
            if available:
                self.widget.handler_unblock(self.handler_id)


class Form:
    name: str
    fields: dict
    validators: dict
    initialized: bool = False

    def __init__(self, name, fields: list, persist: bool = True):
        """
        :param name: unique name of the form for persistence
        :param fields: dictionary mapping field name to field specifications
        :param persist:
        """
        self.name = name
        self.fields = {
            field.name: field for field in fields
        }
        self.persist = persist
        if self.persist:
            initial = load_cache(self.name)
            self.initialized = bool(initial)
        else:
            initial = {}
            self.initialized = False

        self.set_values(**initial, propagate=False)
        self.connect(self.on_change)

    def is_initialized(self):
        return self.initialized

    def connect(self, callback: callable):
        """
        Connect a callback to the form
        :param callback: Callback function must take four arguments: form, field instance, name, value
        """
        for field in self.fields.values():
            field.connect(callback)

    def get_field(self, name: str) -> FormField:
        """
        Get a field by name
        :param name: field name
        :return: FormField
        """
        return self.fields.get(name)

    def set_values(self, propagate: bool = False, **kwargs):
        for name, value in kwargs.items():
            if name in self.fields:
                self.fields[name].set_value(value, propagate=propagate)

    def get_values(self) -> dict:
        """
        Get the current values of the form fields
        :return: dictionary
        """
        return {
            name: field.get_value() for name, field in self.fields.items()
        }

    def disable(self, *fields):
        """
        Disable the specified fields

        :param fields: field names
        """
        for field in fields:
            if field in self.fields:
                self.fields[field].disable()

    def enable(self, *fields):
        """
        Enable the specified fields

        :param fields: field names
        """
        for field in fields:
            if field in self.fields:
                self.fields[field].enable()

    def save(self):
        """
        Save the form values to a persistent storage
        """
        save_cache(self.get_values(), self.name)

    def on_change(self, form, field, name, value):
        """
        Callback for the field changed event
        :param form: form instance
        :param field: field instance
        :param name: field name
        :param value: field value
        """
        if self.persist:
            self.save()


@Gtk.Template.from_resource('/org/gtk/mxdc/data/acquisition_form.ui')
class AcquisitionOptions(Gtk.Popover):
    __gtype_name__ = 'AcquisitionOptions'
    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    strategy_cbox = Gtk.Template.Child()
    delta_entry = Gtk.Template.Child()
    exposure_entry = Gtk.Template.Child()
    start_entry = Gtk.Template.Child()
    range_entry = Gtk.Template.Child()
    resolution_entry = Gtk.Template.Child()
    attenuation_entry = Gtk.Template.Child()
    use_strategy_opt = Gtk.Template.Child()

    skip_opt = Gtk.Template.Child()
    pause_opt = Gtk.Template.Child()
    save_btn = Gtk.Template.Child()
    cancel_btn = Gtk.Template.Child()

    form: Form

    def __init__(self, name: str, kind: TaskType, *args, **kwargs):
        """
        Acquisition options popover form
        :param name: name of the form
        :param kind: task type
        """
        super().__init__(*args, **kwargs)
        fields = [
            FormField(
                'strategy', self.strategy_cbox, fmt='{}', validator=Validator.Int(None, None, StrategyType.SINGLE)
            ),
            FormField('resolution', self.range_entry, fmt='{:0.4g}', validator=Validator.Float(0.5, 50, 1.5)),
            FormField('delta', self.delta_entry, fmt='{:0.3g}', validator=Validator.AngleFrac(0.001, 720, 1.)),
            FormField('range', self.resolution_entry, fmt='{:0.3g}', validator=Validator.Float(0.05, 10000, 1.)),
            FormField('start', self.start_entry, fmt='{:0.3g}', validator=Validator.Float(-360., 360., 0.)),
            FormField('wedge', HiddenWidget(), fmt='{:0.3g}', validator=Validator.Float(0.05, 720., 720.)),
            FormField('energy', HiddenWidget(), fmt='{:0.3g}', validator=Validator.Float(1.0, 25.0, 12.66)),
            FormField('distance', HiddenWidget(), fmt='{:0.1g}', validator=Validator.Float(50., 1000., 200)),
            FormField('exposure', self.exposure_entry, fmt='{:0.3g}', validator=Validator.Float(0.001, 720, 1.)),
            FormField('attenuation', self.attenuation_entry, fmt='{:0.3g}', validator=Validator.Float(0., 100, 0.0)),
            FormField('first', HiddenWidget(), fmt='{}', validator=Validator.Int(1, 10000, 1)),
            FormField('frames', HiddenWidget(), fmt='{}', validator=Validator.Int(1, 100000, 1)),
            FormField('use_strategy', self.use_strategy_opt, fmt='{}', validator=Validator.Bool(True)),
            FormField('skip_on_failure', self.skip_opt, fmt='{}', validator=Validator.Bool(True)),
            FormField('pause', self.pause_opt, fmt='{}', validator=Validator.Bool(False)),
        ]
        self.kind = kind
        self.set_strategy_options(kind == TaskType.SCREEN)
        self.form = Form(name, fields)
        self.cancel_btn.connect('clicked', lambda x: self.hide())
        self.save_btn.connect_after('clicked', self.on_save)
        if self.kind == TaskType.SCREEN:
            self.form.disable('use_strategy')

    def __getattr__(self, item):
        """
        Pass attribute access to the form if not overridden
        :param item:
        """
        return getattr(self.form, item)

    def on_save(self, widget):
        """
        Callback for the save button
        :param widget:
        :return:
        """
        self.emit('changed', self.form.get_values())
        self.hide()

    def set_strategy_options(self, screen=False):
        """
        Set the strategy options in the combobox
        :param screen: toggle screening mode
        """
        screening_types = [
            StrategyType.SINGLE, StrategyType.SCREEN_1, StrategyType.SCREEN_2,
            StrategyType.SCREEN_3, StrategyType.SCREEN_4,
        ]

        self.strategy_cbox.remove_all()
        for idx, params in Strategy.items():
            if screen == (idx in screening_types):
                self.strategy_cbox.append(f'{idx:d}', params['desc'])

    def get_values(self):
        values = self.form.get_values()
        values.update({
            "desc": Strategy[values['strategy']].get("desc", values['strategy']),
            'activity': Strategy[values['strategy']]['activity'],
        })
        return values


@Gtk.Template.from_resource('/org/gtk/mxdc/data/analysis_form.ui')
class AnalysisOptions(Gtk.Popover):
    __gtype_name__ = 'AnalysisOptions'
    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    method_cbox = Gtk.Template.Child()
    anomalous_opt = Gtk.Template.Child()
    min_score_entry = Gtk.Template.Child()

    skip_opt = Gtk.Template.Child()
    pause_opt = Gtk.Template.Child()
    save_btn = Gtk.Template.Child()
    cancel_btn = Gtk.Template.Child()

    form: Form

    def __init__(self, name: str, kind: TaskType, *args, **kwargs):
        """
        Analysis options popover form
        :param name: name of the form
        """
        super().__init__(*args, **kwargs)
        fields = [
            FormField('method', self.method_cbox, fmt='{}', validator=Validator.Literal('strategy', 'process', 'powder')),
            FormField('anomalous', self.anomalous_opt, fmt='{}', validator=Validator.Bool(False)),
            FormField('min_score', self.min_score_entry, fmt='{:0.2g}', validator=Validator.Float(0.0, 1.0, 0.1)),
            FormField('skip_on_failure', self.skip_opt, fmt='{}', validator=Validator.Bool(True)),
            FormField('pause', self.pause_opt, fmt='{}', validator=Validator.Bool(False)),
        ]
        self.kind = kind
        self.form = Form(name, fields)
        self.cancel_btn.connect('clicked', lambda x: self.hide())
        self.save_btn.connect_after('clicked', self.on_save)

    def __getattr__(self, item):
        return getattr(self.form, item)

    def on_save(self, widget):
        self.emit('changed', self.form.get_values())
        self.hide()

    def get_values(self):
        values = self.form.get_values()
        values.update({
            "desc": ANALYSIS_DESCRIPTIONS.get(values["method"], values['method'])
        })
        return values


@Gtk.Template.from_resource('/org/gtk/mxdc/data/centering_form.ui')
class CenteringOptions(Gtk.Popover):
    __gtype_name__ = 'CenteringOptions'
    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    method_cbox = Gtk.Template.Child()
    min_score_entry = Gtk.Template.Child()

    skip_opt = Gtk.Template.Child()
    pause_opt = Gtk.Template.Child()
    save_btn = Gtk.Template.Child()
    cancel_btn = Gtk.Template.Child()

    form: Form

    def __init__(self, name: str, kind: TaskType, *args, **kwargs):
        """
        Centering options popover form
        :param name: name of the form
        """
        super().__init__(*args, **kwargs)
        fields = [
            FormField(
                'method', self.method_cbox, fmt='{}',
                validator=Validator.Literal('loop', 'crystal', 'diffraction', 'capillary', default='loop')
            ),
            FormField('min_score', self.min_score_entry, fmt='{:0.2g}', validator=Validator.Float(0.0, 100.0, 0.50)),
            FormField('skip_on_failure', self.skip_opt, fmt='{}', validator=Validator.Bool(True)),
            FormField('pause', self.pause_opt, fmt='{}', validator=Validator.Bool(False)),
        ]
        self.kind = kind
        self.form = Form(name, fields)
        self.cancel_btn.connect('clicked', lambda x: self.hide())
        self.save_btn.connect_after('clicked', self.on_save)

    def __getattr__(self, item):
        return getattr(self.form, item)

    def on_save(self, widget):
        self.emit('changed', self.form.get_values())
        self.hide()


def format_markup(markup: str, options: dict) -> str:
    """
    Format a description string with the given options or return empty string if the markup is invalid
    :param markup: string format specification
    :param options: dictionary
    :return: str
    """
    try:
        return markup.format(**options)
    except KeyError:
        return ""


_ACQUISITION_DESCR = [
    "<b>{desc}</b>",
    "<b>{delta:0.4g}°</b> / <b>{exposure:0.2g}s</b>",
    "<b>{range}°</b> total, <b>{attenuation:0.1f}%</b> attenuation",
    "<b>{resolution:0.4g} Å</b> resolution"
]


class TaskItem(Object):
    Type = TaskType

    type = Property(type=int, default=Type.CENTER)
    active = Property(type=bool, default=False)
    name = Property(type=str, default="Task Name")
    options = Property(type=object)

    DESCRIPTIONS = {
        Type.CENTER: [
            "Auto-centering by <b>{method}</b>",
            "Minimum score=<b>{min_score}%</b>"],
        Type.ACQUIRE: _ACQUISITION_DESCR,
        Type.SCREEN: _ACQUISITION_DESCR,
        Type.ANALYSE: [
            "<b>{desc}</b>",
            "Anomalous=<b>{anomalous}</b>",
            "Minimum score=<b>{min_score:0.1f}</b>"
        ]
    }

    def __init__(self, name: str, **kwargs):
        """
        :param name: name of task
        :param kwargs: task properties to initialize
        """
        super().__init__()
        self.props.name = name
        self.set_properties(**kwargs)

    def set_active(self, active: bool):
        """
        Set the task active state
        :param active: active state
        """
        self.props.active = active

    def is_active(self):
        """
        Check if the task is active
        """
        return self.props.active

    def get_description(self) -> str:
        """
        Generate the description string for the task
        """
        descriptions = self.DESCRIPTIONS[self.type]
        if self.type == self.Type.ACQUIRE and self.props.options['use_strategy']:
            descriptions = [
                self.DESCRIPTIONS[self.type][0],
                "Using determined strategy!",
            ]

        return ", ".join(
            filter(None, [format_markup(line, self.props.options) for line in descriptions])
        )

    def get_parameters(self) -> dict:
        """
        Get the task parameters
        """
        return {
            'type': self.type,
            'active': self.active,
            'name': self.name,
            'description': self.get_description(),
            'options': {**self.props.options}
        }


TASK_OPTIONS = {
    TaskItem.Type.CENTER: CenteringOptions,
    TaskItem.Type.ACQUIRE: AcquisitionOptions,
    TaskItem.Type.SCREEN: AcquisitionOptions,
    TaskItem.Type.ANALYSE: AnalysisOptions
}


@Gtk.Template.from_resource('/org/gtk/mxdc/data/task_row.ui')
class TaskRow(Gtk.Box):
    __gtype_name__ = 'TaskRow'

    enable_btn = Gtk.Template.Child()
    name = Gtk.Template.Child()
    description = Gtk.Template.Child()
    task_box = Gtk.Template.Child()
    options_btn = Gtk.Template.Child()

    name_size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
    task: TaskItem

    def __init__(self, item: TaskItem):
        """
        Row widget for displaying task items
        :param item: task item
        """
        super().__init__()
        self.name_size_group.add_widget(self.name)
        self.form = TASK_OPTIONS[item.type](f"automation-{item.name}", item.type)
        self.form.connect("changed", self.on_form_saved)
        self.get_style_context().add_class('task-row')
        self.options_btn.set_popover(self.form)
        self.set_item(item)

    def set_item(self, task: TaskItem):
        self.task = task
        if self.form.is_initialized():
            self.task.props.options = self.form.get_values()
        else:
            self.form.set_values(**self.task.props.options, propagate=False)

        self.do_task_changed()
        self.enable_btn.set_active(task.active)
        self.task.bind_property('active', self.enable_btn, 'active', GObject.BindingFlags.BIDIRECTIONAL)
        self.task.bind_property('active', self.task_box, 'sensitive', GObject.BindingFlags.DEFAULT)
        self.task.connect('notify::options', self.do_task_changed)

    def do_task_changed(self, *args):
        self.name.set_markup(self.task.name)
        self.description.set_markup(self.task.get_description())

    def on_form_saved(self, *args):
        self.task.props.options = self.form.get_values()

