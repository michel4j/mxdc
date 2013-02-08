import os
import math
import numpy
import gtk
import gobject
import pango
import time
try:
    import cairo
    using_cairo = True
except:
    using_cairo = False

from bcm.utils.automounter import *
from bcm.utils.log import get_module_logger
from bcm.utils.decorators import async
from bcm.engine import auto
from mxdc.widgets.textviewer import TextViewer
from mxdc.utils import gui
from bcm.beamline.interfaces import IBeamline
from twisted.python.components import globalRegistry
from mxdc.widgets.misc import ActiveProgressBar

_logger = get_module_logger('mxdc.samplepicker')

class _DummyEvent(object):
    width = 0
    height = 0

class ContainerWidget(gtk.DrawingArea):
    __gsignals__ = {
        'pin-selected': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      (gobject.TYPE_STRING,)),
        'probe-select': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      (gobject.TYPE_STRING,)),
        'pin-hover': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
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
        self.set_size_request(160,160)
        self.container.connect('changed', self.on_container_changed)
        self._last_hover_port = None
        self._tooltip = None
    
    def do_pin_selected(self, port):
        pass
    
    def do_probe_select(self, data):
        pass
    
    def do_pin_hover(self, port):
        pass
    
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
        window = self.get_window()
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
            self.state_gc[key] = window.new_gc()
            self.state_gc[key].foreground = self.get_colormap().alloc_color( spec )
        self._realized = True 
           
    
    def do_configure_event(self, event):
        if self.container_type == CONTAINER_PUCK_ADAPTER:
            self.height = min(event.width, event.height) - 12
            self.width = self.height
            self.radius = (self.width)/18.2
            self.sq_rad = self.radius**2
            self.x_pad = (event.width - self.width)//2
            self.y_pad = (event.height - self.height)//2
            self.coordinates, self.labels = self._puck_coordinates(self.width, self.height)
        elif self.container_type in [CONTAINER_CASSETTE, CONTAINER_CALIB_CASSETTE]:
            self.width = min(event.width, event.height*12/9.0)
            self.height = self.width*9/12.0
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
        window = self.get_window()
        if using_cairo:
            context = window.cairo_create()
            context.rectangle(event.area.x, event.area.y,
                              event.area.width, event.area.height)
            context.clip()
            pcontext = self.get_pango_context()
            font_desc = pcontext.get_font_description()
            context.select_font_face(font_desc.get_family(), cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            style = self.get_style()
            context.set_source_color(style.fg[self.state])
            context.set_font_size( font_desc.get_size()/pango.SCALE )
            self.draw_cairo(context)
        else:
            context = window.new_gc()
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
        _cur_port = None
        for label, coord in self.coordinates.items():
            xl, yl = coord
            d2 = ((x - xl)**2 + (y - yl)**2)
            if d2 < self.sq_rad:
                if self.container.samples.get(label) is not None and self.container.samples[label][0] not in [PORT_EMPTY]:
                    inside = True
                    _cur_port = '%s%s' % (self.container.location, label)
                break  
        if _cur_port != self._last_hover_port:
            if not inside:
                event.window.set_cursor(None)
            else:
                event.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.HAND2))
            self.emit('pin-hover', _cur_port)
            self._last_hover_port = _cur_port

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
            if self.container_type in [CONTAINER_NONE, CONTAINER_EMPTY]:
                text = 'Automounter Location is Empty'
            else:
                text = 'Container type is Unknown'
            x_b, y_b, w, h = cr.text_extents(text)[:4]
            cr.move_to(self.x_pad + self.width/2 - w/2,
                       self.y_pad + self.height/2 - h/2,
                       )
            cr.show_text(text)
            cr.stroke()
            return
           
        # draw main labels
        cr.set_font_size(15)
        cr.set_line_width(0.85)
        cr.set_source_color( gtk.gdk.color_parse("#3232ff") )
        for label, coord in self.labels.items():
            x, y = coord
            x_b, y_b, w, h = cr.text_extents(label)[:4]
            cr.move_to(x - w/2.0 - x_b, y - h/2.0 - y_b)
            cr.show_text(label)
            cr.stroke()


        # draw pins
        cr.set_font_size(10)
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
            x_b, y_b, w, h = cr.text_extents(label[1:])[:4]
            cr.move_to(x - w/2.0 - x_b, y - h/2.0 - y_b)
            cr.show_text(label[1:])
            cr.stroke()
            

                      

