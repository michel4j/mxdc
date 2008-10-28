import numpy
import gtk
import gobject
import pango
try:
    import cairo
    using_cairo = True
except:
    using_cairo = False
    
       
class PuckWidget(gtk.DrawingArea):
    __gsignals__ = {
        'pin-clicked': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      (gobject.TYPE_STRING,)),
        'expose-event': 'override',
        'configure-event': 'override',
    }
    def __init__(self, position=''):
        gtk.DrawingArea.__init__(self)
        self.set_app_paintable(True)
        self.position = position
        self.setup()
        self.state_rgba = {
            'unknown' : "#FFFFFF",
            'good': "#90dc8f",
            'bad': "#ff6464",
            'empty': "#999999",
            'mounted': "#dd5cdc"
        }
        self.set_events(gtk.gdk.EXPOSURE_MASK |
                gtk.gdk.LEAVE_NOTIFY_MASK |
                gtk.gdk.BUTTON_PRESS_MASK |
                gtk.gdk.POINTER_MOTION_MASK |
                gtk.gdk.POINTER_MOTION_HINT_MASK|
                gtk.gdk.VISIBILITY_NOTIFY_MASK)  
        self.queue_draw()
           
    def setup(self):
        self.black_gc = None 
        self.ilenf = 140/394.
        self.olenf = 310/394.
        self.loc = {}
        for i in range(16):
            self.loc[i+1] = [0, 0, True, 0, 0.0, 'unknown']
        self.id_label = self.create_pango_layout(self.position)
        self.id_label.set_font_description(pango.FontDescription('Sans 10'))
            
        
    def calc_coordinates(self, width, height):
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
            
    def do_expose_event(self, event):
        global using_cairo
        if self.black_gc is None:
            self.window.clear()
            self.black_gc = self.window.new_gc()
            self.grey_gc =  self.window.new_gc()
            self.dark_grey_gc = self.window.new_gc()
            style = self.get_style()
            self.black_gc.foreground = style.fg[gtk.STATE_NORMAL]
            self.grey_gc.foreground = self.get_colormap().alloc_color( gtk.gdk.color_parse('#bab9b9') )
            self.dark_grey_gc.foreground = self.get_colormap().alloc_color( gtk.gdk.color_parse('#666666') )
            self.lgc = {}
            for k,col in self.state_rgba.items():
                self.lgc[k] = self.window.new_gc()
                self.lgc[k].foreground = self.get_colormap().alloc_color( gtk.gdk.color_parse(col) )
            
        if using_cairo:
            context = self.window.cairo_create()
            context.rectangle(event.area.x, event.area.y, event.area.width, event.area.height)
            context.clip()
            self.draw_cairo(context)
        else:
            self.draw_gdk()
        return False

    def do_configure_event(self, event):
        self.calc_coordinates(self.allocation.width, self.allocation.height)
        return False
        
    def draw_gdk(self):
        self.window.draw_arc(self.grey_gc, True, 1, 1, self.allocation.width-2, self.allocation.width-2, 0, 23040)
        #self.window.draw_arc(self.black_gc, False, 1, 1, self.allocation.width-2, self.allocation.width-2, 0, 23040)
        iw, ih = self.id_label.get_pixel_size()
        self.window.draw_layout(self.black_gc, int(self.hw-iw/2), int(self.hw-ih/2), self.id_label)
        for key, loc in self.loc.items():
            x,y = loc[:2]
            rad = self.radius
            self.window.draw_arc(self.lgc[ loc[-1] ], True, x-rad, y-rad, rad*2, rad*2, 0, 23040)
            self.window.draw_arc(self.black_gc, False, x-rad, y-rad, rad*2, rad*2, 0, 23040)
            pl = self.create_pango_layout("%s" % (key))
            pl.set_font_description(pango.FontDescription('Sans 6'))
            iw, ih = pl.get_pixel_size()
            self.window.draw_layout(self.dark_grey_gc, x-iw/2, y-ih/2, pl)

    def draw_cairo(self, cr):
        cr.set_line_width(2.0)
        cr.set_source_rgba( 0.5,0.5,0.5,0.5)
        cr.arc(self.hw, self.hw, self.hw-1, 0, 2.0*3.14)
        cr.fill()
        cr.set_source_rgba(0.0,0.0,0.0,1.0)
        cr.set_font_size(20)
        text = self.position
        x_b, y_b, w, h = cr.text_extents(text)[:4]
        cr.move_to(self.hw-w/2 - x_b, self.hw-h/2 -y_b)
        cr.show_text(text)
        cr.stroke()

        cr.set_line_width(1.5)
        cr.set_font_size(10)
        for key, loc in self.loc.items():
            x, y = loc[:2]
            col = loc[-1]
            cr.set_source_rgba(0.0,0.0,0.0,1.0)
            cr.arc(x,y, self.radius, 0, 2.0*3.14)
            cr.stroke()        
            cr.set_source_color(gtk.gdk.color_parse(self.state_rgba[col]))
            cr.arc(x,y, self.radius, 0, 2.0*3.14)
            cr.fill()
            cr.set_source_rgba(0.0,0.0,0.0,1.0)
            text = '%d' % key
            x_b, y_b, w, h = cr.text_extents(text)[:4]
            cr.move_to(x-w/2 - x_b, y-h/2 -y_b)
            cr.set_source_rgba(0.3,0.3,0.3,0.6)
            cr.show_text(text)
            cr.stroke()
                        
    def do_button_press_event(self, event):
        x, y = event.x, event.y
        states = ['good', 'bad', 'mounted']
        sel_state = states[event.button -1]
        for key, loc in self.loc.items():
            xl, yl = loc[:2]
            d2 = ((x - xl)**2 + (y - yl)**2)
            if d2 < self.sq_rad:
                loc[-1] = sel_state
                ekey = '%s%s' % (self.position, key)
                self.emit('pin-clicked', ekey)
        self.queue_draw()
        return True

    def do_motion_notify_event(self, event):
        if event.is_hint:
            x, y, state = event.window.get_pointer()
        else:
            x, y = event.x, event.y
        inside = False
        for key, loc in self.loc.items():
            xl, yl = loc[:2]
            d2 = ((x - xl)**2 + (y - yl)**2)
            if d2 < self.sq_rad:
                inside = True
                break
         
        if inside:
            event.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.HAND2))
        else:
            event.window.set_cursor(None)
                            
        return True

