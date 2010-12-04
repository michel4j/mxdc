import sys, os
import time
import logging
import pango
import cairo
import gtk, gobject

from mxdc.widgets.misc import LinearProgress

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class LabelHandler(logging.Handler):
    def __init__(self, label):
        logging.Handler.__init__(self)
        self.label = label
        self.count = 0
    
    def emit(self, record):
        self.label.set_markup(self.format(record))
        #while gtk.events_pending():
        #    gtk.main_iteration()

class Splash1(object):
    def __init__(self, version, color=None, bg=None):
        image_file = os.path.join(DATA_DIR, 'cool-splash.png')
        self.version = version
        self.win = gtk.Window()
        self.win.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_SPLASHSCREEN)
        self.win.set_gravity(gtk.gdk.GRAVITY_CENTER)
    
        self.canvas = gtk.DrawingArea()

        self.win.realize()
        self.pixbuf = gtk.gdk.pixbuf_new_from_file(image_file)
        self.width, self.height = self.pixbuf.get_width(), self.pixbuf.get_height()
        self.win.resize(self.width, self.height)
        self.canvas.set_size_request(self.width, self.height)
        self.win.add(self.canvas)
        self.canvas.connect('expose-event', self._paint)
        
        self.title = self.canvas.create_pango_layout('')
        self.title.set_markup('<big><b>MX Data Collector</b></big>')
        self.log = self.canvas.create_pango_layout('Initializing MXDC...')
        self.vers = self.canvas.create_pango_layout('Version %s' % (self.version))
       
        self.win.set_position(gtk.WIN_POS_CENTER)                
        
#        log_handler = LabelHandler(self.log)
#        log_handler.setLevel(logging.INFO)
#        formatter = logging.Formatter('%(message)s')
#        log_handler.setFormatter(formatter)
#        logging.getLogger('').addHandler(log_handler)

        self._paint()        
        self.win.show_all()

    def _paint(self, obj=None, event=None):
        self.style = self.canvas.get_style()
        self.canvas.window.draw_pixbuf(self.style.fg_gc[gtk.STATE_NORMAL], self.pixbuf, 0, 0, 0, 0)
        self.canvas.window.draw_layout(self.style.bg_gc[gtk.STATE_NORMAL], 20, self.height/2, self.title)
        self.canvas.window.draw_layout(self.style.bg_gc[gtk.STATE_NORMAL], 20, self.height/2 + 20, self.vers)
        self.canvas.window.draw_layout(self.style.bg_gc[gtk.STATE_NORMAL], 20, self.height/2 + 40, self.log)
        

class Splash(gtk.Window):
    def __init__(self, version, image='cool-splash.png'):
        gtk.Window.__init__(self)
        self.img_file = os.path.join(DATA_DIR, image)
        self.version = version
        pixbuf = gtk.gdk.pixbuf_new_from_file(self.img_file)
        self.width, self.height = pixbuf.get_width(), pixbuf.get_height()
        self.set_size_request(self.width, self.height)
        self.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_SPLASHSCREEN)
        self.set_gravity(gtk.gdk.GRAVITY_CENTER)
        self.set_position(gtk.WIN_POS_CENTER)
        self.connect('expose-event', self.on_expose)
        self.connect('screen-changed', self.on_set_screen)
        self.on_set_screen(self)
        self.set_app_paintable(True)
    
    def on_set_screen(self, widget, old_screen=None):
        # To check if the display supports alpha channels, get the colormap
        screen = widget.get_screen()
        colormap = screen.get_rgba_colormap()
        if colormap == None:
            colormap = screen.get_rgb_colormap()
            self.supports_alpha = False
        else:
            self.supports_alpha = True
    
        # Now we have a colormap appropriate for the screen, use it
        widget.set_colormap(colormap)
    
    def on_expose(self, widget, event):
        cr = widget.window.cairo_create()
                
        if self.supports_alpha:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.0) # Transparent
        else:
            cr.set_source_rgb(1.0, 1.0, 1.0) # Opaque white
            
        # Draw the background
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        pixbuf = gtk.gdk.pixbuf_new_from_file(self.img_file)
        pix, mask = pixbuf.render_pixmap_and_mask(230)
        cr = widget.window.cairo_create()
        cr.set_source_pixbuf(pixbuf,0,0)
        cr.paint()
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(0.5)
        cr.move_to(16, self.height - 32)
        cr.select_font_face("Luxi Sans",
                cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

        cr.set_font_size(10)
        cr.text_path('ver. %s' % self.version)
        cr.fill()
        #cr.stroke()
        #widget.shape_combine_mask(mask, 0, 0)
        
        return False
