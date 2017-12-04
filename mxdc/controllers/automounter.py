from __future__ import division

from datetime import datetime

from gi.repository import Gdk, GObject
from mxdc.beamlines.mx import IBeamline
from mxdc.utils.automounter import Port
from mxdc.utils.log import get_module_logger
from twisted.python.components import globalRegistry
logger = get_module_logger(__name__)


class DewarController(GObject.GObject):

    __gsignals__ = {
        'selected': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    layout = GObject.Property(type=object)
    ports = GObject.Property(type=object)
    containers = GObject.Property(type=object)

    def __init__(self, widget, store):
        super(DewarController, self).__init__()
        self.widget = widget
        self.store = store
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.setup()
        self.messages = [(None, "")]

        self.props.layout = {}
        self.props.ports = {}
        self.props.containers = []

        self.beamline.automounter.connect('notify::status', self.on_state_changed)
        self.beamline.automounter.connect('notify::ports', self.on_layout_changed)
        self.beamline.automounter.connect('notify::layout', self.on_layout_changed)
        self.beamline.automounter.connect('notify::containers', self.on_layout_changed)
        self.store.connect('notify::ports', self.on_layout_changed)
        self.store.connect('notify::containers', self.on_layout_changed)

        self.beamline.automounter.connect('active', self.on_state_changed)
        self.beamline.automounter.connect('busy', self.on_state_changed)
        self.beamline.automounter.connect('health', self.on_state_changed)
        self.beamline.automounter.connect('message', self.on_messages)

    def setup(self):
        self.widget.sample_dewar_area.connect('draw', self.draw_dewar)
        self.widget.sample_dewar_area.set_events(
            Gdk.EventMask.EXPOSURE_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.POINTER_MOTION_HINT_MASK | Gdk.EventMask.VISIBILITY_NOTIFY_MASK
        )
        self.widget.sample_dewar_area.connect('motion-notify-event', self.on_motion_notify)
        self.widget.sample_dewar_area.connect('button-press-event', self.on_press_event)

    def get_port_state(self, port,):
        robot_ports = self.beamline.automounter.ports
        user_ports = self.store.ports
        state = robot_ports.get(port, Port.UNKNOWN)
        if port in user_ports:
            if state not in [Port.BAD, Port.EMPTY, Port.MOUNTED]:
                state = Port.GOOD
        return state

    def on_layout_changed(self, *args, **kwargs):
        self.props.layout = self.beamline.automounter.layout

        robot_ports = self.beamline.automounter.ports
        robot_containers = self.beamline.automounter.containers
        user_ports = self.store.ports
        user_containers = self.store.containers

        self.props.ports = {
            port: self.get_port_state(port)
            for port in robot_ports.keys()
            if (port in user_ports or self.beamline.is_admin())
        }
        self.props.containers = {
            container for container in robot_containers
            if container in user_containers or self.beamline.is_admin()
        }

        self.widget.sample_dewar_area.queue_draw()

    def draw_dewar(self, widget, cr):
        # background
        alloc = widget.get_allocation()
        cr.save()
        cr.scale(alloc.width, alloc.height)

        if self.layout:
            for loc, container in self.layout.items():
                container.draw(cr, self.ports, self.containers)
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
                return loc, port
        return None, None

    def on_motion_notify(self, widget, event):
        alloc = widget.get_allocation()
        x = event.x/alloc.width
        y = event.y/alloc.height
        loc, port = self.find_port(x, y)
        if loc and port and self.allow_port(loc, port):
            label = self.store.get_name(port)
            event.window.set_cursor(Gdk.Cursor.new(Gdk.CursorType.HAND2))
            self.widget.hover_sample_lbl.set_text(port)
            if label:
                self.widget.hover_state_lbl.set_text(label)
        else:
            event.window.set_cursor(None)

    def allow_port(self, container, port):
        if self.beamline.is_admin() or ((container and port) and (port in self.ports)):
            return self.get_port_state(port) not in [Port.EMPTY, Port.BAD]
        return False

    def on_press_event(self, widget, event):
        alloc = widget.get_allocation()
        x = event.x/alloc.width
        y = event.y/alloc.height
        loc, port = self.find_port(x, y)
        if self.allow_port(loc, port):
            self.emit('selected', port)

    def on_state_changed(self, obj, val):
        code, h_msg = self.beamline.automounter.health_state
        status = self.beamline.automounter.status

        if status.name in ['IDLE', ] and code < 2:
            self.widget.automounter_command_box.set_sensitive(True)
        else:
            self.widget.automounter_command_box.set_sensitive(False)

        self.widget.automounter_status_fbk.set_text(status.name)

    def on_messages(self, obj, message):
        if message:
            prev_time, prev_msg = self.messages[-1]
            if message == prev_msg:
                return
            self.messages.append((datetime.now(), message))

            if len(self.messages) > 3:
                self.messages = self.messages[-3:]

            text = '\n'.join([
                "<small><tt>{} - </tt>{}</small>".format(dt.now().strftime('%H:%M:%S'), msg.strip())
                for dt, msg in self.messages if dt
            ])

            self.widget.automounter_message_fbk.set_markup(text)