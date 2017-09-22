from mxdc.utils.misc import lighten_color
from diagnostics import MSG_COLORS, MSG_ICONS
from dialogs import warning

from mxdc.utils import gui
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import GdkPixbuf
from gi.repository import Gdk
from gi.repository import cairo

import os
import time

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

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
        self.device.connect('changed', self.on_value_changed)
        self.device.connect('active', self.on_active_changed)
        self.device.connect('health', self.on_health_changed)
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

    def on_health_changed(self, obj, health):
        state, _ = health
        if state == 0:
            self.entry.set_sensitive(True)
        else:
            self.entry.set_sensitive(False)

    def on_value_changed(self, obj, val):
        if val in self.values:
            self.entry.set_active(self.values[val])
        return True

    def on_active_changed(self, obj, state):
        if state:
            self.entry.set_sensitive(True)
        else:
            self.entry.set_sensitive(False)


class ActiveEntry(Gtk.Box, gui.BuilderMixin):
    gui_roots = {
        'data/active_entry': ['active_entry']
    }

    def __init__(self, device, label=None, fmt="%g", width=10):
        super(ActiveEntry, self).__init__(orientation=Gtk.Orientation.HORIZONTAL)

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
        self.surface = None

        self.setup_gui()
        self.build_gui()

    def build_gui(self):
        self.sizegroup_h = Gtk.SizeGroup(Gtk.SizeGroupMode.HORIZONTAL)
        self.pack_start(self.active_entry, True, True, 0)

        # signals and parameters
        self.device.connect('changed', self._on_value_changed)
        self.device.connect('active', self._on_active_changed)
        self.device.connect('health', self._on_health_changed)
        self.action_btn.connect('clicked', self._on_activate)
        self.entry.connect('icon-press', self._on_activate)
        self.entry.connect('activate', self._on_activate)
        self.label.set_text(self.name)

    def set_feedback(self, val):
        text = self.number_format % val
        if len(text) > self.width:
            text = "##.##"
        self.fbk_label.set_text('%8s' % (text,))

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
        except ValueError:
            target = feedback
        self.set_target(target)
        return target

    def _on_icon_activate(self, widget, pos, event):
        if pos == Gtk.EntryIconPosition.SECONDARY:
            self._on_activate(widget)

    def _on_health_changed(self, obj, health):
        state, _ = health
        style = self.fbk_label.get_style_context()
        if state == 0:
            self.action_icon.set_from_icon_name("media-playback-start-symbolic",Gtk.IconSize.BUTTON)
            self._set_active(True)
            style.remove_class('dev-error')
            style.remove_class('dev-warning')
        else:
            cls =  "dev-warning" if (state | 16) == state else "dev-error"
            self.action_icon.set_from_stock('gtk-dialog-warning', Gtk.IconSize.BUTTON)
            self._set_active(False)
            style.add_class(cls)


    def get_fraction(self, val):
        return 0.0

    def _on_value_changed(self, obj, val):
        if time.time() - self._last_signal > 0.1:
            self.set_feedback(val)
            self._last_signal = time.time()
        if self._first_change:
            self._first_change = False
        return True

    def _on_activate(self, obj, data=None, event=None):
        if self.action_active:
            if self.running:
                self.stop()
            else:
                self.apply()
        return True

    def _set_active(self, state):
        self.action_active = state
        if state:
            self.entry.set_sensitive(True)
            # self._action_btn.set_sensitive(True)
        else:
            self.entry.set_sensitive(False)
            # self._action_btn.set_sensitive(False)

    def _on_active_changed(self, obj, state):
        self._set_active(state)


class MotorEntry(ActiveEntry):
    def __init__(self, mtr, label=None, fmt="%0.3f", width=8):
        super(MotorEntry, self).__init__(mtr, label=label, fmt=fmt, width=width)
        self._set_active(False)
        self.device.connect('busy', self._on_motion_changed)
        self.device.connect('target', self._on_target_changed)
        self.device.connect('changed', self._on_progress)

        self._animation = GdkPixbuf.PixbufAnimation.new_from_file(
            os.path.join(os.path.dirname(__file__), 'data/active_stop.gif')
        )

    def get_fraction(self, val):
        if hasattr(self, 'current') and hasattr(self, 'target'):
            pct = 0.0 if self.target == self.current else float(val - self.current) / (self.target - self.current)
        else:
            pct = 0.0
        return pct

    def stop(self):
        self.device.stop()
        self.action_icon.set_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)

    def _on_motion_changed(self, obj, motion):
        style = self.fbk_label.get_style_context()
        if motion:
            self.running = True
            self.action_icon.set_from_animation(self._animation)
            style.add_class('dev-active')
        else:
            self.running = False
            self.action_icon.set_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
            style.remove_class('dev-active')
        self.set_feedback(self.device.get_position())
        return True

    def _on_target_changed(self, obj, targets):
        self.set_target(targets[-1])
        return True

    def _on_progress(self, obj, val):
        #self.entry.set_progress_fraction(self.get_fraction(val))
        pass


