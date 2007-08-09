#!/usr/bin/env python

import gtk
import sys, os
from PeriodicTable import PeriodicTable
import time
import hotshot
import hotshot.stats

def energy_to_wavelength(energy): #Angstroms
    h = 4.13566743e-15
    c = 299792458e10 
    return (h*c)/energy       

def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(2)
    win.set_title("Periodic Table Demo")
    al = gtk.Alignment(0.5,0.5,0.9,0.9)
    mytable = PeriodicTable()
    win.add(al)
    al.add(mytable)
    win.show_all()

    
    def printsel(object, data):
        en = float(data.split(':')[1])
        edge = data.split(':')[0]
        print "Edge:       %s" % edge
        print "Energy:     %8.2f eV" % (en * 1000)
        print "Wavelength: %8.5f  A" % energy_to_wavelength(en * 1000)
        return True
                
    mytable.connect('edge-selected', printsel)
    

if __name__ == '__main__':
    prof = hotshot.Profile("test.prof")
    benchtime = prof.runcall(main)
    prof.close()
    stats = hotshot.stats.load("test.prof")
    stats.strip_dirs()
    stats.sort_stats('time','calls')
    stats.print_stats(20)
    try:
		gtk.main()
    except KeyboardInterrupt:
        print "Quiting..."
        sys.exit()
