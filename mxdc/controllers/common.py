import logging
import operator

from gi.repository import Gtk, Gdk, Pango, GObject

from mxdc.widgets import dialogs, timer


def value_class(val, warning, error):
    if (val < warning < error) or (val > warning > error):
        return ""
    elif (warning < val < error) or (warning > val > error):
        return "dev-warning"
    elif (warning < error < val) or (warning > error > val):
        return "dev-error"
    else:
        return ""


class DeviceMonitor(object):
    def __init__(self, device, label, format='{:.3e}', signal='changed', warning=None, error=None):
        self.text = label
        self.device = device
        self.format = format
        self.warning = warning
        self.error = error
        self.device.connect(signal, self.on_signal)

    def on_signal(self, obj, *args):
        self.text.set_text(self.format.format(*args))
        style = self.text.get_style_context()
        if self.warning and self.error:
            style_class = value_class(args[0], self.warning, self.error)
            for name in ['dev-warning', 'dev-error']:
                if style_class == name:
                    style.add_class(name)
                else:
                    style.remove_class(name)


class PropertyMonitor(object):
    def __init__(self, device, property, widget, format='{:.3e}', warning=None, error=None):
        self.widget = widget
        self.device = device
        self.property = property
        self.format = format
        self.warning = warning
        self.error = error
        self.device.connect('notify::{}'.format(self.property), self.on_value_changed)
        self.device.bind_property(self.property, self.widget, 'text', 0, self.transform)

    def transform(self, obj, value):
        return self.format.format(value)

    def on_value_changed(self, *args, **kwargs):
        if self.warning and self.error:
            value = self.device.get_property(self.property)
            style = self.widget.get_style_context()
            style_class = value_class(value, self.warning, self.error)
            for name in ['dev-warning', 'dev-error']:
                if style_class == name:
                    style.add_class(name)
                else:
                    style.remove_class(name)


class ShutterSwitcher(object):
    def __init__(self, device, switch, reverse=False, openonly=False):
        self.device = device
        self.switch = switch
        self.reverse = reverse
        self.openonly = openonly
        self.device.connect('changed', self.on_state_change)
        self.switch.connect('notify::active', self.on_shutter_activated)

    def on_state_change(self, obj, state):
        self.switch.set_state(operator.xor(state, self.reverse))
        if self.openonly:
            self.switch.set_sensitive(not state)

    def on_shutter_activated(self, obj, param):
        state = self.switch.get_active()
        if operator.xor(state, self.reverse):
            self.device.open()
        else:
            self.device.close()


class ScaleMonitor(object):
    def __init__(self, scale, device, minimum=0.0, maximum=100.0):
        self.scale = scale
        self.device = device
        self.minimum = minimum
        self.maximum = maximum
        self.in_progress = False
        self.adjustment = self.scale.get_adjustment()
        self.adjustment.connect('value-changed', self.on_value_set)
        self.device.connect('changed', self.on_update)

    def on_value_set(self, obj):
        if not self.in_progress:
            if hasattr(self.device, 'move_to'):
                self.device.move_to(self.adjustment.props.value)
            elif hasattr(self.device, 'set'):
                self.device.set(self.adjustment.props.value)

    def on_update(self, obj, val):
        self.in_progress = True
        self.adjustment.props.value = val
        self.in_progress = False


class ModeMonitor(object):
    def __init__(self, device, box, color_map, value_map, signal="changed", markup="<small><b>{}</b></small>"):
        self.box = box
        self.device = device
        self.color_map = color_map
        self.value_map = value_map
        self.markup = markup
        self.label = Gtk.Label('')
        self.box.add(self.label)
        self.device.connect(signal, self.on_signal)

    def on_signal(self, obj, state):
        self.label.set_markup(self.markup.format(state))

        color = Gdk.RGBA(alpha=1)
        color.parse(self.color_map.get(self.value_map.get(state, state), '#708090'))
        fg_color = Gdk.RGBA(alpha=1)
        fg_color.parse('#ffffff')
        self.box.override_background_color(Gtk.StateType.NORMAL, color)
        self.label.override_color(Gtk.StateType.NORMAL, fg_color)


class BoolMonitor(object):
    def __init__(self, device, entry, value_map, signal='changed', inverted=False):
        self.device = device
        self.entry = entry
        self.value_map = value_map
        self.inverted = inverted
        self.device.connect(signal, self.on_signal)

    def on_signal(self, obj, state):
        txt = self.value_map.get(state, str(state))
        self.entry.set_text(txt)
        style = self.entry.get_style_context()

        if state == self.inverted:
            style.add_class('state-active')
            style.remove_class('state-inactive')
        else:
            style.remove_class('state-active')
            style.add_class('state-inactive')


class AppNotifier(object):
    def __init__(self, label, revealer, button):
        self.label = label
        self.revealer = revealer
        self.close_button = button
        self.box = self.label.get_parent()
        self.close_button.connect('clicked', self.on_notifier_closed)
        self.timer_shown = False
        self.timer = timer.Timer()
        #self.box.pack_start(self.timer, False, False, 0)
        #self.box.show_all()

    def on_notifier_closed(self, button):
        self.close()

    def notify(self, message, level=Gtk.MessageType.INFO, important=False, duration=3, show_timer=False):
        """
        Display an in-app notification.
        @param message: Text to display
        @param level: Gtk.MessageType
        @param duration: Duration too display message in seconds. Ignored if 'important' is True
        @param important: Boolean, if True, the message stays on until closed manually
        @param show_timer: Boolean, if True, a timer will be shown
        @return:
        """
        if self.revealer.get_reveal_child():
            self.revealer.set_reveal_child(False)
        self.label.set_text(message)
        if show_timer:
            self.timer.start(duration)
            self.box.pack_start(self.timer, False, False, 3)
            self.timer.show()
            self.timer_shown = True
        self.revealer.set_reveal_child(True)
        if not important:
            GObject.timeout_add(1000 * duration, self.close)

    def close(self):
        self.revealer.set_reveal_child(False)
        if self.timer_shown:
            self.box.remove(self.timer)
            self.timer_shown = False


