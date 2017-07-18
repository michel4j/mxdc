import logging
import operator

from gi.repository import Gtk, Gdk, Pango, GObject
from mxdc.widgets import dialogs


def value_color(val, warning, error):
    if (val < warning < error) or (val > warning > error):
        return Gdk.color_parse("#204A87")
    elif (warning < val < error) or (warning > val > error):
        return Gdk.color_parse("#CE5C00")
    elif (warning < error < val) or (warning > error > val):
        return Gdk.color_parse("#A40000")
    else:
        return Gdk.color_parse("#204A87")


class DeviceMonitor(object):
    def __init__(self, device, label, format='{:.3e}', signal='changed', warning=None, error=None):
        self.label = label
        self.device = device
        self.format = format
        self.warning = warning
        self.error = error
        self.device.connect(signal, self.on_signal)

    def on_signal(self, obj, *args):
        self.label.set_markup(self.format.format(*args))
        if self.warning and self.error:
            col = value_color(args[0], self.warning, self.error)
            self.label.modify_fg(Gtk.StateType.NORMAL, col)


class ShutterSwitcher(object):
    def __init__(self, device, switch, reverse=False):
        self.device = device
        self.switch = switch
        self.reverse = reverse
        self.device.connect('changed', self.on_state_change)
        self.switch.connect('notify::active', self.on_shutter_activated)

    def on_state_change(self, obj, state):
        self.switch.set_state(operator.xor(state, self.reverse))

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

    def on_value_set(self, obj):
        if not self.in_progress:
            if hasattr(self.device, 'move_to'):
                self.device.move_to(self.scale.props.value)
            elif hasattr(self.device, 'set'):
                self.device.set(self.scale.props.value)

    def on_update(self, obj, val):
        self.in_progress = True
        self.scale.props.value = val
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
            logging.WARNING: 'Orange',
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
        #self.view.scroll_to_iter(_iter, 0, True, 0.5, 0.5)

