import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

ARROW_WIDTH = 8
ARROW_HEIGHT = 28


class ArrowFrame(Gtk.Frame):
    __gtype_name__ = 'ArrowFrame'

    offset = GObject.Property(type=float)

    def __init__(self):
        super().__init__()
        self.task_row = None
        self._style = self.get_style_context()
        self._style.add_class('arrow-frame')
        self.props.valign = Gtk.Align.FILL
        self.props.halign = Gtk.Align.END

    def set_row(self, task_row):
        self.task_row = task_row
        self.task_row.connect('destroy', self.on_row_destroyed)
        self.queue_draw()

    def get_row_y(self):
        my_alloc = self.get_allocation()
        if not self.task_row:
            return my_alloc.height / 2
        else:
            row_alloc = self.task_row.get_allocation()
            return row_alloc.y + row_alloc.height / 2

    def draw_arrow(self, cr):
        style = self.get_style_context()
        state = style.get_state()
        dir = self.get_direction()
        border = style.get_border(state)
        border_color = style.get_border_color(state)

        alloc = self.get_allocation()
        if dir == Gtk.TextDirection.LTR:
            start_x = end_x = ARROW_WIDTH + border.left
            border_width = border.left
            tip_x = 0
        else:
            start_x = end_x = alloc.width - ARROW_WIDTH - border.right
            border_width = border.right
            tip_x = alloc.width
        tip_y = self.get_row_y()
        start_y = tip_y - ARROW_HEIGHT / 2.
        end_y = tip_y + ARROW_HEIGHT / 2.

        # draw the arrow
        cr.save()
        cr.set_line_width(1.0)
        cr.move_to(start_x, start_y)
        cr.line_to(tip_x, tip_y)
        cr.line_to(end_x, end_y)
        cr.clip()

        # render the background
        Gtk.render_background(style, cr, 0, 0, alloc.width, alloc.height)

        # draw the border
        cr.set_source_rgba(*list(border_color))
        cr.set_line_width(1.0)
        cr.move_to(start_x, start_y)
        cr.line_to(tip_x, tip_y)
        cr.line_to(end_x, end_y)

        cr.set_line_width(border_width + 1)
        cr.stroke()

        cr.restore()

    def draw_background(self, cr):
        style = self.get_style_context()
        state = style.get_state()
        margin = style.get_margin(state)
        alloc = self.get_allocation()
        dir = self.get_direction()
        gap_position = Gtk.PositionType.LEFT if dir == Gtk.TextDirection.LTR else Gtk.PositionType.RIGHT
        if dir == Gtk.TextDirection.LTR:
            start_x = ARROW_WIDTH + margin.left
            end_x = alloc.width - margin.right
        else:
            start_x = margin.left
            end_x = alloc.width - margin.right - ARROW_WIDTH

        start_y = margin.top
        end_y = alloc.height - margin.bottom
        start_gap = ((end_y - start_y - ARROW_HEIGHT) / 2.)
        end_gap = ((end_y - start_y + ARROW_HEIGHT) / 2.)

        Gtk.render_background(style, cr, start_x, start_y, end_x, end_y)
        Gtk.render_frame_gap(style, cr, start_x, start_y, end_x, end_y, gap_position, start_gap, end_gap)

    def do_draw(self, cr):
        self.draw_background(cr)
        self.draw_arrow(cr)
        child = self.get_child()
        if child:
            self.propagate_draw(child, cr)
        return True

    def do_size_allocate(self, allocation):
        alloc = self.get_child().get_allocation()
        alloc.y, alloc.height, alloc.width = allocation.y, allocation.height, allocation.width - ARROW_WIDTH
        if self.get_direction() != Gtk.TextDirection.RTL:
            alloc.x = allocation.x + ARROW_WIDTH
        self.get_child().size_allocate(alloc)
        self.set_allocation(allocation)

    def get_preferred_width(self):
        min_width, natural_width = super(ArrowFrame, self).get_preferred_width
        return max(min_width + ARROW_WIDTH, natural_width + ARROW_WIDTH + self.props.offset)

    def on_row_destroyed(self, obj):
        self.row = None
        self.queue_draw()
