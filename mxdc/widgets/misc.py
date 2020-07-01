import time

from gi.repository import GdkPixbuf, Gtk

from mxdc.utils import gui


class ActiveMenu(Gtk.Box, gui.BuilderMixin):
    gui_roots = {
        'data/active_menu': ['active_menu']
    }

    def __init__(self, device, label=None, fmt="%g", width=10):
        super(ActiveMenu, self).__init__(orientation=Gtk.Orientation.HORIZONTAL)

        # initialize housekeeping
        self.device = device
        self.name = label or self.device.name
        self.name = self.name if not self.device.units else '{} ({})'.format(self.name, self.device.units)
        self.target = 0.0
        self.current = 0.0
        self._first_change = True
        self._last_signal = 0
        self.running = False
        self.action_active = True
        self.width = width
        self.number_format = fmt
        self.format = self.number_format
        self.values = {}
        self.setup_gui()
        self.build_gui()

    def build_gui(self):
        self.pack_start(self.active_menu, True, True, 0)

        # Generate list of values
        for i, value in enumerate(self.device.choices):
            self.entry.append_text(self.format % value)
            self.values[value] = i
        for r in self.entry.get_cells():
            r.set_alignment(0.5, 0.5)

        # signals and parameters
        self.device.connect('enabled', self.on_status)
        self.device.connect('changed', self.on_value)
        self.device.connect('active', self.on_status)
        self.device.connect('health', self.on_status)

        self.entry.connect('changed', self.on_activate)
        self.label.set_text(self.name)

    def on_activate(self, val):
        target = float(self.entry.get_active_text())
        self.device.set(target)

    def apply(self):
        target = self._get_target()
        if hasattr(self.device, 'move_to'):
            self.device.move_to(target)
        elif hasattr(self.device, 'set'):
            self.device.set(target)

    def on_value(self, obj, val):
        if val in self.values:
            self.entry.set_active(self.values[val])
        return True

    def on_status(self, obj, *args):
        enabled = self.device.is_enabled()
        active = self.device.is_active()
        healthy = self.device.is_healthy()
        self.set_sensitive(enabled and active and healthy)


class ActiveEntry(Gtk.Box, gui.BuilderMixin):
    gui_roots = {
        'data/active_entry': ['active_entry']
    }

    def __init__(self, device, label=None, fmt="%g", width=10):
        super(ActiveEntry, self).__init__(orientation=Gtk.Orientation.HORIZONTAL)

        # initialize housekeeping
        self._animation = GdkPixbuf.PixbufAnimation.new_from_resource(
            "/org/mxdc/data/active_stop.gif"
        )
        self.device = device
        self.name = label or self.device.name
        self.name = self.name if not self.device.units else '{} ({})'.format(self.name, self.device.units)
        self.target = 0.0
        self.current = 0.0
        self._first_change = True
        self._last_signal = 0
        self.running = False
        self.action_active = True
        self.width = width
        self.number_format = fmt
        self.format = self.number_format
        self.state_icon = "media-playback-start-symbolic"

        self.setup_gui()
        self.build_gui()

    def build_gui(self):
        self.sizegroup_h = Gtk.SizeGroup(Gtk.SizeGroupMode.HORIZONTAL)
        self.pack_start(self.active_entry, True, True, 0)

        # signals and parameters
        self.device.connect('changed', self.on_value)
        self.device.connect('active', self.on_status)
        self.device.connect('enabled', self.on_status)
        self.device.connect('health', self.on_status)
        self.device.connect('busy', self.on_status)

        self.action_btn.connect('clicked', self.on_activate)
        self.entry.connect('icon-press', self.on_activate)
        self.entry.connect('activate', self.on_activate)
        self.label.set_text(self.name)

    def set_feedback(self, val):
        text = self.number_format % val
        self.fbk_label.set_text(text)

    def set_target(self, val):
        text = self.number_format % val
        self.entry.set_text(text)
        self.target = val
        self.current = self.device.get_position()

    def stop(self):
        self.running = False

    def apply(self):
        target = self._get_target()
        if hasattr(self.device, 'move_to'):
            self.device.move_to(target)
        elif hasattr(self.device, 'set'):
            self.device.set(target)

    def _get_target(self):
        feedback = self.fbk_label.get_text()
        try:
            target = float(self.entry.get_text())
        except (ValueError, TypeError):
            target = float(feedback)
        self.set_target(target)
        return target

    def on_status(self, *args, **kwargs):
        health_status = self.device.get_state('health')
        if health_status:
            health = health_status[0]
        else:
            health = 0

        style = self.fbk_label.get_style_context()
        if self.device.is_healthy():
            style.remove_class('dev-error')
            style.remove_class('dev-warning')
        else:
            cls = "dev-warning" if (health | 16) == health else "dev-error"
            style.add_class(cls)

        if not self.device.is_active():
            self.state_icon = "network-wired-disconnected-symbolic"
            self.entry.set_sensitive(False)
            self.action_btn.set_sensitive(False)
        elif not self.device.is_healthy():
            self.state_icon = "dialog-warning-symbolic"
            self.entry.set_sensitive(False)
            self.action_btn.set_sensitive(False)
        elif not self.device.is_enabled():
            self.state_icon = "system-lock-screen-symbolic"
            self.entry.set_sensitive(False)
            self.action_btn.set_sensitive(False)
        else:
            self.state_icon = "media-playback-start-symbolic"
            self.entry.set_sensitive(True)
            self.action_btn.set_sensitive(True)

        if self.device.is_busy():
            self.action_btn.set_sensitive(True)
            self.action_icon.set_from_animation(self._animation)
            style.add_class('dev-active')
            self.running = True
        else:
            self.action_icon.set_from_icon_name(self.state_icon, Gtk.IconSize.BUTTON)
            style.remove_class('dev-active')
            self.running = False

    def on_value(self, obj, val):
        if time.time() - self._last_signal > 0.1:
            self.set_feedback(val)
            self._last_signal = time.time()
        if self._first_change:
            self._first_change = False
        return True

    def on_activate(self, obj, data=None, event=None):
        if self.action_active:
            if self.running:
                self.stop()
            else:
                self.apply()
        return True


class MotorEntry(ActiveEntry):
    def __init__(self, mtr, label=None, fmt="%0.3f", width=8):
        super(MotorEntry, self).__init__(mtr, label=label, fmt=fmt, width=width)
        self.device.connect('busy', self.on_busy)
        self.device.connect('target', self.on_target)

    def stop(self):
        self.device.stop()

    def on_busy(self, obj, motion):
        self.set_feedback(self.device.get_position())

    def on_target(self, obj, previous, current):
        self.set_target(current)