class CassetteWidget(PuckWidget):

    def __init__(self, position=''):
        PuckWidget.__init__(self, position)
           
    def setup(self):
        self.black_gc = None 
        self.loc = {}
        for c in 'ABCDEFGHIJKL':
            for i in range(8):
                loc_key = "%c%1d" % (c, i+1)
                self.loc[loc_key] = [0, 0, True, 0, 0.0, 'unknown']
                    
    def calc_coordinates(self,width, height):
        self.radius = (width-4.0)/24.0
        self.sq_rad = self.radius*self.radius
        self.label_coords = {}
        keys ='ABCDEFGHIJKL'
        for i in range(12):
            x = int(( 2 * i + 1) * self.radius )+2
            self.label_coords[keys[i]] = [x,int(self.radius+2),int(height-self.radius-2)]
            for j in range(8):
                loc_key = "%c%1d" % (keys[i], j+1)
                y = int(( 2 * j + 1) * self.radius )+ 2.0*self.radius
                self.loc[loc_key][0] = x
                self.loc[loc_key][1] = y
                
    def draw_gdk(self):
        self.window.draw_rectangle(self.grey_gc, True, 1, 1, self.allocation.width-2, self.allocation.width-2 )
        for key, coords in self.label_coords.items():
            pl = self.create_pango_layout("%s" % (key))
            pl.set_font_description(pango.FontDescription('Sans 10'))
            iw, ih = pl.get_pixel_size()
            self.window.draw_layout(self.black_gc, coords[0]-iw/2, coords[1]-ih/2, pl)
            self.window.draw_layout(self.black_gc, coords[0]-iw/2, coords[2]-ih/2, pl)
        self.window.draw_line(self.dark_grey_gc, 2, self.allocation.height/2-2, self.allocation.width-2, self.allocation.height/2-2 )
        for key, loc in self.loc.items():
            x,y = int(loc[0]), int(loc[1])
            rad = int(self.radius)-1
            self.window.draw_arc(self.lgc[ loc[-1] ], True, x-rad, y-rad, rad*2, rad*2, 0, 23040)
            self.window.draw_arc(self.black_gc, False, x-rad, y-rad, rad*2, rad*2, 0, 23040)
            pl = self.create_pango_layout("%s" % (key[1:]))
            pl.set_font_description(pango.FontDescription('Sans 6'))
            iw, ih = pl.get_pixel_size()
            self.window.draw_layout(self.dark_grey_gc, x-iw/2, y-ih/2, pl)

    def draw_cairo(self, cr):
        cr.set_line_width(1.0)
        cr.set_source_rgba( 0.5,0.5,0.5,0.5)
        cr.rectangle(1, 1, self.allocation.width-2, self.allocation.height-2)
        cr.fill()
        cr.set_source_rgba(0.0,0.0,0.0,1.0)
        for key, coords in self.label_coords.items():
            cr.set_source_rgba(0.0,0.0,0.0,1.0)
            cr.set_font_size(12)
            x_b, y_b, w, h = cr.text_extents(key)[:4]
            cr.move_to(coords[0]-w/2 - x_b, coords[1]-h/2 -y_b)
            cr.show_text(key)
            cr.stroke()
            cr.move_to(coords[0]-w/2 - x_b, coords[2]-h/2 -y_b)
            cr.show_text(key)
            cr.stroke()
        cr.set_source_rgba( 0.3,0.3,0.3,0.5)
        cr.set_line_width(2.0)
        cr.move_to(2,self.allocation.height/2-2)
        cr.line_to(self.allocation.width-1, self.allocation.height/2-2)
        cr.stroke()

        cr.set_line_width(1.5)
        cr.set_font_size(10)
        for key, loc in self.loc.items():
            x, y = loc[:2]
            col = loc[-1]
            cr.set_source_rgba(0.0,0.0,0.0,1.0)
            cr.arc(x,y, self.radius-1, 0, 2.0*3.14)
            cr.stroke()        
            cr.set_source_color(gtk.gdk.color_parse(self.state_rgba[col]))
            cr.arc(x,y, self.radius-1, 0, 2.0*3.14)
            cr.fill()
            cr.set_source_rgba(0.0,0.0,0.0,1.0)
            text = '%s' % key[1:]
            x_b, y_b, w, h = cr.text_extents(text)[:4]
            cr.move_to(x-w/2 - x_b, y-h/2 -y_b)
            cr.set_source_rgba(0.3,0.3,0.3,0.6)
            cr.show_text(text)
            cr.stroke()
                        
                
