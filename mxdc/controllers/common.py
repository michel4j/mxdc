import logging
import operator
import subprocess
import os

import mxdc.beamlines
from mxdc.utils import misc, log
from pathlib import Path
from gi.repository import Gtk, Pango, GLib
from mxdc.widgets import timer, status


logger = log.get_module_logger(__name__)

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
        if isinstance(self.format, str):
            display_text = self.format.format(*args)
        elif callable(self.format):
            display_text = self.format(*args)
        else:
            display_text = args[0]

        self.text.set_text(display_text)
        style = self.text.get_style_context()
        if self.warning and self.error:
            style_class = value_class(args[0], self.warning, self.error)
            for name in ['dev-warning', 'dev-error']:
                if style_class == name:
                    style.add_class(name)
                else:
                    style.remove_class(name)


class PropertyMonitor(object):
    def __init__(self, device, property, widget, format='{:.3e}', uri=None, warning=None, error=None):
        self.widget = widget
        self.device = device
        self.property = property
        self.format = format
        self.warning = warning
        self.uri = uri
        self.error = error
        self.device.connect('notify::{}'.format(self.property), self.on_value_changed)
        if isinstance(widget, (Gtk.Label, Gtk.Button)):
            self.device.bind_property(self.property, self.widget, 'label', 0, self.transform)
        else:
            self.device.bind_property(self.property, self.widget, 'text', 0, self.transform)

        if self.uri and isinstance(widget, Gtk.LinkButton):
            self.widget.set_uri(self.uri)

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
        self.dev_link = self.device.connect('changed', self.on_state_change)
        self.sw_link = self.switch.connect('notify::active', self.on_shutter_activated)

    def watch(self):
        self.switch.handler_unblock(self.sw_link)

    def unwatch(self):
        self.switch.handler_block(self.sw_link)

    def on_state_change(self, obj, state):
        self.unwatch()
        self.switch.set_state(operator.xor(state, self.reverse))
        self.watch()

    def on_shutter_activated(self, obj, param):
        state = self.switch.get_active()
        if operator.xor(state, self.reverse):
            self.device.open()
        elif not self.openonly:
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


class ModeMonitor(object):

    def __init__(self, device, entry, signal='activity'):
        self.device = device
        self.entry = entry
        self.device.connect(signal, self.on_signal)
        self.device.connect('busy', self.on_busy)
        self.activity = ''

    def on_signal(self, obj, state):
        self.activity = state.upper()
        style = self.entry.get_style_context()
        for name in style.list_classes():
            if name.startswith('activity-'):
                style.remove_class(name)
        style.add_class(f'activity-{state}')
        self.entry.set_text(self.activity)

    def on_busy(self, obj, busy):
        if busy:
            self.entry.set_text('BUSY')
        else:
            self.entry.set_text(self.activity)


