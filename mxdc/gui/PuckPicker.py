import numpy
import gtk
import pango
try:
    import cairo
    using_cairo = True
except:
    using_cairo = False

class Puck(gtk.DrawingArea):
    def __init__(self, name=''):
        gtk.DrawingArea.__init__(self)
        self.set_app_paintable(True)
        self.black_gc = None 
        self.connect('expose-event', self.on_expose)
        self.connect('configure-event', self.on_configure)
        self.connect('button_press_event', self.on_mouse_click)
        self.connect('motion_notify_event', self.on_mouse_motion)
        self.ilenf = 140/394.
        self.olenf = 310/394.
        self.set_size_request(150,150)
        self.queue_draw()
        self.position = name
        self.loc = {}
        for i in range(16):
            self.loc[i+1] = [0, 0, True, 0, 0.0, 'empty']
            
        self.state_rgba = {
            'unknown' : (0.7,0.7,0.7, 1.0),
            'good': (0.4, 1.0, 0.4, 0.5),
            'bad': (1.0, 0.4, 0.4, 0.5),
            'empty': (1.0, 1.0, 1.0, 1.0),
            'mounted': (1.0, 0.0, 1.0, 0.5)
        }
        self.font_desc = pango.FontDescription('Serif 8')
        self.set_events(gtk.gdk.EXPOSURE_MASK |
                gtk.gdk.LEAVE_NOTIFY_MASK |
                gtk.gdk.BUTTON_PRESS_MASK |
                gtk.gdk.POINTER_MOTION_MASK |
                gtk.gdk.POINTER_MOTION_HINT_MASK|
                gtk.gdk.VISIBILITY_NOTIFY_MASK)  
           
    
    def on_expose(self, obj=None, event=None):
        global using_cairo
        if self.black_gc is None:
            self.window.clear()
            self.black_gc = self.window.new_gc()
            self.grey_gc =  self.window.new_gc()
            style = self.get_style()
            self.black_gc.foreground = style.fg[gtk.STATE_NORMAL]
            self.grey_gc.foreground = self.get_colormap().alloc_color( gtk.gdk.color_parse('gray') )
            self.lgc = {}
            for k,v in self.state_rgba.items():
                self.lgc[k] = self.window.new_gc()
                r = int(v[0]*32767 + (v[3])*32767)
                g = int(v[1]*32767 + (v[3])*32767)
                b = int(v[2]*32767 + (v[3])*32767)
                col = gtk.gdk.Color(red=r, green=g, blue=b)
                self.lgc[k].foreground = self.get_colormap().alloc_color(col)
            self.pl = []
            self.font_desc = pango.FontDescription('Monospace 9')
            for i in range(16):
                self.pl.append( self.create_pango_layout("%d" % (i+1)) )
                self.pl[-1].set_font_description(self.font_desc)
            self.id_label = self.create_pango_layout(self.position)
            self.id_label.set_font_description(pango.FontDescription('Sans Bold 15'))
            
        if using_cairo:
            self.draw_cairo()
        else:
            self.draw_gdk()
        return False

    def on_configure(self, obj, event):
        width, height = self.allocation.width, self.allocation.height
        self.radius = width/12
        self.sq_rad = self.radius*self.radius
        ilen = width * self.ilenf /2.0
        olen = width * self.olenf /2.0
        self.hw = float(width)/2
        angs_o = numpy.linspace(0,360.0,12)[:-1]
        angs_i = numpy.linspace(0,360.0,6)[:-1]
        count = 0
        for ang in angs_i:
            count += 1
            x = int( self.hw + ilen * numpy.cos( (270-ang) * numpy.pi / 180.0) )
            y = int( self.hw + ilen * numpy.sin( (270-ang) * numpy.pi / 180.0) )
            self.loc[count][0] = x
            self.loc[count][1] = y
        for ang in angs_o:
            count += 1
            x = int(self.hw + olen * numpy.cos( (270-ang) * numpy.pi / 180.0))
            y = int(self.hw + olen * numpy.sin( (270-ang) * numpy.pi / 180.0))
            self.loc[count][0] = x
            self.loc[count][1] = y
        return False
        
    def draw_gdk(self):
        self.window.draw_arc(self.grey_gc, True, 1, 1, self.allocation.width-2, self.allocation.width-2, 0, 23040)
        self.window.draw_arc(self.black_gc, False, 1, 1, self.allocation.width-2, self.allocation.width-2, 0, 23040)
        iw, ih = self.id_label.get_pixel_size()
        self.window.draw_layout(self.black_gc, int(self.hw-iw/2), int(self.hw-ih/2), self.id_label)
        for key, loc in self.loc.items():
            x,y = loc[:2]
            rad = self.radius
            self.window.draw_arc(self.lgc[ loc[-1] ], True, x-rad, y-rad, rad*2, rad*2, 0, 23040)
            self.window.draw_arc(self.black_gc, False, x-rad, y-rad, rad*2, rad*2, 0, 23040)
            iw, ih = self.pl[key -1].get_pixel_size()
            self.window.draw_layout(self.black_gc, x-iw/2, y-ih/2, self.pl[key -1])

    def draw_cairo(self):
        cr = self.window.cairo_create()
        #cr.set_source_rgba(1.0, 1.0, 1.0, 0.0) # Transparent
        #cr.set_operator(cairo.OPERATOR_SOURCE)
        #cr.paint()
        cr.set_line_width(1.0)
        
                
        cr.set_source_rgba( 0.7,0.7,0.7,0.5)
        cr.arc(self.hw, self.hw, self.hw, 0, 2.0*3.14)
        cr.fill()
        cr.set_source_rgba(0.0,0.0,0.0,1.0)
        cr.arc(self.hw, self.hw, self.hw, 0, 2.0*3.14)
        cr.stroke()
        
        #cr.select_font_face("Segoe UI", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(20)
        text = self.position
        x_b, y_b, w, h = cr.text_extents(text)[:4]
        cr.move_to(self.hw-w/2 - x_b, self.hw-h/2 -y_b)
        cr.show_text(text)
        cr.stroke()

        cr.set_line_width(0.8)
        #cr.select_font_face("Segoe UI", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10)
        for key, loc in self.loc.items():
            x, y = loc[:2]
            col = loc[-1]
            cr.set_source_rgba(0.0,0.0,0.0,1.0)
            cr.arc(x,y, self.radius, 0, 2.0*3.14)
            cr.stroke()        
            cr.set_source_rgba(*self.state_rgba[col])
            cr.arc(x,y, self.radius, 0, 2.0*3.14)
            cr.fill()
            cr.set_source_rgba(0.0,0.0,0.0,1.0)
            text = '%d' % key
            x_b, y_b, w, h = cr.text_extents(text)[:4]
            cr.move_to(x-w/2 - x_b, y-h/2 -y_b)
            cr.show_text(text)
            cr.stroke()
                        
    def on_mouse_click(self, widget, event):
        x, y = event.x, event.y
        x, y = x - self.hw, y - self.hw
        states = ['good', 'bad', 'mounted']
        sel_state = states[event.button -1]
        for key, loc in self.loc.items():
            xl, yl = loc[:2]
            xl, yl = xl - self.hw, yl - self.hw
            d2 = ((x - xl)**2 + (y - yl)**2)
            if d2 < self.sq_rad:
                loc[-1] = sel_state
                print 'Location %s-%d selected' % (self.position, key)
        self.queue_draw()
        return True

    def on_mouse_motion(self, widget, event):
        if event.is_hint:
            x, y, state = event.window.get_pointer()
        else:
            x, y = event.x, event.y
        x, y = x - self.hw, y - self.hw
        inside = False
        for key, loc in self.loc.items():
            xl, yl = loc[:2]
            xl, yl = xl - self.hw, yl - self.hw
            d2 = ((x - xl)**2 + (y - yl)**2)
            if d2 < self.sq_rad:
                inside = True
                break
         
        if inside:
            widget.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.HAND2))
        else:
            widget.window.set_cursor(None)
                            
        return True
              
class PuckFrame(gtk.AspectFrame):
    def __init__(self, name):
        gtk.AspectFrame.__init__(self)
        self.puck = Puck(name)
        self.add(self.puck)
        self.set_shadow_type(gtk.SHADOW_NONE)
        
win = gtk.Window()
p1 = PuckFrame('A')
p2 = PuckFrame('B')
p3 = PuckFrame('C')
p4 = PuckFrame('D')
vbox1 = gtk.VBox()
vbox2 = gtk.VBox()
vbox1.pack_start(p1)
vbox1.pack_start(p2)
vbox2.pack_start(p3)
vbox2.pack_start(p4)

hbox = gtk.HBox()
hbox.pack_start(vbox1)
hbox.pack_start(vbox2)

win.add(hbox)
win.show_all()
win.connect('destroy', lambda x: gtk.main_quit())
gtk.main()
