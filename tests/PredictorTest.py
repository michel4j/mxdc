#!/usr/bin/env python

import gtk, gobject
import sys, time
from Predictor import Predictor

def main():
   
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_default_size(400,400)
    win.set_border_width(2)
    win.set_title("Prector Widget Demo")
    vbox = gtk.VBox()
    win.add(vbox)
    mypred = Predictor()
    vbox.pack_start(mypred)
    mypred.set_all(1.33,150, 0, 1536, 1536)
    win.show_all()
    mypred.tmp_tt = 0
    def update():
        mypred.update()
        mypred.set_twotheta(mypred.two_theta + 1)
        if mypred.two_theta > 45:
            return False
        return True
        
    try:
        gobject.idle_add(update)
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()


if __name__ == '__main__':
    main()