class ScriptMonitor(object):
    def __init__(self, btn, script, spinner=None, status=None, confirm=False, msg=""):
        self.script = script
        self.btn = btn
        self.confirm = confirm
        self.warning_text = msg
        self.spinner = spinner

        self.script.connect('enabled', self.do_enabled)
        self.btn.connect('clicked', self.do_clicked)

    def do_clicked(self, widget):
        if not self.btn.get_active():
            return
        if self.confirm and not self.script.is_active():
            response = dialogs.warning(self.script.description, self.warning_text,
                                       buttons=(('Cancel', Gtk.ButtonsType.CANCEL), ('Proceed', Gtk.ButtonsType.OK)))
            if response == Gtk.ButtonsType.OK:
                self.script.start()
        elif not self.script.is_active():
            self.script.start()

    def do_enabled(self, obj, state):
        if state:
            self.btn.set_sensitive(True)
        else:
            self.btn.set_sensitive(False)


class GUIHandler(logging.Handler):
    def __init__(self, viewer):
        logging.Handler.__init__(self)
        self.viewer = viewer

    def emit(self, record):
        GObject.idle_add(self.viewer.add_text, self.format(record), record.levelno)


class StatusMonitor(object):
    def __init__(self, label, spinner, devices=()):
        self.devices = []
        self.label = label
        self.spinner = spinner
        self.message = ''
        for dev in devices:
            self.add(dev)

    def add(self, device):
        self.devices.append(device)
        device.connect('busy', self.on_state)
        device.connect('message', self.on_message)

    def on_message(self, dev, message):
        """ Set the message directly if spinner is busy otherwise set to blank"""
        self.message = message
        if self.spinner.props.active:
            self.label.set_markup('{}'.format(message))
        else:
            self.label.set_text('')

    def on_state(self, dev, state):
        if any(dev.is_busy() for dev in self.devices):
            self.spinner.start()
            self.label.set_markup('{}'.format(self.message))
        else:
            self.spinner.stop()
            self.label.set_text('')


class LogMonitor(object):
    def __init__(self, log_box, size=5000, font='Monospace 8'):
        self.buffer_size = size
        self.scroll_win = log_box
        self.view = log_box.get_child()
        self.text_buffer = self.view.get_buffer()
        self.view.set_editable(False)
        pango_font = Pango.FontDescription(font)
        self.view.modify_font(pango_font)
        self.wrap_mode = Gtk.WrapMode.WORD
        self.prefix = ''
        color_chart = {
            logging.INFO: 'Black',
            logging.CRITICAL: 'Red',
            logging.DEBUG: 'Blue',
            logging.ERROR: 'Red',
            logging.WARNING: 'Magenta',
        }
        self.tags = {}
        for key, v in color_chart.items():
            self.tags[key] = self.text_buffer.create_tag(foreground=v)
        self.view.connect('size-allocate', self.content_changed)

    def content_changed(self, widget, event, data=None):
        adj = self.scroll_win.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    def set_prefix(self, txt):
        self.prefix = txt

    def clear(self):
        self.text_buffer.delete(self.text_buffer.get_start_iter(), self.text_buffer.get_end_iter())

    def add_text(self, text, level=logging.INFO):
        linecount = self.text_buffer.get_line_count()
        if linecount > self.buffer_size:
            start_iter = self.text_buffer.get_start_iter()
            end_iter = self.text_buffer.get_start_iter()
            end_iter.forward_lines(10)
            self.text_buffer.delete(start_iter, end_iter)

        _iter = self.text_buffer.get_end_iter()
        tag = self.tags[level]
        self.text_buffer.insert_with_tags(_iter, "%s%s\n" % (self.prefix, text), tag)
        _iter = self.text_buffer.get_end_iter()
        # self.view.scroll_to_iter(_iter, 0, True, 0.5, 0.5)


class Tuner(object):
    def __init__(self, tuner, tune_up_btn, tune_down_btn, reset_btn=None, repeat_interval=100):
        self.tuner = tuner
        self.tune_up_btn = tune_up_btn
        self.tune_down_btn = tune_down_btn
        self.reset_btn = reset_btn
        self.repeat_interval = repeat_interval
        self.tune_func = None

        self.tune_up_btn.connect('button-press-event', self.on_tune_up)
        self.tune_down_btn.connect('button-press-event', self.on_tune_down)
        self.tune_up_btn.connect('button-release-event', self.cancel_tuning)
        self.tune_down_btn.connect('button-release-event', self.cancel_tuning)

        if self.reset_btn:
            self.reset_btn.connect('clicked', lambda x: tuner.reset())

    def repeat_tuning(self):
        if self.tune_func:
            self.tune_func()
            return True

    def on_tune_up(self, button, event):
        if event.button == 1:
            self.tune_func = self.tuner.tune_up
            self.tuner.tune_up()
            GObject.timeout_add(self.repeat_interval, self.repeat_tuning)

    def on_tune_down(self, button, event):
        if event.button == 1:
            self.tune_func = self.tuner.tune_down
            self.tuner.tune_down()
            GObject.timeout_add(self.repeat_interval, self.repeat_tuning)

    def cancel_tuning(self, *args, **kwargs):
        self.tune_func = None
