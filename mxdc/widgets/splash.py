import gtk, gobject
import sys, os
import logging
from mxdc.widgets.misc import LinearProgress

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class LabelHandler(logging.Handler):
    def __init__(self, label):
        logging.Handler.__init__(self)
        self.label = label
        self.count = 0
    
    def emit(self, record):
        self.label.set_markup(self.format(record))

class Splash(object):
    def __init__(self, duration=2.0, color=None, bg=None):
        image_file = os.path.join(DATA_DIR, 'cool-splash.png')
        self.win = gtk.Window()
        self.win.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_SPLASHSCREEN)
        self.win.set_gravity(gtk.gdk.GRAVITY_CENTER)

        pixbuf = gtk.gdk.pixbuf_new_from_file(image_file)
        pixmap, mask = pixbuf.render_pixmap_and_mask()
        width, height = pixmap.get_size()
        self.win.set_app_paintable(True)
        self.win.resize(width, height)
        self.win.realize()
        self.win.window.set_back_pixmap(pixmap, False)
        
        self.version = '2.5.9'
        
        vbox = gtk.VBox(False,0)
        hbox = gtk.HBox(False, 0)

        self.pbar = LinearProgress()
        self.pbar.set_color(color, bg)
        self.pbar.set_size_request(0,8)
        self.log = gtk.Label('Initializing MXDC...')
        self.log.modify_fg( gtk.STATE_NORMAL, self.log.get_colormap().alloc_color(color) )
        self.log.set_alignment(0,0.5)
        vbox.pack_end(self.pbar, expand=False, fill=False)
        vbox.pack_end(self.log, expand=False, fill=False)
        self.vers = gtk.Label('Version %s' % (self.version))
        self.vers.set_alignment(1.0, 0.5)
        self.vers.modify_fg(gtk.STATE_NORMAL, self.vers.get_colormap().alloc_color(color))
        vbox.pack_end(self.vers, expand=False, fill=False)
        vbox.set_spacing(6)
        vbox.set_border_width(12)
        
        self.win.add(vbox)
        self.win.set_position(gtk.WIN_POS_CENTER)                
        self.win.show_all()
        self.win.realize()
        self._prog = 0
        
        log_handler = LabelHandler(self.log)
        log_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        log_handler.setFormatter(formatter)
        logging.getLogger('').addHandler(log_handler)
        
        
        self.win.show_all()
        gobject.timeout_add(int(duration*1000/100.0), self._run_splash)
        
    def set_version(self, version):
        self.version = version
        self.vers.set_text('Version %s' % (self.version))
        
    def _run_splash(self):
        if self._prog < 100:
            self._prog += 1
            self.pbar.set_fraction(self._prog/100.0)
            return True
        else:
            self.pbar.set_fraction(1.0)
            return False
