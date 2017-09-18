from __future__ import division

from datetime import datetime

import cairo
from gi.repository import Gdk, Gtk, GObject
from mxdc.beamline.mx import IBeamline
from mxdc.utils.automounter import ContainerCoords
from mxdc.utils.log import get_module_logger
from twisted.python.components import globalRegistry
_logger = get_module_logger(__name__)


class DewarLayout(object):
    """Objects with manage the layout of container and samples with the automounter dewar"""

    def __init__(self, data=None):
        # Defaults
        self.max_width = 30
        self.max_height = 30
        self.width = self.height = 200
        self.radius = 30
        self.pin_size = 10
        self.aspect_ratio = 1.0
        self.base_params = {}
        self.parameters = {}
        self.update(data)

    def update(self, data):
        if data:
            self.base_params = {
                loc: (ContainerCoords[kind] + center, kind in ['puck', 'basket']) for (loc, kind), center in
            data.items()
            }
            # maximum extents of container locations in units of radius
            self.max_width = max(
                [coords[:, 0].max() for coords, kind in self.base_params.values()]
            ) + min(
                [coords[:, 0].min() for coords, kind in self.base_params.values()]
            )
            self.max_height = max(
                [coords[:, 1].max() for coords, kind in self.base_params.values()]
            ) + min(
                [coords[:, 1].min() for coords, kind in self.base_params.values()]
            )
            self.aspect_ratio = self.max_height / self.max_width
            self.scale(self.width, self.height)
        else:
            self.base_params = {}

    def scale(self, width, height):
        """scale the parameters according to the width and height of the widget"""
        self.width = width
        self.height = height
        if self.aspect_ratio < self.height / self.width:
            ew = self.width - width / 20
            eh = ew * self.aspect_ratio
        else:
            eh = self.height - height / 20
            ew = eh / self.aspect_ratio

        xmargin = 0.5 * (self.width - ew)
        ymargin = 0.5 * (self.height - eh)

        self.radius = ew / 12.
        self.pin_size = ew / 62.0
        self.parameters = {
            loc: (spec[0] * ew + (xmargin, ymargin), spec[1])
            for loc, spec in self.base_params.items()
        }

OWN_ALPHA = {
    True: 1.0,
    False: 0.25
}

def _text_col(col, alpha):
    br = 0.241 * col['red']**2 + 0.691 * col['green']**2 + 0.068 * col['blue']**2
    return (0.0, 0.0, 0.0, alpha) if br > 0.5 else  (1.0, 1.0, 1.0, alpha)