class SamplePicker(gtk.HBox):
    __gsignals__ = {
        'pin-hover': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      (gobject.TYPE_PYOBJECT, gobject.TYPE_STRING,)),
    }
    def __init__(self, automounter=None):
        gtk.HBox.__init__(self)
        self._xml = gui.GUIFile(os.path.join(os.path.dirname(__file__), 'data/sample_picker'),
                                  'sample_picker')
        
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
            self.automounter = self.beamline.automounter
        except:
            self.beamline = None
            self.automounter = automounter
            _logger.error('No registered beamline found.')

        self.pack_start(self.sample_picker, True, True, 0)
        pango_font = pango.FontDescription('sans 8')
        self.status_lbl.modify_font(pango_font)
        self.lbl_port.modify_font(pango_font)
        self.lbl_barcode.modify_font(pango_font)
        self.throbber.set_from_stock('robot-idle', gtk.ICON_SIZE_LARGE_TOOLBAR)
        self.message_log = TextViewer(self.msg_txt)
        self.message_log.set_prefix('-')
        
        self.containers = {}
        for k in ['Left', 'Middle', 'Right']:
            key = k[0]
            self.containers[key] = ContainerWidget(self.automounter.containers[key])
            tab_label = gtk.Label('%s' % k)
            tab_label.set_padding(12, 0)
            self.notebk.insert_page(self.containers[key], tab_label=tab_label)
            self.containers[key].connect('pin-selected', self.on_pick)
            self.containers[key].connect('pin-hover', self.on_hover)
        self.mount_btn.connect('clicked', self.on_mount)
        self.dismount_btn.connect('clicked', self.on_dismount)
        self.automounter.connect('progress', self.on_progress)
        self.automounter.connect('message', self.on_state_changed)
        self.automounter.connect('status', self.on_state_changed)
        self.automounter.connect('active', self.on_state_changed)
        self.automounter.connect('busy', self.on_state_changed)
        self.automounter.connect('health', self.on_state_changed)
        self.automounter.connect('enabled', self.on_state_changed)
        self.automounter.connect('mounted', self.on_sample_mounted)

        self._full_state = []
        
        # extra widgets
        self._animation = gtk.gdk.PixbufAnimation(os.path.join(os.path.dirname(__file__),
                                                               'data/active_stop.gif'))
        
        #add progressbar
        self.pbar = ActiveProgressBar()
        self.pbar.set_fraction(0.0)
        self.pbar.idle_text('')
        self.control_box.pack_end(self.pbar, expand=False, fill=False)
        self.pbar.modify_font(pango_font)
        
               
                
    def __getattr__(self, key):
        try:
            return super(SamplePicker).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
        
    def do_pin_hover(self, cont, port):
        pass
    
    def pick_port(self, port):
        if port is not None:
            self.selected.set_text(port)
            self.mount_btn.set_sensitive(True)
        else:
            self.selected.set_text('')
            self.mount_btn.set_sensitive(False)
    
    def on_hover(self, obj, port):
        self.emit('pin-hover', obj, port)
                        
    def on_pick(self, obj, sel):
        self.selected.set_text(sel)
        self.mount_btn.set_sensitive(True)
    
    def on_mount(self, obj):
        if not self.command_active:
            wash = self.wash_btn.get_active()
            port = self.selected.get_text()
            self.mount_btn.set_sensitive(False)
            if port.strip() == '':
                return
            self._set_throbber("busy")
            message = "<span color='blue'>Preparing to mount %s.</span>" % port
            self.status_lbl.set_markup(message)
            self.execute_mount(port, wash)
            self.selected.set_text('')
    
    @async
    def execute_mount(self, port, wash):
        try:
            self.command_active = True
            auto.auto_mount_manual(self.beamline, port, wash)
        except:
            _logger.error('Sample mounting failed')
        self.command_active = False
        
    @async
    def execute_dismount(self, port):
        try:
            self.command_active = True
            auto.auto_dismount_manual(self.beamline, port)
        except:
            _logger.error('Sample dismounting failed')
        self.command_active = False
                

    def on_dismount(self, obj):
        if not self.command_active:
            port = self.mounted.get_text().strip()
            self.mount_btn.set_sensitive(False)
            self._set_throbber("busy")
            message = "<span color='blue'>Preparing to dismount %s.</span>" % port
            self.status_lbl.set_markup(message)            
            self.execute_dismount(port)
    
    def on_progress(self, obj, state):
        val, tool_pos, sample_pos, magnet_pos = state
        self.pbar.set_fraction(val)
        self.message_log.add_text(time.strftime('-- %a %H:%M:%S --'))
        self.message_log.add_text('Gripper: %s.' % tool_pos)
        self.message_log.add_text('Sample: %s.' % sample_pos)
        self.message_log.add_text('Magnet: %s.' % magnet_pos)
    
                   
    def _set_throbber(self, st):
        if st == 'error':
            self.throbber.set_from_stock('robot-error', gtk.ICON_SIZE_LARGE_TOOLBAR)
        elif st == 'standby':
            self.throbber.set_from_stock('robot-standby', gtk.ICON_SIZE_LARGE_TOOLBAR)
        elif st == 'warning':
            self.throbber.set_from_stock('robot-warning', gtk.ICON_SIZE_LARGE_TOOLBAR)
        elif st == 'busy':
            self.throbber.set_from_animation(self._animation)
        elif st == 'idle':
            self.throbber.set_from_stock('robot-idle', gtk.ICON_SIZE_LARGE_TOOLBAR)
        elif st == 'setup':
            self.throbber.set_from_stock('robot-setup', gtk.ICON_SIZE_LARGE_TOOLBAR)

            
    def on_state_changed(self, obj, val):
        code, h_msg = self.automounter.health_state
        status = self.automounter.status_state
        message = self.automounter.message_state
        busy = self.automounter.busy_state
        enabled = self.automounter.enabled_state
        active = self.automounter.active_state
        
        # Do nothing if the state has not really changed
        _new_state = [code, h_msg, status, message, busy, enabled, active]
        if _new_state == self._full_state:
            return
        else:
            self._full_state = _new_state
            
        if code == 16: 
            self._set_throbber('warning')
        elif code >= 2:
            self._set_throbber('error')
        else:
            if not busy:
                self._set_throbber(status)
            else:
                self._set_throbber('busy') 
        if message.strip() == "":
            message = h_msg

        message = "<span color='blue'>%s</span>" % message.strip()
        if h_msg.strip() != '':
            self.message_log.add_text(h_msg)
        self.status_lbl.set_markup(message) 

        if status == 'idle' and code <= 2 and not busy:
            self.command_tbl.set_sensitive(True)
        else:
            self.command_tbl.set_sensitive(False)
            self.pbar.set_text('')        
        
    
    def on_sample_mounted(self, obj, info):
        if info is None: # dismounting
            self.mounted.set_text('')
            self.lbl_port.set_markup('')
            self.lbl_barcode.set_markup('')
            self.dismount_btn.set_sensitive(False)
        else:   
            port, barcode = info
            if port is not None:
                self.mounted.set_text(port)
                self.lbl_port.set_markup("<span color='blue'>%s</span>" % port)
                self.lbl_barcode.set_markup("<span color='blue'>%s</span>" % barcode)
                self.dismount_btn.set_sensitive(True)
                if self.selected.get_text().strip() == port:
                    self.selected.set_text('')
                    self.mount_btn.set_sensitive(False)
            else:
                self.mounted.set_text('')
                self.lbl_port.set_markup('')
                self.lbl_barcode.set_markup('')
                self.dismount_btn.set_sensitive(False)

    def show_info(self, data):
        self.hide_info()
        if data is not None:
            self.info_lbl.set_markup("<span color='blue'>%s</span>" %data)
    
    def hide_info(self):
        self.info_lbl.set_markup("")