class PuckAdapter(gtk.AspectFrame):
    __gsignals__ = {
        'pin-clicked': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      (gobject.TYPE_STRING,))
    }
    def __init__(self, position):
        gtk.AspectFrame.__init__(self, xalign=0.5, yalign=0.5, ratio=1.0, obey_child=False)
        self.set_shadow_type(gtk.SHADOW_NONE)
        tab = gtk.Table(rows=2, columns=2, homogeneous=True)
        tab.set_row_spacings(3)
        tab.set_col_spacings(6)
        self.pucks = {}
        self.position = position
        for k in ['A','B','C','D']:
            self.pucks[k] = PuckWidget(k)
            self.pucks[k].connect('pin-clicked', self.__on_pin_picked)
        tab.attach(self.pucks['A'], 0,1,0,1, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        tab.attach(self.pucks['B'], 0,1,1,2, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        tab.attach(self.pucks['C'], 1,2,0,1, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        tab.attach(self.pucks['D'], 1,2,1,2, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        self.add(tab)
    
    def __on_pin_picked(self, puck, address):
        loc = "%c%s" % (self.position.upper()[0], address)
        self.emit('pin-clicked', loc)

class CassetteAdapter(gtk.AspectFrame):
    __gsignals__ = {
        'pin-clicked': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      (gobject.TYPE_STRING,))
    }
    def __init__(self, position):
        gtk.AspectFrame.__init__(self, xalign=0.5, yalign=0.5, ratio=1.2, obey_child=False)
        self.set_shadow_type(gtk.SHADOW_NONE)
        tab = gtk.Table(rows=1, columns=1, homogeneous=True)     
        tab.set_row_spacings(6)
        tab.set_col_spacings(6)
        self.cassette = CassetteWidget()
        self.position = position
        tab.attach(self.cassette, 0,1,0,1, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        self.cassette.connect('pin-clicked', self.__on_pin_picked)
        self.add(tab)
    
    def __on_pin_picked(self, cassette, address):
        loc = "%c%s" % (self.position.upper()[0], address)
        self.emit('pin-clicked', loc)

class SamplePicker(gtk.HBox):
    def __init__(self):
        gtk.HBox.__init__(self,homogeneous=False, spacing=6)       
        self.mounted = gtk.Entry()
        self.selected = gtk.Entry()
        self.mount_btn = gtk.Button('Mount')
        self.unmount_btn = gtk.Button('Un-mount')
        self.wash_btn = gtk.Button('Wash Sample')
        
        self.mounted.set_editable(False)
        self.selected.set_editable(False)
        self.mounted.set_width_chars(10)
        self.selected.set_width_chars(10)
        mnt_table = gtk.Table(2,2,False)

        mnt_table.attach(self.selected, 0,1,0,1, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        mnt_table.attach(self.mounted, 0,1,1,2, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        mnt_table.attach(self.mount_btn, 1,2,0,1, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        mnt_table.attach(self.unmount_btn, 1,2,1,2, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        mnt_table.attach(self.wash_btn, 1,2,2,3, xoptions=gtk.EXPAND|gtk.FILL,yoptions=gtk.EXPAND|gtk.FILL)
        vbox = gtk.VBox(False,6)
        vbox.pack_start(mnt_table, expand=False, fill=False )
        vbox.pack_start(gtk.Label(''), expand=True, fill=True)
        self.pack_end( vbox, expand=False, fill=True )
        notebk = gtk.Notebook()
        notebk.set_size_request(320,320)
        self.adapters = {}
        for k in ['Left','Middle','Right']:
            if k=='Middle':
                self.adapters[k] = CassetteAdapter(k)
            else:
                self.adapters[k] = PuckAdapter(k)
            self.adapters[k].set_border_width(6)
            tab_label = gtk.Label('%s' % k)
            tab_label.set_padding(12,0)
            notebk.insert_page( self.adapters[k], tab_label=tab_label )
            self.adapters[k].connect('pin-clicked', self.on_pick)
        self.pack_start( notebk, expand=True, fill=True )
        
    
    def on_pick(self,obj, sel):
        self.selected.set_text(sel)
        
gobject.type_register(PuckWidget)
gobject.type_register(CassetteWidget)
gobject.type_register(PuckAdapter)
gobject.type_register(CassetteAdapter)

if __name__ == '__main__':
       
    win = gtk.Window()
    win.set_border_width(6)
    p1 = SamplePicker()

    win.add(p1)
    win.show_all()
    win.connect('destroy', lambda x: gtk.main_quit())
    gtk.main()