class DewarController(GObject.GObject):
    class State(object):
        (
            EMPTY,
            GOOD,
            UNKNOWN,
            MOUNTED,
            JAMMED,
            NONE
        ) = range(6)

    Color = {
        State.UNKNOWN: {'red': 1.0, 'green': 1.0, 'blue': 1.0},
        State.EMPTY: {'red': 0.2, 'green': 0.2, 'blue': 0.2},
        State.JAMMED: {'red': 1.0, 'green': 0., 'blue': 0.0},
        State.MOUNTED: {'red': 0.5, 'green': 0, 'blue': 0.5},
        State.NONE: {'red': 1.0, 'green': 1.0, 'blue': 1.0},
        State.GOOD: {'red': 0.0, 'green': 0.5, 'blue': 0.0},
    }
    StateLabel = {
        State.UNKNOWN: "Unknown",
        State.EMPTY: "Empty",
        State.JAMMED: "Jammed!",
        State.MOUNTED: "Mounted",
        State.NONE: "...",
        State.GOOD: "Good"
    }

    __gsignals__ = {
        'selected': (GObject.SignalFlags.RUN_FIRST, None,
                     (str,)),
    }

    def __init__(self, widget, store):
        super(DewarController, self).__init__()

        self.widget = widget
        self.store = store
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.setup()
        self.messages = []

        self.layout = DewarLayout()

        self.beamline.automounter.connect('port-state', self.on_port_state)
        self.beamline.automounter.connect('layout', self.on_dewar_layout)
        self.beamline.automounter.connect('message', self.on_state_changed)
        self.beamline.automounter.connect('status', self.on_state_changed)
        self.beamline.automounter.connect('active', self.on_state_changed)
        self.beamline.automounter.connect('busy', self.on_state_changed)
        self.beamline.automounter.connect('health', self.on_state_changed)
        self.beamline.automounter.connect('enabled', self.on_state_changed)
        self.beamline.automounter.connect('preparing', self.on_state_changed)

    def setup(self):
        self.widget.sample_dewar_area.connect('draw', self.draw_dewar)
        self.widget.sample_dewar_area.connect('size-allocate', self.on_size_allocate)
        self.widget.sample_dewar_area.set_events(
            Gdk.EventMask.EXPOSURE_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.POINTER_MOTION_HINT_MASK | Gdk.EventMask.VISIBILITY_NOTIFY_MASK
        )
        self.widget.sample_dewar_area.connect('motion-notify-event', self.on_motion_notify)
        self.widget.sample_dewar_area.connect('button-press-event', self.on_press_event)

    def on_dewar_layout(self, obj, data):
        self.layout.update(data)
        self.widget.sample_dewar_area.queue_draw()

    def draw_dewar(self, widget, cr):
        cr.set_line_width(1)
        # background

        for loc, (coords, is_puck) in self.layout.parameters.items():
            cx, cy = coords[-1]
            if is_puck:
                cr.arc(cx, cy, self.layout.radius, 0, 2.0 * 3.14)
                #cr.set_source_rgba(.7, .7, .7, 1.)
                cr.set_source_rgba(0.5, 0.5, 0.5, 1.)
                cr.fill()
                cr.arc(cx, cy, self.layout.radius, 0, 2.0 * 3.14)
                cr.set_source_rgb(0, 0, 0)
                cr.stroke()
            else:
                for px, py in coords[1:-1]:
                    #cr.set_source_rgba(.7, .7, .7, 1.)
                    cr.set_source_rgba(0.5, 0.5, 0.5, 1.)
                    cr.arc(px, py, self.layout.pin_size + 5, 0, 2.0 * 3.14)
                    cr.fill()
        # pins
        alpha = 0.5
        for loc, (coords, is_puck) in self.layout.parameters.items():
            cx, cy = coords[-1]
            cr.select_font_face('Cantarell', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_source_rgb(0, 0, 1)
            xb, yb, w, h = cr.text_extents(loc)[:4]
            cr.move_to(cx - w / 2.0 - xb, cy - h / 2.0 - yb)
            cr.show_text(loc)
            cr.stroke()
            for i, (px, py) in enumerate(coords[1:-1]):
                port = '{}{}'.format(loc, i + 1)
                state = self.store.get_state(port)
                alpha = OWN_ALPHA[self.store.has_port(port)]
                rgb = self.Color.get(state, {'red': 1.0, 'green': 1.0, 'blue': 1.0})
                Gdk.cairo_set_source_rgba(cr, Gdk.RGBA(alpha=alpha, **rgb))
                cr.arc(px, py, self.layout.pin_size, 0, 2.0 * 3.14)
                cr.fill()
                cr.arc(px, py, self.layout.pin_size, 0, 2.0 * 3.14)
                cr.set_source_rgba(0.5, 0.5, 0.5, alpha)
                cr.stroke()
                label = '{}'.format(i + 1)
                xb, yb, w, h = cr.text_extents(label)[:4]
                cr.move_to(px - w / 2. - xb, py - h / 2. - yb)
                cr.set_source_rgba(*_text_col(rgb, alpha))
                cr.show_text(label)
                cr.stroke()

        if not self.layout.parameters:
            text = 'Layout Not available!'
            cx, cy = self.layout.width / 2., self.layout.height / 2.
            cr.set_source_rgb(0.5, 0.35, 0)
            cr.set_font_size(14)
            xb, yb, w, h = cr.text_extents(text)[:4]
            cr.move_to(cx - w / 2.0 - xb, cy - h / 2.0 - yb)
            cr.show_text(text)
            cr.stroke()

    def find_port(self, x, y):
        for loc, (coords, is_puck) in self.layout.parameters.items():
            distances = ((coords[1:-1] - (x, y)) ** 2).sum(axis=1) ** 0.5
            min_dist = distances.min()
            if min_dist > self.layout.pin_size: continue
            pos = distances.tolist().index(min_dist)
            port = '{}{}'.format(loc, pos + 1)
            if self.store.has_port(port):
                return port

    def on_size_allocate(self, obj, size):
        self.layout.scale(size.width, size.height)

    def on_port_state(self, *args, **kwargs):
        self.widget.sample_dewar_area.queue_draw()

    def on_motion_notify(self, widget, event):
        port = self.find_port(event.x, event.y)
        if port:
            state = self.store.get_state(port)
            label = self.StateLabel[state]
            event.window.set_cursor(Gdk.Cursor.new(Gdk.CursorType.HAND2))
            self.widget.hover_sample_lbl.set_markup('<b>{}</b>'.format(port))
            self.widget.hover_state_lbl.set_text(label)
        else:
            event.window.set_cursor(None)

    def on_press_event(self, widget, event):
        port = self.find_port(event.x, event.y)
        if self.store.get_state(port) not in [self.State.JAMMED, self.State.EMPTY]:
            self.emit('selected', port)

    def on_state_changed(self, obj, val):
        code, h_msg = self.beamline.automounter.health_state
        status = self.beamline.automounter.status_state
        message = self.beamline.automounter.message_state
        busy = (self.beamline.automounter.busy_state or self.beamline.automounter.preparing_state)
        enabled = self.beamline.automounter.enabled_state
        active = self.beamline.automounter.active_state

        # Do nothing if the state has not really changed
        _new_state = [code, h_msg, status, message, busy, enabled, active]
        if message.strip() == "":
            message = h_msg

        message = "<tt>{} - </tt><span color='blue'>{}</span>".format(datetime.now().strftime('%H:%M:%S'),
                                                                      message.strip())
        if not self.messages or message != self.messages[-1]:
            self.messages.append(message)

        if status == 'ready' and code < 2 and not busy:
            self.widget.automounter_command_box.set_sensitive(True)
        else:
            self.widget.automounter_command_box.set_sensitive(False)
        if len(self.messages) > 2:
            self.messages = self.messages[-2:]

        self.widget.automounter_status_lbl.set_markup(' ...\n'.join(self.messages))
