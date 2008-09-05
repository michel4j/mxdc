import gtk, gobject
import sys, os
from ActiveWidgets import LinearProgress

REVISION =  '$Rev$'.split()[1]

class Splash(object):
    def __init__(self, image, startup_obj, icon=None, logo=None, color=None):
        self.win = gtk.Window()
        self.win.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_SPLASHSCREEN)
        self.win.set_gravity(gtk.gdk.GRAVITY_CENTER)

        pixbuf = gtk.gdk.pixbuf_new_from_file(image)
        pixmap, mask = pixbuf.render_pixmap_and_mask()
        width, height = pixmap.get_size()
        self.win.set_app_paintable(True)
        self.win.resize(width, height)
        self.win.realize()
        self.win.window.set_back_pixmap(pixmap, False)

        vbox = gtk.VBox(False,0)
        hbox = gtk.HBox(False, 0)
        hbox.set_border_width(50)

        self.pbar = LinearProgress()
        self.pbar.set_color(color)
        self.pbar.set_size_request(0,8)
        self.log = gtk.Label()
        self.log.modify_fg( gtk.STATE_NORMAL, self.log.get_colormap().alloc_color(color) )
        self.log.set_alignment(0,0.5)
        self.icon = gtk.Image()
        self.logo = gtk.Image()
        if icon:
            self.icon.set_from_file(icon)
        if logo:
            self.logo.set_from_file(logo)
        hbox.pack_start(self.icon, expand=False, fill=False)
        hbox.pack_start(self.logo, expand=False, fill=False)
        vbox.pack_start(hbox)
        vbox.pack_end(self.pbar, expand=False, fill=False)
        vbox.pack_end(self.log, expand=False, fill=False)
        vers = gtk.Label('Version 2.0 | Revision %s' % REVISION)
        vers.set_alignment(0,0.5)
        vers.modify_fg( gtk.STATE_NORMAL, vers.get_colormap().alloc_color(color) )
        vbox.pack_end(vers, expand=False, fill=False)
        vbox.set_spacing(4)
        vbox.set_border_width(16)
        
        self.win.add(vbox)
        self.win.set_position(gtk.WIN_POS_CENTER)                
        self.win.show_all()
        self.win.realize()

        self.startup_obj = startup_obj
        self.startup_obj.connect('progress', self.on_progress)
        self.startup_obj.connect('log', self.on_log)
        
    def hide(self):
        self.win.hide_all()
        
    def on_progress(self, obj, frac):
        self.pbar.set_fraction(frac)
    
    def on_log(self, obj, text):
        self.log.set_text(text)
    
