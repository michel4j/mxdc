import math
import numpy
import gtk
import gobject
import pango
try:
    import cairo
    using_cairo = True
except:
    using_cairo = False

from bcm.utils.automounter import *
from bcm.device.automounter import Automounter, DummyAutomounter

class _DummyEvent(object):
    width = 0
    height = 0

class ContainerWidget(gtk.DrawingArea):
    __gsignals__ = {
        'pin-selected': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      (gobject.TYPE_STRING,)),
        'probe-select': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      (gobject.TYPE_STRING,)),
        'expose-event': 'override',
        'configure-event': 'override',
        'motion-notify-event': 'override',
        'button-press-event': 'override',   
    }
    
    def __init__(self, container):
        gtk.DrawingArea.__init__(self)
        self.container = container
        self.connect('realize', self.on_realize)
        self.container_type = self.container.container_type
        self._realized = False
        self.set_events(gtk.gdk.EXPOSURE_MASK |
                gtk.gdk.LEAVE_NOTIFY_MASK |
                gtk.gdk.BUTTON_PRESS_MASK |
                gtk.gdk.POINTER_MOTION_MASK |
                gtk.gdk.POINTER_MOTION_HINT_MASK|
                gtk.gdk.VISIBILITY_NOTIFY_MASK)
        self.set_size_request(246,214)
        self.container.connect('changed', self.on_container_changed)
    
    def on_container_changed(self, obj):
        self.setup(self.container.container_type)
        return False
        
    def setup(self, container_type):
        last_container = self.container_type
        self.container_type = container_type

        if last_container != self.container_type and self._realized:
            e = _DummyEvent()
            e.width = self.width+2*self.x_pad
            e.height = self.height+2*self.y_pad
            self.do_configure_event(e)     
        self.queue_draw()
    
    def _puck_coordinates(self, width, height):
        radius = self.radius
        ilenf = 140 / 394.
        olenf = 310 / 394.
        sq_rad = radius * radius
        ilen = width * ilenf / 4.0
        olen = width * olenf / 4.0
        hw = int(width / 4)
        angs_o = numpy.linspace(0, 360.0, 12)[: - 1]
        angs_i = numpy.linspace(0, 360.0, 6)[: - 1]
        count = 0
        locations = numpy.zeros((16, 2), dtype=numpy.int)
        for ang in angs_i:
            x = int(hw + ilen * math.cos((270 - ang) * math.pi / 180.0))
            y = int(hw + ilen * math.sin((270 - ang) * math.pi / 180.0))
            locations[count] = (x, y)
            count += 1
        for ang in angs_o:
            x = int(hw + olen * math.cos((270 - ang) * math.pi / 180.0))
            y = int(hw + olen * math.sin((270 - ang) * math.pi / 180.0))
            locations[count] = (x, y)
            count += 1
        locs = {
                'A': locations + (self.x_pad, self.y_pad),
                'B': locations + (self.x_pad, self.y_pad + height // 2),
                'C': locations + (self.x_pad + width // 2, self.y_pad),
                'D': locations + (self.x_pad + height // 2, self.y_pad + width / 2)
        }
        final_loc = {}
        for k, v in locs.items():
            for i in range(len(v)):
                final_loc['%c%1d' % (k, (i + 1))] = v[i]
        labels = {
                'A': (self.x_pad + hw, self.y_pad + hw),
                'B': (self.x_pad + hw, self.y_pad + hw + height // 2),
                'C': (self.x_pad + hw + width // 2, self.y_pad + hw),
                'D': (self.x_pad + hw + height // 2, self.y_pad + hw + width // 2)
        }
        return final_loc, labels

    def _cassette_coordinates(self, width, height, calib=False):
        radius = self.radius
        sq_rad = radius * radius
        labels = {}
        keys = 'ABCDEFGHIJKL'
        final_loc = {}
        for i in range(12):
            x = self.x_pad + int((2 * i + 1) * radius)
            labels[keys[i]] = (x, self.y_pad + int(self.radius))
            for j in range(8):
                if calib and 0<j<7:
                    continue
                loc_key = "%c%1d" % (keys[i], j + 1)
                y = self.y_pad + int((2 * j + 3) * radius)
                final_loc[loc_key] = (x, y)
        return final_loc, labels
       
    def on_realize(self, obj):
        style = self.get_style()
        self.port_colors = {
            PORT_EMPTY: gtk.gdk.color_parse("#aaaaaa"),
            PORT_GOOD: gtk.gdk.color_parse("#90dc8f"),
            PORT_UNKNOWN: style.bg[gtk.STATE_NORMAL],
            PORT_MOUNTED: gtk.gdk.color_parse("#dd5cdc"),
            PORT_JAMMED: gtk.gdk.color_parse("#ff6464"),
            PORT_NONE: style.bg[gtk.STATE_NORMAL]
            }     
        self.state_gc = {}  
        for key, spec in self.port_colors.items():
            self.state_gc[key] = self.window.new_gc()
            self.state_gc[key].foreground = self.get_colormap().alloc_color( spec )
        self._realized = True 
           
    
    def do_configure_event(self, event):
        if self.container_type == CONTAINER_PUCK_ADAPTER:
            self.height = min(event.width, event.height)
            self.width = self.height
            self.radius = (self.width)/19.0
            self.sq_rad = self.radius**2
            self.x_pad = (event.width - self.width)//2
            self.y_pad = (event.height - self.height)//2
            self.coordinates, self.labels = self._puck_coordinates(self.width, self.height)
        elif self.container_type in [CONTAINER_CASSETTE, CONTAINER_CALIB_CASSETTE]:
            self.width = min(event.width, event.height*12/9)
            self.height = self.width*9/12
            self.radius = (self.width)/24.0
            self.sq_rad = self.radius**2
            self.x_pad = (event.width - self.width)//2
            self.y_pad = (event.height - self.height)//2
            if self.container_type == CONTAINER_CALIB_CASSETTE:
                self.coordinates, self.labels = self._cassette_coordinates(self.width, self.height, calib=True)
            else:
                self.coordinates, self.labels = self._cassette_coordinates(self.width, self.height, calib=False)
        else:
            self.x_pad = 0
            self.y_pad = 0
            self.width = event.width
            self.height = event.height
            self.coordinates = {}
            self.labels = {}

    
    def do_expose_event(self, event):
        if using_cairo:
            context = self.window.cairo_create()
            context.rectangle(event.area.x, event.area.y,
                              event.area.width, event.area.height)
            context.clip()
            pcontext = self.get_pango_context()
            font_desc = pcontext.get_font_description()
            style = self.get_style()
            context.set_source_color(style.fg[self.state])
            context.set_font_size( font_desc.get_size()/pango.SCALE )
            self.draw_cairo(context)
        else:
            context = self.window.new_gc()
            style = self.get_style()
            context.foreground = style.fg[self.state]
            context.set_clip_origin(event.area.x, event.area.y)
            self.draw_gdk(context)
        return False

    def do_button_press_event(self, event):
        x, y = event.x, event.y
        for label, coord in self.coordinates.items():
            xl, yl = coord
            d2 = ((x - xl)**2 + (y - yl)**2)
            if d2 < self.sq_rad:
                ekey = '%s%s' % (self.container.location, label)
                if self.container.samples.get(label) is not None and self.container.samples[label][0] == PORT_GOOD:
                    self.emit('pin-selected', ekey)
                elif self.container[label][0] == PORT_UNKNOWN:
                    self.emit('probe-select', ekey)
        self.queue_draw()
        return True

    def do_motion_notify_event(self, event):
        if event.is_hint:
            x, y, state = event.window.get_pointer()
        else:
            x, y = event.x, event.y
        inside = False
        for label, coord in self.coordinates.items():
            xl, yl = coord
            d2 = ((x - xl)**2 + (y - yl)**2)
            if d2 < self.sq_rad:
                if self.container.samples.get(label) is not None and self.container.samples[label][0] == PORT_GOOD:
                    inside = True
                break  
        if inside:
            event.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.HAND2))
        else:
            event.window.set_cursor(None)                
        return True

    def draw_gdk(self, context):
        if self.container_type in [CONTAINER_NONE, CONTAINER_UNKNOWN, CONTAINER_EMPTY]:
            text = 'Empty or Undetermined'
            pl = self.create_pango_layout(text)
            iw, ih = pl.get_pixel_size()
            self.window.draw_layout(context, 
                                    self.x_pad + self.width/2 - iw/2,
                                    self.y_pad + self.height/2 - ih/2,pl)
            return
        # draw main labels
        _fd = pango.FontDescription() 
        _fd.merge(self.get_pango_context().get_font_description(), False)
        _fd.set_size(10240)
        for label, coord in self.labels.items():
            pl = self.create_pango_layout("%s" % (label))
            x, y = coord
            iw, ih = pl.get_pixel_size()
            self.window.draw_layout(context, x-iw/2, y-ih/2, pl)
        
        # draw pins
        _fd = pango.FontDescription() 
        _fd.merge(self.get_pango_context().get_font_description(), False)
        _fd.set_size(7168)
        for label, coord in self.coordinates.items():
            x, y = coord
            r = int(self.radius)
            port_state, port_descr = self.container.samples.get(label, [PORT_NONE,''])
            self.window.draw_arc(self.state_gc[port_state], True, x-r+1, y-r+1, r*2-1, r*2-1, 0, 23040)
            self.window.draw_arc(context, False, x-r+1, y-r+1, r*2-1, r*2-1, 0, 23040)
            pl = self.create_pango_layout(label)
            iw, ih = pl.get_pixel_size()
            self.window.draw_layout(context, x-iw/2+1, y-ih/2+1, pl)
    
    def draw_cairo(self, cr):
        if self.container_type in [CONTAINER_NONE, CONTAINER_UNKNOWN, CONTAINER_EMPTY]:
            text = 'Empty or Undetermined'
            x_b, y_b, w, h = cr.text_extents(text)[:4]
            cr.move_to(self.x_pad + self.width/2 - w/2,
                       self.y_pad + self.height/2 - h/2,
                       )
            cr.show_text(text)
            cr.stroke()
            return
           
        # draw main labels
        cr.set_font_size(14)
        cr.set_line_width(0.8)
        for label, coord in self.labels.items():
            x, y = coord
            x_b, y_b, w, h = cr.text_extents(label)[:4]
            cr.move_to(x - w / 2 - x_b, y - h / 2 - y_b)
            cr.show_text(label)
            cr.stroke()

        # draw pins
        cr.set_font_size(9)
        style = self.get_style()
        for label, coord in self.coordinates.items():
            x, y = coord
            r = self.radius
            port_state, port_descr = self.container.samples.get(label, (PORT_NONE,''))
            cr.set_source_color( self.port_colors[port_state] )
            cr.arc(x, y, r-1.0, 0, 2.0 * 3.14)
            cr.fill()
            cr.set_source_color(style.fg[self.state])
            cr.arc(x, y, r-1.0, 0, 2.0 * 3.14)
            cr.stroke()
            x_b, y_b, w, h = cr.text_extents(label)[:4]
            cr.move_to(x - w / 2 - x_b, y - h / 2 - y_b)
            cr.show_text(label)
            cr.stroke()

                

class SamplePicker(gtk.HBox):
    def __init__(self, automounter):
        gtk.HBox.__init__(self, homogeneous=False, spacing=6)       
        self.mounted = gtk.Entry()
        self.selected = gtk.Entry()
        self.mount_btn = gtk.Button('Mount')
        self.dismount_btn = gtk.Button('Dismount')
        self.wash_btn = gtk.CheckButton('Washing Enabled')
        self.automounter = automounter
        
        self.mounted.set_editable(False)
        self.selected.set_editable(False)
        self.mounted.set_width_chars(5)
        self.selected.set_width_chars(5)
        mnt_table = gtk.Table(4, 2, True)

        mnt_table.attach(self.selected, 0,1,2,3, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        mnt_table.attach(self.mounted, 0,1,3,4, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        mnt_table.attach(self.mount_btn, 1,2,2,3, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        mnt_table.attach(self.dismount_btn, 1,2,3,4, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        mnt_table.attach(self.wash_btn, 0,2,1,2, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        mnt_table.set_col_spacings(6)
        mnt_table.set_row_spacings(6)
        vbox = gtk.VBox(False,6)
        vbox.pack_start(mnt_table, expand=False, fill=False )
        vbox.pack_start(gtk.Label(''), expand=True, fill=True)
        self.pack_end( vbox, expand=False, fill=True )
        notebk = gtk.Notebook()
        self.containers = {}
        import random
        for k in ['Left','Middle','Right']:
            key = k[0]
            self.containers[key] = ContainerWidget(self.automounter.containers[key])
            tab_label = gtk.Label('%s' % k)
            tab_label.set_padding(12,0)
            notebk.insert_page( self.containers[key], tab_label=tab_label )
            self.containers[key].connect('pin-selected', self.on_pick)
        self.pack_start( notebk, expand=True, fill=True )
        self.mount_btn.connect('clicked', self.on_mount)
        self.dismount_btn.connect('clicked', self.on_dismount)
        
    
    def on_pick(self,obj, sel):
        self.selected.set_text(sel)
    
    def on_mount(self, obj):
        wash = self.wash_btn.get_active()
        port = self.selected.get_text()
        self.automounter.mount(port, wash)

    def on_dismount(self, obj):
        self.automounter.dismount()
        

gobject.type_register(ContainerWidget)
_TEST_STATE2 = '31uuu00000uujuuuuuuuuuuuuuuuuuuuu111111uuuuuuuuuuuuuuuuuuuuuuuuuu---\
-----------------------------41uuuuuuuuuuuumuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu\
uuuuuuuuuuuuuuuu0uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu20------uu------uu------\
uu------uu------uu------uu------uu------uu------uu------uu------uu------u'

if __name__ == '__main__':
       
    win = gtk.Window()
    win.set_border_width(6)

    rob = DummyAutomounter()
    p1 = SamplePicker(rob)
    gobject.timeout_add(5000, rob.set_state, _TEST_STATE2)
    
    win.add(p1)
    win.show_all()
    win.connect('destroy', lambda x: gtk.main_quit())
    gtk.main()
