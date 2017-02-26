import os
import logging
import cairo
from gi.repository import Gtk, GdkPixbuf, Gdk

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class LabelHandler(logging.Handler):
    def __init__(self, label):
        logging.Handler.__init__(self)
        self.label = label
        self.count = 0
    
    def emit(self, record):
        self.label.set_markup(self.format(record))
   

class Splash(Gtk.Window):
    def __init__(self, version, image='splash.png'):
        super(Splash, self).__init__()
        self.img_file = os.path.join(DATA_DIR, image)
        self.version = version
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.img_file)
        self.width, self.height = pixbuf.get_width(), pixbuf.get_height()
        self.set_size_request(self.width, self.height)
        self.set_type_hint(Gdk.WindowTypeHint.SPLASHSCREEN)
        self.set_decorated(False)
        self.set_gravity(Gdk.Gravity.CENTER)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect('draw', self.on_expose)
        #self.connect('screen-changed', self.on_set_screen)
        #self.on_set_screen(self)
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
        window = widget.get_window()
        cr = window.cairo_create()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.0) # Transparent

        # Draw the background
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        img_src = cairo.ImageSurface.create_from_png(self.img_file)
        sp = cairo.SurfacePattern(img_src)
        sp.set_extend(cairo.EXTEND_REPEAT)
        cr = window.cairo_create()
        cr.set_source(sp)
        cr.paint()
        cr.set_source_rgb(0.2, 0.5, 0.7)
        cr.set_line_width(0.5)
        cr.move_to(32, self.height - 32)
        cr.select_font_face("Luxi Sans",
                cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

        cr.set_font_size(10)
        cr.text_path('Release %s' % self.version)
        cr.fill()
        #cr.stroke()
        #widget.shape_combine_mask(mask, 0, 0)
        
        return False