class CryojetWidget(Gtk.Alignment):
    def __init__(self, cryojet):
        super(CryojetWidget, self).__init__()
        self.set(0.5, 0.5, 1, 1)
        self.cryojet = cryojet
        self._xml = gui.GUIFile(os.path.join(DATA_DIR, 'cryo_widget'),
                                'cryo_widget')
        self.cryo_widget = self._xml.get_widget('cryo_widget')
        self.add(self.cryo_widget)
        self.noz_img.set_from_file(os.path.join(DATA_DIR, 'icons', 'cryojet_out.png'))

        # layout the gauge section
        self.level_gauge = Gauge(0, 100, 6, 4)
        self.level_gauge.set_property('label', "LN%s Level" % (u"\u2082"))
        self.level_gauge.set_property('units', "[%]")
        self.level_gauge.set_property('low', 20.0)
        self.level_frame.add(self.level_gauge)
        self.cryojet.level.connect('changed', self._on_level)

        # Status section
        tbl_data = {
            'temp': (0, self.cryojet.temperature),
            'smpl': (1, self.cryojet.sample_flow),
            'shld': (2, self.cryojet.shield_flow),
        }
        for v in tbl_data.values():
            lb = ActiveLabel(v[1])
            lb.set_alignment(0.5, 0.5)
            self.status_table.attach(lb, 1, 2, v[0], v[0] + 1)

        self.duration_entry.set_alignment(0.5)
        self.start_anneal_btn.connect('clicked', self._start_anneal)
        self.stop_anneal_btn.connect('clicked', self._stop_anneal)
        self._restore_anneal_id = None
        self._progress_id = None
        self._annealed_time = 0
        self.stop_anneal_btn.set_sensitive(False)
        self.retract_btn.connect('clicked', lambda x: self.cryojet.nozzle.open())
        self.restore_btn.connect('clicked', lambda x: self.cryojet.nozzle.close())
        self.cryojet.nozzle.connect('changed', self._on_nozzle_change)

    def __getattr__(self, key):
        try:
            return super(CryojetWidget).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)

    def _on_level(self, obj, val):
        self.level_gauge.value = val / 10.0
        return False

    def _on_nozzle_change(self, obj, state):
        if not state:
            self.noz_img.set_from_file(os.path.join(DATA_DIR, 'icons', 'cryojet_in.png'))
        else:
            self.noz_img.set_from_file(os.path.join(DATA_DIR, 'icons', 'cryojet_out.png'))

    def _on_status(self, obj, val):
        self.status.set_text('%s' % val)
        return False

    def _start_anneal(self, obj=None):
        try:
            duration = float(self.duration_entry.get_text())
        except:
            self.duration_entry.set_text('0.0')
            return
        msg1 = 'This procedure may damage your sample'
        msg2 = 'Flow control annealing will turn off the cold stream for the specified '
        msg2 += 'duration of <b>"%0.1f"</b> seconds. The outer dry nitrogen shroud remains on to protect the crystal ' % duration
        msg2 += 'from icing. However this procedure may damage the sample.\n\n'
        msg2 += 'Are you sure you want to continue?'

        response = warning(msg1, msg2, buttons=(('Cancel', Gtk.ButtonsType.CANCEL), ('Anneal', Gtk.ButtonsType.OK)))
        if response == Gtk.ButtonsType.OK:
            self.start_anneal_btn.set_sensitive(False)
            self.stop_anneal_btn.set_sensitive(True)
            self._annealed_time = 0
            self.cryojet.stop_flow()
            # dur = max(0.0, (duration-0.5*1000))
            self._restore_anneal_id = GObject.timeout_add(int(duration * 1000), self._stop_anneal)
            self._progress_id = GObject.timeout_add(1000, self._update_progress, duration)

    def _stop_anneal(self, obj=None):
        self.cryojet.resume_flow()
        self.start_anneal_btn.set_sensitive(True)
        self.stop_anneal_btn.set_sensitive(False)
        self.anneal_prog.set_fraction(0.0)
        self.anneal_prog.set_text('')
        if self._restore_anneal_id:
            GObject.source_remove(self._restore_anneal_id)
            self._restore_anneal_id = None
        if self._progress_id:
            GObject.source_remove(self._progress_id)
            self._progress_id = None
        return False

    def _update_progress(self, duration):
        if self._annealed_time < duration:
            self._annealed_time += 1
            self.anneal_prog.set_fraction(self._annealed_time / duration)
            self.anneal_prog.set_text('%0.1f sec' % self._annealed_time)
            return True
        else:
            return False
