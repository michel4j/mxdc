from gi.repository import GObject
from gi.repository import Gtk
import math
from gi.repository import Pango

class Gauge(Gtk.DrawingArea):
    __gproperties__ = {
        'percent' : (float, 'Percent', 'Gauge Percentage', 0, 100, 0.0, GObject.PARAM_READWRITE),
        'digits' : (int, 'Digits', 'The number of decimal places to display', 0, 5, 0, GObject.PARAM_READWRITE),
        'low': (float, 'Low', 'The Low alarm percent', 0, 100, 0.0, GObject.PARAM_READWRITE),
        'high': (float, 'High', 'The High alarm percent', 0, 100, 100, GObject.PARAM_READWRITE),
        'units': (str, 'Units', 'Units to display', '', GObject.PARAM_READWRITE),
        'label': (str, 'Label', 'Text to display', '', GObject.PARAM_READWRITE),
    }
    def __init__(self, min_val, max_val, maj_ticks, min_ticks):
        """
        min_val, max_val: min_val and max_val of rng
        maj_ticks: number of major divisions, equal to number of major ticks
        plus one
        min_ticks: number of minor tick marks per major tick mark
        """
        super(Gauge, self).__init__()
        self.connect("draw", self.on_draw)
        self.connect('realize', self.on_realize)
        self._properties = {
            'percent': 0.0,
            'digits': 0,
            'low': 0.0,
            'high': 100.0,
            'units': '',
            'label': '',
        }
        self.minimum, self.maximum, self.majticks, self.minticks = min_val, max_val, maj_ticks, min_ticks
        self.set_size_request(120, 100)

    def on_realize(self, obj):
        self.connect('notify', self._on_property_change)

    def get_value(self):
        return self.get_property('percent') * self.maximum / 100.0
    
    def set_value(self, value):
        tg = max(0.0, min(100.0, value * 100.0/self.maximum))
        self.set_property('percent', tg)
    
    value = property(get_value, set_value)

    def _on_property_change(self, widget, val):
        GObject.idle_add(widget.queue_draw) 
            
    def do_get_property(self, pspec):
        if pspec.name in ['percent','digits','low','high', 'units', 'label']:
            return self._properties.get(pspec.name, None)
        else:
            raise AttributeError, 'unknown property %s' % pspec.name

    def do_set_property(self, pspec, value):
        if pspec.name in ['percent','digits','low','high','units', 'label']:
            self._properties[pspec.name] = value
        else:
            raise AttributeError, 'unknown property %s' % pspec.name
                    
    def on_draw(self, widget, context):
        rect = widget.get_allocation()
        
        style = widget.get_style_context()
        col = style.get_color(Gtk.StateType.NORMAL)
        context.set_source_rgba(col.red, col.green, col.blue, 0.25)
        context.rectangle(0, 0, rect.width, rect.height)
        context.stroke()
        
        context.set_source_rgba(*col)
        maximum = self.maximum
        frmstrg = '%%.%df' % self.get_property('digits')
        pads = context.text_extents(frmstrg % maximum)
        #radius = min((rect.width- 2.5*pads[2])/2, rect.height-(2.5*pads[3]))
        radius = min((rect.width- 2.5*pads[2])/2, (rect.height-(3*pads[3]))/2)
        x =  rect.width / 2
        y =  (pads[3] + rect.height)/2 # - (rect.height-radius-0.8*pads[3])/2
        offset = 0.25*math.pi
        
        # empty region
        context.set_source_rgba(0.9, 0.5, 0.5, 0.4)
        context.set_line_width(0.2*radius)
        empty_ang = 1.5 * math.pi * self.get_property('low') / 100.0
        context.arc(x, y, 0.9*radius, math.pi - offset, math.pi - offset + empty_ang)
        context.stroke()

        # Draw ticks
        context.set_source_rgba(*col)
        num_ticks = self.majticks * (self.minticks + 1) + 1
        tick_step = 1.5*math.pi / (num_ticks-1)
        label_radius = radius + 0.5 * pads[2]
        context.set_line_width(1.2)
        for i in range(num_ticks):
            context.save()
            tick_angle = i * tick_step
            cos_ta = math.cos(tick_angle-offset)
            sin_ta = math.sin(tick_angle-offset)
            
            if i%self.majticks == 0:
                tick_size = 0.2 * radius
                # labels
                labelnum = ((num_ticks - i)/self.majticks) * maximum/(self.majticks-1)
                xbearing, ybearing, width, height = context.text_extents(frmstrg % labelnum)[:4]
                cx = x + label_radius * cos_ta
                cy = y - label_radius * sin_ta
                context.move_to(cx + 0.5 - xbearing-width/2, cy + 0.5-ybearing-height/2)
                context.show_text(frmstrg % labelnum)
            elif i%(self.minticks-1) == 0:
                context.set_line_width(0.5 * context.get_line_width())
                tick_size = 0.15 * radius
            else:
                tick_size = 0.075 * radius
                context.set_line_width(0.5 * context.get_line_width())
            context.move_to(x + 0.8 * radius * cos_ta,  y - 0.8 * radius * sin_ta)
            context.line_to(x + (0.8*radius + tick_size) * cos_ta,  y - (0.8*radius + tick_size) * sin_ta)
            context.stroke()          
            context.restore()

        # show units
        xbearing, ybearing, width, height = context.text_extents(self.get_property('label'))[:4]
        context.move_to(x + 0.5 - xbearing-width/2, y + 0.25*radius + 0.5-ybearing-height/2)
        context.show_text(self.get_property('label'))
        xbearing, ybearing, width, height = context.text_extents(self.get_property('units'))[:4]
        context.move_to(x + 0.5 - xbearing-width/2, y + 0.5*radius + 0.5-ybearing-height/2 )
        context.show_text(self.get_property('units'))
        
        
        # needle
        f = (radius/20)**2
        pointer = (1.5*math.pi*self.get_property('percent')/100.0) - offset
        
        context.save()
        xp = x + (radius * 0.75 * -math.cos(pointer))
        yp = y + (radius * 0.75 * -math.sin(pointer))
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
        context.set_line_width(2)
        if self.get_property('percent') < self.get_property('low'):
            context.set_source_rgb(0.8, 0.0, 0.0)
        elif self.get_property('percent') > self.get_property('high'):
            context.set_source_rgb(0.8, 0.0, 0.0)
        else:
            context.set_source_rgb(0.0, 0.6, 0.0)
        context.move_to(xa, ya)
        context.line_to(xb, yb)
        context.line_to(xp, yp)
        context.line_to(xa, ya)
        context.fill()

        context.move_to(xa, ya)
        context.line_to(xb, yb)
        context.line_to(xp, yp)
        context.line_to(xa, ya)
        context.fill()
        context.arc(x, y, radius*0.1, 0, 2.0 * math.pi)
        context.fill()
          
        context.restore()
