#!/usr/bin/env python

import sys, time
import gtk, gobject
import threading
import numpy

#gobject.threads_init()

class Scanner(threading.Thread, gobject.GObject):
    __gsignals__ = {}
    __gsignals__['new-point'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,gobject.TYPE_FLOAT))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['aborted'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['log'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    
    def __init__(self, positioner=None, start=0, end=0, steps=0, detector=None, time=1.0, output=None):
        threading.Thread.__init__(self)
        gobject.GObject.__init__(self)
        self.ps = positioner
        self.ds = detector
        self.time = time
        self.stopped = False
        self.aborted = False
        self.filename = output
        self.steps = steps
        self.range_start = start
        self.range_end = end
        self.calc_targets()
        self.data_points = []
        
    def _logtext(self,s):
        text = time.strftime('%Y/%m/%d %H:%M:%S ') + s
        print text
        gobject.idle_add(self.emit, 'log', text)
        
    def run(self, widget=None):
        self.detector = self.ds.copy() 
        self.positioner = self.ps.copy()
        self.count = 0
        for x in self.positioner_targets:
            if self.stopped or self.aborted:
                break
            self._logtext( "Entering iteration %d" % self.count)
            self.count += 1
            prev = self.positioner.get_position()
            self.positioner.move_to(x, wait=True)
            self._logtext("--- Position obtained, will now count ---")
            y = self.detector.count(self.time)
            self._logtext("--- Position and Count obtained ---")
            self.data_points.append( (x, y) )
            gobject.idle_add(self.emit, "new-point", x, y )
            
        if self.aborted:
            gobject.idle_add(self.emit, "aborted")
        else:
            self.save()
            gobject.idle_add(self.emit, "done")

    def calc_targets(self):
        if self.steps > 0:
            self.step_size = abs(end-start)/float(self.steps)
            self.positioner_targets = numpy.arange(self.range_start,self.range_end,self.step_size)
        else:
            self.positioner_targets = []
    
    def set_targets(self, targets):
        self.positioner_targets = targets
    
    def stop(self, widget=None):
        self.stopped = True    

    def abort(self, widget=None):
        self.aborted = True    

    def set_output(self, filename):
        self.filename = filename

    def save(self):
        scan_data  = "# Positioner: %s \n" % self.positioner.get_name()
        scan_data += "# Detector: %s \n" % self.detector.get_name()
        scan_data += "# Detector count time: %0.4f sec \n" % (self.time)
        scan_data += "# \n" 
        scan_data += "# Columns: (%s) \t (%s) \n" % (self.positioner.get_name(), self.detector.get_name())
        for x,y in self.data_points:
            scan_data += "%15.8g %15.8g \n" % (x, y)

        if self.filename != None:
            try:
                scan_file = open(self.filename,'w')        
                scan_file.write(scan_data)
                scan_file.flush()
                scan_file.close()
            except:
                print scan_data
        else:
            print scan_data
                        
gobject.type_register(Scanner)






from Plotter import Plotter
def add_point(widget, x, y, plot_widget):
    plot_widget.add_point(x, y,0)
    return True

        
def main():
    import Motor, Detector
    win = gtk.Window()
    win.set_default_size(800,600)
    win.set_border_width(2)
    win.set_title("Scanner Demo")
    vbox = gtk.VBox()
    win.add(vbox)
    myplot = Plotter()
    vbox.pack_start(myplot)
    
    act = Motor.FakeMotor()
    det = Detector.FakeDetector('XFD1608-101:mca1')
    #det.setup(roi=(0,100))
    
    myscanner = Scanner(act, 1, 5, 10, det, 1)
    myscanner.connect('new-point', add_point, myplot)
    gobject.idle_add(myscanner.start)
    win.connect("destroy", lambda x: gtk.main_quit())
    win.show_all()
    

    try:
        gtk.main()
    finally:
        myscanner.stop()
        sys.exit()

if __name__ == '__main__':
    main()
