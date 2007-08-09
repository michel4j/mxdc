#!/usr/bin/env python

import time, sys
from numpy import *
from Plotter import Plotter
import gobject, gtk
import pylab

def main():
    if len(sys.argv) < 2:
        print 'usage: <prog> file.data'
        sys.exit()
    
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_default_size(800,600)
    win.set_border_width(2)
    win.set_title("Plot Widget Demo")
    vbox = gtk.VBox()
    win.add(vbox)
    myplot = Plotter()
    vbox.pack_start(myplot)
    
    data = pylab.load(sys.argv[1])
    x = data[:,0]
    y = data[:,1]
    count = 1
    myplot.add_line(x[:count],y[:count])
    def addpoint():
        myplot.add_point(x[addpoint.count], y[addpoint.count], 0)
        addpoint.count = addpoint.count + 1
        if addpoint.count == len(x):
            return False
        return True
    myplot.set_labels(title="Se-K absorption Edge", x_label="Energy (eV)", y1_label="Absorption")    
    gobject.timeout_add(100,addpoint)
    addpoint.count = count
    win.show_all()

    try:
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()


if __name__ == '__main__':
    main()
