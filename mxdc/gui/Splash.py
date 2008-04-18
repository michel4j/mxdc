import gtk, gobject
import sys, os

class Splash(object):
    def __init__(self, image, startup_obj):
        self.win = gtk.Window()
        self.win.set_size_request(480,290)
        self.win.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_SPLASHSCREEN)
        self.win.set_gravity(gtk.gdk.GRAVITY_CENTER)

        self.img = gtk.Image()
        self.img.set_from_file(image)
        vbox = gtk.VBox(False,0)
        vbox.pack_start(self.img, expand=False, fill=False)

        self.pbar = gtk.ProgressBar()
        vbox.pack_end(self.pbar)
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
        self.pbar.set_text(text)
    