class AppNotifier(object):
    def __init__(self, label, revealer, button):
        self.label = label
        self.revealer = revealer
        self.close_button = button
        self.box = self.label.get_parent()
        self.close_button.connect('clicked', self.on_notifier_closed)
        self.timer_shown = False
        self.timer = timer.Timer()
        # self.box.pack_start(self.timer, False, False, 0)
        # self.box.show_all()

    def on_notifier_closed(self, button):
        self.close()

    def notify(self, message, level=Gtk.MessageType.INFO, important=False, duration=3, show_timer=False):
        """
        Display an in-app notification.
        :param message: Text to display
        :param level: Gtk.MessageType
        :param duration: Duration too display message in seconds. Ignored if 'important' is True
        :param important: Boolean, if True, the message stays on until closed manually
        :param show_timer: Boolean, if True, a timer will be shown
        :return:
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
            GLib.timeout_add(1000 * duration, self.close)

    def close(self):
        self.revealer.set_reveal_child(False)
        if self.timer_shown:
            self.box.remove(self.timer)
            self.timer_shown = False


class GUIHandler(logging.Handler):
    def __init__(self, viewer):
        logging.Handler.__init__(self)
        self.viewer = viewer

    def emit(self, record):
        GLib.idle_add(self.viewer.add_text, self.format(record), record.levelno)


class StatusMonitor(object):
    def __init__(self, widget, devices=()):
        self.devices = set()
        self.spinner = widget.spinner
        self.text = widget.status_lbl
        for dev in devices:
            self.add(dev)

    def add(self, *args):
        for device in args:
            self.devices.add(device)
            device.connect('message', self.on_message)
            device.connect('busy', self.check_busy)

    def on_message(self, device, message):
        """ Set the message directly if spinner is busy otherwise set to blank"""
        message = message if message else 'Busy ...'
        self.text.set_text(f'{device.name} - {message}')
        self.check_busy()

    def check_busy(self, *args, **kwargs):
        if any(dev.is_busy() for dev in self.devices):
            self.spinner.start()
        else:
            self.spinner.stop()
            self.text.set_text('')


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
            logging.CRITICAL: '#d2413a',
            logging.DEBUG: '#3a7ca8',
            logging.ERROR: '#D2413A',
            logging.WARNING: '#e98b39',
        }
        self.tags = {}
        for key, v in list(color_chart.items()):
            self.tags[key] = self.text_buffer.create_tag(foreground=v)
        self.view.connect('size-allocate', self.content_changed)

    def content_changed(self, widget, event, data=None):
        adj = self.scroll_win.get_vadjustment()
        #adj.set_value(adj.get_upper() - adj.get_page_size())

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

        loc = self.text_buffer.get_end_iter()
        if level == logging.INFO:
            self.text_buffer.insert(loc, f"{self.prefix}{text}\n")
        else:
            tag = self.tags[level]
            self.text_buffer.insert_with_tags(loc, f"{self.prefix}{text}\n", tag)


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
            GLib.timeout_add(self.repeat_interval, self.repeat_tuning)

    def on_tune_down(self, button, event):
        if event.button == 1:
            self.tune_func = self.tuner.tune_down
            self.tuner.tune_down()
            GLib.timeout_add(self.repeat_interval, self.repeat_tuning)

    def cancel_tuning(self, *args, **kwargs):
        self.tune_func = None



class DataDirectory:
    def __init__(self, button: Gtk.Button, label: Gtk.Label):
        self.button = button
        self.label = label
        self.directory = Path(misc.get_project_home())
        self.label.set_text(str(self.directory).replace(misc.get_project_home(), '~'))
        self.button.connect('clicked', self.open_terminal)

    def update_view(self):
        if self.directory.exists():
            os.chdir(self.directory)
            self.label.set_text(str(self.directory).replace(misc.get_project_home(), '~'))
            return False
        else:
            return True

    def get_directory(self):
        return self.directory

    def set_directory(self, path):
        self.directory = Path(str(path))
        GLib.timeout_add(500, self.update_view)

    def open_terminal(self, btn):
        commands = [
            'gnome-terminal',
            '--geometry=132x24',
            '--working-directory={}'.format(self.directory),
        ]
        subprocess.Popen(commands)


class DataStatusController:
    def __init__(self, beamline: mxdc.beamlines.Beamline, view: status.DataStatus):
        self.view = view
        self.config = [
            (beamline.goniometer.omega, self.view.omega_fbk, '{:0.1f}°'),
            (beamline.energy, self.view.energy_fbk, '{:0.3f} keV'),
            (beamline.attenuator, self.view.attenuation_fbk, '{:0.0f} %'),
            (beamline.maxres, self.view.max_res_fbk, '{:0.2f} Å'),
            (beamline.aperture, self.view.aperture_fbk, '{:0.0f} µm'),
            (beamline.two_theta, self.view.two_theta_fbk, '{:0.0f}°'),
        ]
        self.monitors = [
            DeviceMonitor(dev, lbl, fmt)
            for (dev, lbl, fmt) in self.config
        ]
        self.data_folder = DataDirectory(self.view.directory_btn, self.view.directory_fbk)

    def get_directory(self):
        return self.data_folder.get_directory()

    def set_directory(self, path):
        self.data_folder.set_directory(path)

