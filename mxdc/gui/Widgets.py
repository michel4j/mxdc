import gtk
from gtk import gdk
import gobject
try:
    import cairo
    using_cairo = False
except:
    using_cairo = False

import math

class Guage(gtk.DrawingArea):
    __gsignals__ = dict(pointval_changed=(gobject.SIGNAL_RUN_FIRST,
                                          gobject.TYPE_NONE,
                                          (gobject.TYPE_FLOAT,)))

    def __init__(self, minrg, maxrg, majticks, minticks, decs):
        """
        minrg, maxrg: minimum and maximum of range
        majticks: number of major divisions, equal to number of major ticks
        plus one
        minticks: number of minor tick marks per major tick mark
        decs: number of decimal places for tick mark labels
        """
        super(Guage, self).__init__()

        self.connect("expose_event", self.expose)
        self._pointer = 0 
        self.minrg, self.maxrg, self.majticks, self.minticks = minrg, maxrg, majticks, minticks
        self.frmstrg = '%%.%df' % int(decs)

    def expose(self, widget, event):
        if using_cairo:
            context = widget.window.cairo_create()

            # set a clip region for the expose event
            context.rectangle(event.area.x, event.area.y,
                              event.area.width, event.area.height)
            context.clip()
            self.draw_cairo(context)
        else:      
            colormap = widget.get_colormap()
            gcontext = widget.window.new_gc(background=gdk.Color(0, 0, 0),
                                            foreground=colormap.alloc_color(gdk.Color(65535, 65535, 65535)) ,
                                            clip_x_origin=event.area.x,
                                            clip_y_origin=event.area.y)
            playout = widget.create_pango_layout("")
            self.draw_gdk(gcontext, playout, widget.window)
        return False

    def draw_cairo(self, context):
        rect = self.get_allocation()
        minticks = self.minticks
        majticks = self.majticks
        minrg = self.minrg
        maxrg = self.maxrg
        frmstrg = self.frmstrg
        x = rect.x + rect.width / 2
        y = rect.y + rect.height

        radius = min(rect.width / 2, rect.height) - (context.text_extents(frmstrg % maxrg)[2] * 1.15)
       
        # clock back
        context.arc(x, y, radius, 1 * math.pi, 2 * math.pi)
        context.set_source_rgb(1, 1, 1)
        context.fill_preserve()
        context.set_source_rgb(0, 0, 0)
        context.line_to(x - radius, y)
        context.stroke()
        
        # clock ticks
        for i in range((majticks * (minticks + 1) + 1),2 * majticks * (minticks + 1)):
            context.save()
            
            if i % (minticks + 1) == 0:
                inset = 0.2 * radius

                # labels
                labelnum = ((i/(majticks * (minticks + 1.0) )) - 1) * (maxrg - minrg) + minrg
                x_bearing, y_bearing, width, height = context.text_extents(frmstrg % labelnum)[:4]
                if ((labelnum - minrg) / (maxrg - minrg)) > 0.51:
                    xfac = 0
                elif ((labelnum - minrg) / (maxrg - minrg)) < 0.51 and ((labelnum - minrg) / (maxrg - minrg)) > 0.49:
                    xfac = -width/2
                else:
                    xfac = -width
                context.move_to(x + radius * math.cos(math.pi * i / (majticks * (minticks + 1) )) + xfac,
                                y + (radius * 1.1) * math.sin(math.pi * i / (majticks * (minticks + 1) )))
                context.show_text(frmstrg % labelnum)

            else:
                inset = 0.1 * radius
                context.set_line_width(0.5 * context.get_line_width())

            context.move_to(x + (radius - inset) * math.cos(math.pi * i / (majticks * (minticks + 1) )),
                            y + (radius - inset) * math.sin(math.pi * i / (majticks * (minticks + 1) )))
            context.line_to(x + radius * math.cos(math.pi * i / (majticks * (minticks + 1) )),
                            y + radius * math.sin(math.pi * i / (majticks * (minticks + 1) )))
            context.stroke()
            
            context.restore()

        # minimum and maximum labels
        context.save()
        width, height = context.text_extents(frmstrg % minrg)[2:4]
        context.move_to(x - radius - (width * 1.1), y)
        context.show_text(frmstrg % minrg)
        context.move_to(x + radius + (0.1 * width), y)
        context.show_text(frmstrg % maxrg)
        context.restore()
        
        # needle position
        f = (radius/10)**2
        pointer = self._pointer
        context.save()
        xp = x + (radius / 1.5 * -math.cos(math.pi * pointer))
        yp = y + (radius / 1.5 * -math.sin(math.pi * pointer))
        if abs(yp - y) < 0.01:
            xa = x
        else:
            xa = math.sqrt(f / (1 + ((xp - x)/(y - yp))**2)) + x
        if abs(xp - x) < 0.01:
            ya = y
        else:
            ya = math.sqrt(f / (1 + ((y - yp)/(xp - x))**2)) + y
        xb = (2 * x) - xa
        yb = (2 * y) - ya
#        if math.cos(math.pi * pointer) > 0.1:
        if xp - x < 0:
            yb = ya
            ya = (2 * y) - yb
        context.set_source_rgb(0, 0, 0)
        context.move_to(xa, ya)
        context.line_to(xb, yb)
        context.line_to(xp, yp)
