import sys, os
import time
import logging
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

        self.win.realize()
        self.pixbuf = gtk.gdk.pixbuf_new_from_file(image_file)
        self.pixmap, mask = self.pixbuf.render_pixmap_and_mask()
        width, height = self.pixmap.get_size()
        self.win.set_app_paintable(True)
        self.win.resize(width, height)
        self.win.connect('expose-event', self._paint)
        
        vbox = gtk.VBox(False,0)
        hbox = gtk.HBox(False, 0)

        #self.pbar = LinearProgress()
        #self.pbar.set_color(color, bg)
        #self.pbar.set_size_request(0,8)
        self.title = gtk.Label('<big><b>MX Data Collector</b></big>')
        self.title.set_use_markup(True)
        self.title.set_alignment(0,0.5)
        self.title.modify_fg( gtk.STATE_NORMAL, self.title.get_colormap().alloc_color(color) )
        
        self.log = gtk.Label('Initializing MXDC...')
        self.log.set_alignment(0,0.5)
        self.log.modify_fg( gtk.STATE_NORMAL, self.log.get_colormap().alloc_color(color) )
        self.vers = gtk.Label('Version %s RC3' % (self.version))
        self.vers.set_alignment(0.0, 0.5)
        self.vers.modify_fg(gtk.STATE_NORMAL, self.vers.get_colormap().alloc_color(color))
        vbox.set_spacing(6)
        vbox.set_border_width(12)
        vbox.pack_end(self.log, expand=False, fill=False)
        vbox.pack_end(self.vers, expand=False, fill=False)
        vbox.pack_end(self.title, expand=False, fill=False)
       
        self.win.add(vbox)
        self.win.set_position(gtk.WIN_POS_CENTER)                
        
#        log_handler = LabelHandler(self.log)
#        log_handler.setLevel(logging.INFO)
#        formatter = logging.Formatter('%(message)s')
#        log_handler.setFormatter(formatter)
#        logging.getLogger('').addHandler(log_handler)

        self._paint()        
        self.win.show_all()

    def _paint(self, obj=None, event=None):
        self.win.window.set_back_pixmap(self.pixmap, False)
        


