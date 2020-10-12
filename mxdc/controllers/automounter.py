

from datetime import datetime

from gi.repository import Gdk, Gtk

from mxdc import Registry, Object, Property, Signal, IBeamline
from mxdc.utils.automounter import Port
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs

logger = get_module_logger(__name__)


class DewarController(Object):

    class Signals:
        selected = Signal("selected", arg_types=(str,))

    layout = Property(type=object)
    ports = Property(type=object)
    containers = Property(type=object)

    def __init__(self, widget, store):
        super().__init__()
        self.widget = widget
        self.store = store
        self.beamline = Registry.get_utility(IBeamline)
        self.setup()
        self.failure_dialog = None
        self.messages = [(None, "")]

        self.props.layout = {}
        self.props.ports = {}
        self.props.containers = []

        self.beamline.automounter.connect('status', self.on_state_changed)
        self.beamline.automounter.connect('ports', self.on_layout_changed)
        self.beamline.automounter.connect('layout', self.on_layout_changed)
        self.beamline.automounter.connect('containers', self.on_layout_changed)
        self.beamline.automounter.connect('sample', self.on_layout_changed)
        self.beamline.automounter.connect('failure', self.on_failure_changed)

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
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.VISIBILITY_NOTIFY_MASK
        )
        self.widget.sample_dewar_area.connect('query-tooltip', self.on_query_tooltip)
        self.widget.sample_dewar_area.connect('button-press-event', self.on_press_event)

    def get_port_state(self, port):
        robot_ports = self.beamline.automounter.get_state('ports')
        user_ports = self.store.ports
        state = robot_ports.get(port, Port.UNKNOWN)
        if port in user_ports:
            if state not in [Port.BAD, Port.EMPTY, Port.MOUNTED]:
                state = Port.GOOD
        return state

    def on_layout_changed(self, obj, *args):
        self.props.layout = self.beamline.automounter.get_state('layout')
        robot_ports = self.beamline.automounter.get_state('ports')
        robot_containers = self.beamline.automounter.get_state('containers')
        user_ports = self.store.ports
        user_containers = self.store.containers
        self.props.ports = {
            port: self.get_port_state(port)
            for port in list(robot_ports.keys())
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
            for loc, container in list(self.layout.items()):
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
        for loc, container in list(self.layout.items()):
            port = container.get_port(x, y)
            if port:
                return loc, port
        return None, None

    def on_query_tooltip(self, widget, x, y, keyboard, tooltip):
        if keyboard:
            return False
        alloc = widget.get_allocation()
        xp = x / alloc.width
        yp = y / alloc.height
        loc, port = self.find_port(xp, yp)
        if loc and port and self.allow_port(loc, port):
            label = self.store.get_name(port)
            widget.get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.HAND2))
            tooltip.set_markup('<small><b>{}</b>\n{}</small>'.format(port, label))
            return True
        else:
            widget.get_window().set_cursor(None)
            return False

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

    def on_state_changed(self, obj, *args):
        status = self.beamline.automounter.get_state('status')

        if status.name in ['IDLE', ]:
            self.widget.automounter_command_box.set_sensitive(True)

        self.widget.automounter_status_fbk.set_text(status.name)

        failure = self.beamline.automounter.get_state('failure')
        if status.name == 'IDLE' and failure and self.failure_dialog:
            self.failure_dialog.destroy()
            self.failure_dialog = None

    def failure_callback(self, dialog, response, context):
        if self.failure_dialog:
            self.failure_dialog.destroy()
            self.failure_dialog = None
        if response == Gtk.ButtonsType.OK:
            self.beamline.automounter.recover(context)
            message = ("Recovery is in progress. This operation may take\n"
                       "a few minutes. The automounter will be usable again\n"
                       "when it reaches the IDLE state")
            dialogs.info('Automounter Recovery', message, modal=False)

    def on_failure_changed(self, obj, failure):
        failure_context = failure
        if failure_context:
            failure_type, message = failure_context
            self.failure_dialog = dialogs.make_dialog(
                Gtk.MessageType.QUESTION, 'Automounter Failed: {}'.format(failure_type.replace('-', ' ').title()),
                message, buttons=(('Cancel', Gtk.ButtonsType.CANCEL), ('Recover', Gtk.ButtonsType.OK)), modal=False
            )
            self.failure_dialog.connect('response', self.failure_callback, failure_context)
            self.failure_dialog.show_all()
        else:
            if self.failure_dialog:
                self.failure_dialog.destroy()
                self.failure_dialog = None

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