#        context.line_to(xa, ya)
        context.fill_preserve()
        context.stroke()
        context.restore()

    def draw_gdk(self, gcontext, playout, area):
        rect = self.get_allocation()
        minticks = self.minticks
        majticks = self.majticks
        minrg = self.minrg
        maxrg = self.maxrg
        frmstrg = self.frmstrg
        x = rect.x + rect.width / 2
        y = rect.y + rect.height

        playout.set_font_description(playout.get_context().get_font_description())
        playout.set_text(frmstrg % maxrg)
        radius = int(min(rect.width / 2, rect.height) - (playout.get_pixel_size()[0] * 1.15))

        
        # clock back
        area.draw_arc(gcontext, True, x - radius, y - radius, radius * 2, radius * 2, 0, (180*64 + 1))
        gcontext.set_foreground(gdk.Color(0,0,0))
        gcontext.set_line_attributes(2, gdk.LINE_SOLID, gdk.CAP_BUTT, gdk.JOIN_MITER)
        area.draw_arc(gcontext, False, x - radius, y - radius, radius * 2, radius * 2, 0, (180*64 + 1))
        area.draw_segments(gcontext, ((x-radius, y-1, x+radius, y-1),))

        # clock ticks
        for i in range((majticks * (minticks + 1) + 1),2 * majticks * (minticks + 1)):
            
            if i % (minticks + 1) == 0:
                inset = 0.2 * radius
                gcontext.set_line_attributes(2, gdk.LINE_SOLID, gdk.CAP_BUTT, gdk.JOIN_MITER)

                # labels
                labelnum = ((i/(majticks * (minticks + 1.0) )) - 1) * (maxrg - minrg) + minrg
                playout.set_text(frmstrg % labelnum)
                width, height = playout.get_pixel_size()
                if ((labelnum - minrg) / (maxrg - minrg)) > 0.51:
                    xfac = 0.1 * width
                elif ((labelnum - minrg) / (maxrg - minrg)) < 0.51 and ((labelnum - minrg) / (maxrg - minrg)) > 0.49:
                    xfac = -width/2
                else:
                    xfac = -1.1 * width
                area.draw_layout(gcontext,
                                        int(x + radius * math.cos(math.pi * i / (majticks * (minticks + 1) )) + xfac),
                                        int(y + (radius * 1) * math.sin(math.pi * i / (majticks * (minticks + 1) )) - height),
                                        playout)

            else:
                inset = 0.1 * radius
                gcontext.set_line_attributes(1, gdk.LINE_SOLID, gdk.CAP_BUTT, gdk.JOIN_MITER)

            area.draw_segments(gcontext, ((
                int(x + (radius - inset) * math.cos(math.pi * i / (majticks * (minticks + 1)))),
                int(y + (radius - inset) * math.sin(math.pi * i / (majticks * (minticks + 1)))),
                int(x + radius * math.cos(math.pi * i / (majticks * (minticks + 1) ))),
                int(y + radius * math.sin(math.pi * i / (majticks * (minticks + 1) )))),))

        # minimum and maximum labels
        playout.set_text(frmstrg % minrg)
        width, height = playout.get_pixel_size()
        area.draw_layout(gcontext, int(x - radius - (width * 1.1)), y - height, playout)
        playout.set_text(frmstrg % maxrg)
        area.draw_layout(gcontext, x + radius, y - height, playout)
        
        # needle position
        f = (radius/10)**2
        pointer = self._pointer
        xp = x + radius / 1.2 * -math.cos(math.pi * pointer)
        yp = y + radius / 1.2 * -math.sin(math.pi * pointer)
        if abs(yp - y) < 0.01:
            xa = x
        else:
            xa = int(math.sqrt(f / (1 + ((xp - x)/(y - yp))**2)) + x)
        if abs(xp - x) < 0.01:
            ya = y
        else:
            ya = int(math.sqrt(f / (1 + ((y - yp)/(xp - x))**2)) + y)
        xb = (2 * x) - xa
        yb = (2 * y) - ya
        if xp - x < 0:
            yb = ya
            ya = (2 * y) - yb
        area.draw_polygon(gcontext, True, [(xa, ya), (int(xp), int(yp)), (xb, yb)])

    def redraw_canvas(self):
        if self.window:
            alloc = self.get_allocation()
            self.queue_draw_area(alloc.x, alloc.y, alloc.width, alloc.height)
            self.window.process_updates(True)

    def _get_pointval(self):
        return self._pointer
    def _set_pointval(self, pointer):
        self._pointer = pointer
        self.redraw_canvas()
    pointval = property(_get_pointval, _set_pointval)

def on_change_value(scrolltype, clock, spinner):
    clock.pointval = spinner.get_value()
    
def main():
    window = gtk.Window()
    window.set_default_size(200,100)
    clock = Guage(0, 100, 4, 1, 0)
    vbox = gtk.VBox(False,8)    
    window.add(vbox)
    adj = gtk.Adjustment(0.0, 0.0, 1.0, 0.05, 0.1, 0.0)
    spinner = gtk.SpinButton(adj, 0, 2)
    spinner.set_wrap(True)
    spinner.connect('value-changed', on_change_value, clock, spinner)
    
    vbox.pack_start(clock, True, True)
    vbox.pack_start(spinner, False, True, 0)
    
    window.connect("destroy", gtk.main_quit)
    window.show_all()

    gtk.main()

if __name__ == "__main__":
    main()