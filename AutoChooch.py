#!/usr/bin/env python

import sys, os, re
import gtk, gobject
import threading
import commands
from pylab import load

gobject.threads_init()


class AutoChooch(threading.Thread, gobject.GObject):
    __gsignals__ = {}
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    def __init__(self):
        threading.Thread.__init__(self)
        gobject.GObject.__init__(self)
        self.raw_file = None
        self.efs_file = None
        self.out_file = None
        self.data = None
        self.results = {}

    def set_parameters(self, params):
        self.parameters = params
        
    def get_results(self):
        return self.results
    
    def get_data(self):
        return self.data
        
    def run(self, widget=None):    
        file_root = "%s/%s_%s" % (self.parameters['directory'],    self.parameters['prefix'], self.parameters['edge'])
        element, edge = self.parameters['edge'].split('-')
        self.raw_file = "%s.raw" % (file_root)
        self.efs_file = "%s.efs" % (file_root)
        self.out_file = "%s.out" % (file_root)
        chooch_command = "chooch -e %s -a %s %s -o %s | tee %s " % (element, edge, self.raw_file, self.efs_file, self.out_file)
        self.return_code, self.output = commands.getstatusoutput(chooch_command)
        if self.return_code == 0:
            self.read_output()
            gobject.idle_add(self.emit, 'done')
        else:
            gobject.idle_add(self.emit, 'error','Premature termination')
        
    def read_output(self):
        self.data = load(self.efs_file)
        output = open(self.out_file, 'r')
        pattern = re.compile('\|\s+([a-z]+)\s+\|\s+(.+)\s+\|\s+(.+)\s+\|\s+(.+)\s+\|')
        for line in output:
            lm = pattern.search(line)
            if lm:
                self.results[lm.group(1)] = [ lm.group(1), float(lm.group(2)), float(lm.group(3)), float(lm.group(4)) ]
        output.close()
        
        # select remote energy, maximize fp, minimize fpp-fp
        selected = [0, -999, -999]
        for e, fp, fpp in zip(self.data[:,0], self.data[:,2], self.data[:,1]):
           if e > self.results['peak'][1] + 50.0 and e < self.results['peak'][1] + 200.0:
                if (fpp+fp) > (selected[1]+selected[2]):
                    selected = [e, fpp, fp]
        if selected[0] != 0:
            self.results['remo'] = ['remo', selected[0], selected[1], selected[2]]
        #convert eV to keV
        self.data[:,0] *= 1e-3 # convert x-axis to keV 
        for key in self.results.keys():
            self.results[key][1] *= 1e-3
            

gobject.type_register(AutoChooch)



