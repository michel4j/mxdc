from __future__ import division

from datetime import datetime

from gi.repository import Gdk, GObject
from mxdc.beamlines.mx import IBeamline
from mxdc.utils.automounter import Port, PortColors
from mxdc.utils.log import get_module_logger
from twisted.python.components import globalRegistry
logger = get_module_logger(__name__)


class DewarController(GObject.GObject):

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

        self.layout = {}
        self.states = {}

        self.beamline.automounter.connect('notify::ports', self.on_port_state)
        self.beamline.automounter.connect('notify::layout', self.on_dewar_layout)
        self.beamline.automounter.connect('notify::status', self.on_state_changed)
        self.store.connect('notify::ports', self.on_port_state)

        self.beamline.automounter.connect('active', self.on_state_changed)
        self.beamline.automounter.connect('busy', self.on_state_changed)
        self.beamline.automounter.connect('health', self.on_state_changed)
        self.beamline.automounter.connect('message', self.on_state_changed)

    def setup(self):
        self.widget.sample_dewar_area.connect('draw', self.draw_dewar)
        self.widget.sample_dewar_area.set_events(
            Gdk.EventMask.EXPOSURE_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.POINTER_MOTION_HINT_MASK | Gdk.EventMask.VISIBILITY_NOTIFY_MASK
        )
        self.widget.sample_dewar_area.connect('motion-notify-event', self.on_motion_notify)
        self.widget.sample_dewar_area.connect('button-press-event', self.on_press_event)

    def on_dewar_layout(self, obj, param):
        self.layout = self.beamline.automounter.layout
        self.widget.sample_dewar_area.queue_draw()

    def draw_dewar(self, widget, cr):
        # background
        alloc = widget.get_allocation()
        cr.save()
        cr.scale(alloc.width, alloc.height)
        if self.layout:
            for loc, container in self.layout.items():
                container.draw(cr, self.states)
        else:
            xscale, yscale = cr.device_to_user_distance(1, 1)
            cr.set_font_size(14*xscale)
            cr.set_line_width(1*xscale)
            text = 'Layout Not available!'
            cr.set_source_rgb(0.5, 0.35, 0)
            xb, yb, w, h = cr.text_extents(text)[:4]
            cr.move_to(0.5 - w / 2.0, 0.5 - h / 2.0 - yb)
            cr.show_text(text)
            cr.stroke()

        cr.restore()

    def find_port(self, x, y):
        for loc, container in self.layout.items():
            port = container.get_port(x, y)
            if port:
                return port

    def on_port_state(self, *args, **kwargs):
        self.states = {
            port: self.get_state(port) for port in self.beamline.automounter.ports.keys()
        }
        self.widget.sample_dewar_area.queue_draw()

    def get_state(self, port):
        if port in self.store.ports or self.beamline.is_admin():
            return self.beamline.automounter.ports.get(port, Port.UNKNOWN)
        else:
            return Port.FORBIDDEN

    def on_motion_notify(self, widget, event):
        alloc = widget.get_allocation()
        x = event.x/alloc.width
        y = event.y/alloc.height
        port = self.find_port(x, y)
        if port and self.states.get(port) not in [None, Port.BAD, Port.EMPTY, Port.FORBIDDEN]:
            label = self.store.get_name(port)
            event.window.set_cursor(Gdk.Cursor.new(Gdk.CursorType.HAND2))
            self.widget.hover_sample_lbl.set_text(port)
            self.widget.hover_state_lbl.set_text(label)
        else:
            event.window.set_cursor(None)

    def on_press_event(self, widget, event):
        alloc = widget.get_allocation()
        x = event.x/alloc.width
        y = event.y/alloc.height
        port = self.find_port(x, y)
        if port and self.states.get(port) not in [None, Port.BAD, Port.EMPTY, Port.FORBIDDEN]:
            self.emit('selected', port)


    def on_state_changed(self, obj, val):
        code, h_msg = self.beamline.automounter.health_state
        message = self.beamline.automounter.message_state
        busy = self.beamline.automounter.busy_state
        enabled = self.beamline.automounter.enabled_state
        active = self.beamline.automounter.active_state
        status = self.beamline.automounter.status

        # Do nothing if the state has not really changed
        _new_state = [code, h_msg, status, message, busy, enabled, active]
        if message.strip() == "":
            message = h_msg

        message = "<tt>{} - </tt>{}".format(datetime.now().strftime('%H:%M:%S'), message.strip())
        if not self.messages or message != self.messages[-1]:
            self.messages.append(message)

        if status.name == 'IDLE' and code < 2 and not busy:
            self.widget.automounter_command_box.set_sensitive(True)
        else:
            self.widget.automounter_command_box.set_sensitive(False)
        if len(self.messages) > 2:
            self.messages = self.messages[-2:]

        self.widget.automounter_message_fbk.set_markup(' ...\n'.join(self.messages))
        self.widget.automounter_status_fbk.set_text(status.name)