import gtk
import gobject
import math
import pango
import sys

try:
    import cairo
    using_cairo = True
except:
    using_cairo = False

class Gauge(gtk.DrawingArea):
    __gproperties__ = {
        'percent' : (float, 'Percent', 'Gauge Percentage', 0, 100, 0.0, gobject.PARAM_READWRITE),
        'digits' : (int, 'Digits', 'The number of decimal places to display', 0, 5, 0, gobject.PARAM_READWRITE),
        'low': (float, 'Low', 'The Low alarm percent', 0, 100, 0.0, gobject.PARAM_READWRITE),
        'high': (float, 'High', 'The High alarm percent', 0, 100, 100, gobject.PARAM_READWRITE),
        'units': (str, 'Units', 'Units to display', '', gobject.PARAM_READWRITE),
    }
    def __init__(self, minimum, maximum, majticks, minticks):
        """
        minimum, maximum: minimum and maximum of range
        majticks: number of major divisions, equal to number of major ticks
        plus one
        minticks: number of minor tick marks per major tick mark
        """
        gtk.DrawingArea.__init__(self)
        self.set_app_paintable(True)
        self.connect("expose-event", self.on_expose)
        self.connect('realize', self.on_realize)
        self._properties = {
            'percent': 0.0,
            'digits': 0,
            'low': 0.0,
            'high': 100.0,
            'units': '',
        }
        self.minimum, self.maximum, self.majticks, self.minticks = minimum, maximum, majticks, minticks

        self.set_size_request(125,75)

    def on_realize(self, obj):
        self.connect('notify', self._on_property_change)

    def get_value(self):
        return self.get_property('percent') * self.maximum / 100.0
    
    def set_value(self, value):
        tg = max(0.0, min(100.0, value * 100.0/self.maximum))
        self.set_property('percent', tg)
    
    value = property(get_value, set_value)

    def _on_property_change(self, widget, val):
        widget.queue_draw() 
            
    def do_get_property(self, pspec):
        if pspec.name in ['percent','digits','low','high', 'units']:
            return self._properties.get(pspec.name, None)
        else:
            raise AttributeError, 'unknown property %s' % pspec.name

    def do_set_property(self, pspec, value):
        if pspec.name in ['percent','digits','low','high','units']:
            self._properties[pspec.name] = value
        else:
            raise AttributeError, 'unknown property %s' % pspec.name
                    
    def on_expose(self, widget, event):
        if using_cairo:
            context = widget.window.cairo_create()
            context.rectangle(event.area.x, event.area.y,
                              event.area.width, event.area.height)
            context.clip()
            pcontext = widget.get_pango_context()
            font_desc = pcontext.get_font_description()
            style = widget.get_style()
            context.set_source_color(style.fg[gtk.STATE_NORMAL] )
            context.set_font_size( font_desc.get_size()/pango.SCALE )
            widget.draw_cairo(context)
        else:       
            gcontext = widget.window.new_gc()
            style = self.get_style()
            gcontext.foreground = style.fg[gtk.STATE_NORMAL]
            gcontext.set_clip_origin(event.area.x, event.area.y)
            widget.draw_gdk(gcontext)
        return False

    def draw_cairo(self, context):
        rect = self.get_allocation()
        minimum = self.minimum
        maximum = self.maximum
        frmstrg = '%%.%df' % self.get_property('digits')
        pads = context.text_extents(frmstrg % maximum)
        radius = min((rect.width- 2.5*pads[2])/2, rect.height-(2.5*pads[3]))
        x =  rect.width / 2
        y =  rect.height - (rect.height-radius-0.8*pads[3])/2
        
        # Draw ticks
        num_ticks = self.majticks * (self.minticks + 1) + 1
        tick_step = math.pi / (num_ticks-1)
        label_radius = radius + 0.5 * pads[2]
        for i in range(num_ticks):
            context.save()
            tick_angle = i * tick_step
            cos_ta = math.cos(tick_angle)
            sin_ta = math.sin(tick_angle)
            
            if i%self.majticks == 0:
                tick_size = 0.2 * radius
                # labels
                labelnum = ((num_ticks - i)/self.majticks) * maximum/(self.majticks-1)
                xbearing, ybearing, width, height = context.text_extents(frmstrg % labelnum)[:4]
                cx = x + label_radius * cos_ta
                cy = y - label_radius * sin_ta
                context.move_to(cx + 0.5 - xbearing-width/2, cy + 0.5-ybearing-height/2)
                context.show_text(frmstrg % labelnum)
            else:
                tick_size = 0.1 * radius
                context.set_line_width(0.5 * context.get_line_width())
            context.move_to(x + (radius - tick_size) * cos_ta,  y - (radius - tick_size) * sin_ta)
            context.line_to(x + radius * cos_ta,  y - radius * sin_ta)
            context.stroke()          
            context.restore()

        # show units
        xbearing, ybearing, width, height = context.text_extents(self.get_property('units'))[:4]
        context.move_to(x + 0.5 - xbearing-width/2, y - 0.5*radius + 0.5-ybearing-height/2)
        context.show_text(self.get_property('units'))
        
        # needle position
        f = (radius/20)**2
        pointer = self.get_property('percent')/100.0
        context.save()
        xp = x + (radius * 0.75 * -math.cos(math.pi * pointer))
        yp = y + (radius * 0.75 * -math.sin(math.pi * pointer))
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
        if xp - x < 0:
            yb = ya
            ya = (2 * y) - yb
        context.move_to(xa, ya)
        context.line_to(xb, yb)
        context.line_to(xp, yp)
        context.line_to(xa, ya)
        if self.get_property('percent') < self.get_property('low'):
            context.set_source_rgba(0.8, 0.0, 0.0, 0.8)
        elif self.get_property('percent') > self.get_property('high'):
            context.set_source_rgba(0.8, 0.0, 0.0, 0.8)
        else:
            context.set_source_rgba(0.0, 0.6, 0.0, 0.8)
        context.fill()
        context.restore()

    def draw_gdk(self, context):
        area = self.window
        rect = self.get_allocation()
        minimum = self.minimum
        maximum = self.maximum
        frmstrg = '%%.%df' % self.get_property('digits')
        fd = self.get_pango_context().get_font_description()
        pl = self.create_pango_layout(frmstrg % maximum)
        fd.set_size( int(fd.get_size() * 0.85) )
        pl.set_font_description(fd)
        iw, ih = pl.get_pixel_size()
        radius = min((rect.width- 2*iw)/2, rect.height-(2*ih))
        x =  rect.width / 2
        y =  rect.height - (rect.height-radius)/2

        # Draw ticks
        num_ticks = self.majticks * (self.minticks + 1) + 1
        tick_step = math.pi / (num_ticks-1)
        label_radius = int(radius + 0.5 * iw)
        for i in range(num_ticks):
            tick_angle = i * tick_step
            cos_ta = math.cos(tick_angle)
            sin_ta = math.sin(tick_angle)
            
            if i%self.majticks == 0:
                tick_size = 0.3 * radius
                context.set_line_attributes(2, gtk.gdk.LINE_SOLID, gtk.gdk.CAP_BUTT, gtk.gdk.JOIN_MITER)
                
                # labels
                labelnum = ((num_ticks - i)/self.majticks) * maximum/(self.majticks-1)
                pl.set_text(frmstrg % labelnum)
                width, height = pl.get_pixel_size()
                cx = x + label_radius * cos_ta
                cy = y - label_radius * sin_ta
                area.draw_layout(context, int(cx-width/2), int(cy-height/2), pl)
            else:
                tick_size = 0.15 * radius
                context.set_line_attributes(1, gtk.gdk.LINE_SOLID, gtk.gdk.CAP_BUTT, gtk.gdk.JOIN_MITER)
            area.draw_line(context, 
                int(x + (radius - tick_size) * cos_ta),
                int(y - (radius - tick_size) * sin_ta),
                int(x + radius * cos_ta),
                int(y - radius * sin_ta))
        

        
        # show units
        pl.set_text(self.get_property('units'))
        width, height = pl.get_pixel_size()
        area.draw_layout(context, int(x - width/2), int(y - 0.5*radius -height/2), pl)

        # needle position
        f = (radius/20)**2
        pointer = self.get_property('percent')/100.0
        xp = x + (radius * 0.75 * -math.cos(math.pi * pointer))
        yp = y + (radius * 0.75 * -math.sin(math.pi * pointer))
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
        if xp - x < 0:
            yb = ya
            ya = (2 * y) - yb
        if self.get_property('percent') < self.get_property('low'):
            context.foreground = self.get_colormap().alloc_color( gtk.gdk.color_parse('#aa0000') )
        elif self.get_property('percent') > self.get_property('high'):
            context.foreground = self.get_colormap().alloc_color( gtk.gdk.color_parse('#aa0000') )
        else:
            context.foreground = self.get_colormap().alloc_color( gtk.gdk.color_parse('#00aa00') )
            
        area.draw_polygon(context, True, [(int(xa), int(ya)), (int(xp), int(yp)), (int(xb), int(yb))])

gobject.type_register(Gauge)
