import sys, os
import time
import logging
import pango
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

class Splash(object):
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
        self.vers = self.canvas.create_pango_layout('Version %s RC4' % (self.version))
       
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
        


