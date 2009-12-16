import os
import math
import numpy
import gtk
import gtk.glade
import gobject
import pango
try:
    import cairo
    using_cairo = True
except:
    using_cairo = False

from bcm.utils.automounter import *
from bcm.device.automounter import Automounter, DummyAutomounter
from mxdc.widgets.gauge import Gauge

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
        self.set_size_request(290,290)
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
                if self.container.samples.get(label) is not None and self.container.samples[label][0] in [PORT_GOOD, PORT_UNKNOWN]:
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
                if self.container.samples.get(label) is not None and self.container.samples[label][0] in [PORT_GOOD, PORT_UNKNOWN]:
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


def _format_error_string(state):
    nd_dict = {
        'calib': 'calibration',
        'inspect': 'inspection',
        'action': 'action'
    }
    needs = []
    if not state['healthy']:
        needs_txt = 'Not normal'
    else:
        needs_txt = ''
    for t in state['needs']:
        ts = t.split(':') 
        if len(ts)>1:
            needs.append(ts[1] +' '+ nd_dict[ts[0]])
        else:
            needs.append(t)
    if len(needs) > 0:
        needs_txt = 'Needs ' + '; '.join(needs)
    if len(state['diagnosis']) > 0:
        needs_txt += ' because: ' + '; '.join(state['diagnosis'])
    
    return needs_txt
                      

class SamplePicker(gtk.Frame):
    def __init__(self, automounter):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        self._xml = gtk.glade.XML(os.path.join(os.path.dirname(__file__), 'data/sample_picker.glade'), 
                                  'sample_picker')
        self.add(self.sample_picker)
        self.automounter = automounter
        pango_font = pango.FontDescription('Monospace 7')
        self.msg_view.modify_font(pango_font)
        
        self.containers = {}
        for k in ['Left','Middle','Right']:
            key = k[0]
            self.containers[key] = ContainerWidget(self.automounter.containers[key])
            tab_label = gtk.Label('%s' % k)
            tab_label.set_padding(12,0)
            self.notebk.insert_page( self.containers[key], tab_label=tab_label )
            self.containers[key].connect('pin-selected', self.on_pick)
        self.mount_btn.connect('clicked', self.on_mount)
        self.dismount_btn.connect('clicked', self.on_dismount)
        self.automounter.connect('progress', self.on_progress)
        self.automounter.connect('message', self.on_message)
        self.automounter.connect('state', self.on_state)
        self.automounter.connect('mounted', self.on_sample_mounted)
        
        # layout the gauge section
        self.ln2_gauge = Gauge(0,100,5,3)
        self.ln2_gauge.set_property('units','% LN2')
        self.ln2_gauge.set_property('low', 70.0)
        self.level_frame.add(self.ln2_gauge)
        self.automounter.nitrogen_level.connect('changed', self._on_level)
        
        
    def __getattr__(self, key):
        try:
            return super(SamplePicker).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
    
    def _on_level(self, obj, val):
        self.ln2_gauge.value = val
        return False

    def on_pick(self,obj, sel):
        self.selected.set_text(sel)
        self.mount_btn.set_sensitive(True)
    
    def on_mount(self, obj):
        wash = self.wash_btn.get_active()
        port = self.selected.get_text()
        if port.strip() == '':
            self.mount_btn.set_sensitive(False)
            return
        self.automounter.mount(port, wash)
        self.selected.set_text('')
        self.mount_btn.set_sensitive(False)

    def on_dismount(self, obj):
        port = self.mounted.get_text().strip()
        self.automounter.dismount(port)
    
    def on_progress(self, obj, val):
        self.pbar.set_fraction(val)
    
    def on_message(self, obj, str):
        self.msg_view.get_buffer().set_text(str)
            
    def on_state(self, obj, state):
        needstxt = _format_error_string(state)
        self.msg_view.get_buffer().set_text(needstxt)
        statustxt = ''
        if state['healthy']:
            statustxt += '- Normal\n'
        else:
            statustxt += '- Not Normal\n'
        if state['busy']:
            statustxt += '- Busy\n'
            self.command_tbl.set_sensitive(False)
        else:
            statustxt += '- Idle\n'
            self.command_tbl.set_sensitive(True)
            
        
        self.status_lbl.set_markup(statustxt)
    
    def on_sample_mounted(self, obj, port):
        if port is not None:
            self.mounted.set_text(port)
            self.dismount_btn.set_sensitive(True)
            if self.selected.get_text().strip() == port:
                self.selected.set_text('')
                self.mount_btn.set_sensitive(False)
        else:
            self.mounted.set_text('')
            self.dismount_btn.set_sensitive(False)

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
