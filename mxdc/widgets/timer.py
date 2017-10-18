import time
from gi.repository import Gtk, GObject


class Timer(Gtk.DrawingArea):
    """
    A count-down timer icon
    """
    total = GObject.Property(type=float, default=10.0)
    value = GObject.Property(type=float, default=0.0)

    def __init__(self, size=Gtk.IconSize.BUTTON):
        super(Timer, self).__init__()
        self.set_size_request(16, 16)
        self.props.valign = Gtk.Align.CENTER
        self.props.halign = Gtk.Align.CENTER
        self.start_time = 0
        self.connect('notify::value', self.on_time)
        self.show_all()

    def start(self, total=10.0):
        self.props.total = total
        self.start_time = time.time()
        self.props.value = self.props.total
        GObject.timeout_add(100, self.countdown)

    def countdown(self):
        value = self.props.total - (time.time() - self.start_time)
        self.props.value = max(0, value)
        return value > 0

    def on_time(self, widget, param):
        self.queue_draw()

    def do_draw(self, cr):
        alloc = self.get_allocation()
        style = self.get_style_context()
        color = style.get_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(color.red, color.green, color.blue, 0.7)
        cx = radius = alloc.width/2
        cy = alloc.height/2
        fraction = 6.283 * max(0, self.props.value)/self.props.total
        offset = -1.57

        cr.set_line_width(0.5)
        cr.move_to(cx, cy)
        cr.arc(cx, cy, radius, -fraction + offset, offset)
        cr.fill()