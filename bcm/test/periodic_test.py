#!/usr/bin/env python

import gtk
from bcm.utils import energy_to_wavelength
from mxdc.gui.PeriodicTable import PeriodicTable

def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(2)
    win.set_title("Periodic Table Demo")
    mytable = PeriodicTable()
    win.add(mytable)
    win.show_all()

    
    def printsel(object, data):
        en = float(data.split(':')[1])
        edge = data.split(':')[0]
        print "Edge:       %s" % edge
        print "Energy:     %8.2f eV" % (en * 1000)
        print "Wavelength: %8.5f  A" % energy_to_wavelength(en)
        return True
                
    mytable.connect('edge-selected', printsel)
    

if __name__ == '__main__':
    try:
        main()
        gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()
