import sys, os, re
import gobject
import threading
import commands
from numpy import loadtxt

class AutoChooch(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    def __init__(self):
        gobject.GObject.__init__(self)

    def setup(self, params):
        self.parameters = params
        
    def get_results(self):
        return self.results
    
    def get_data(self):
        return self.data
    
    def start(self):
        self.raw_file = None
        self.efs_file = None
        self.out_file = None
        self.data = None
        self.results = {}
        worker = threading.Thread(target=self.run)
        worker.setDaemon(True)
        worker.start()
        
    def run(self):    
        file_root = "%s/%s_%s" % (self.parameters['directory'],    self.parameters['prefix'], self.parameters['edge'])
        element, edge = self.parameters['edge'].split('-')
        self.raw_file = "%s.raw" % (file_root)
        self.efs_file = "%s.efs" % (file_root)
        self.out_file = "%s.out" % (file_root)
        chooch_command = "chooch -e %s -a %s %s -o %s | tee %s " % (element, edge, self.raw_file, self.efs_file, self.out_file)
        self.return_code, self.output = commands.getstatusoutput(chooch_command)
        success = self.read_output()
        if success:
            gobject.idle_add(self.emit, 'done')
        else:
            gobject.idle_add(self.emit, 'error','Premature termination')
        
    def read_output(self):
        self.data = loadtxt(self.efs_file, comments="#")
        output = open(self.out_file, 'r')
        pattern = re.compile('\|\s+([a-z]+)\s+\|\s+(.+)\s+\|\s+(.+)\s+\|\s+(.+)\s+\|')
        found_results = False
        for line in output:
            lm = pattern.search(line)
            if lm:
                found_results = True
                self.results[lm.group(1)] = [ lm.group(1), float(lm.group(2)), float(lm.group(3)), float(lm.group(4)) ]
        output.close()
        
        if not found_results:
            self.results = None
            gobject.idle_add(self.emit, 'error','AutoChooch Failed')
            return False
            
        # select remote energy, maximize fp, minimize fpp-fp
        def fpp_fp(triplet):
            return triplet[1]-triplet[2]
        triplets =   zip(self.data[:,0], self.data[:,2], self.data[:,1])  
        count = 0
        while (triplets[count][0]  <  self.results['peak'][1] + 25.0) and count < len(triplets)-1:
            count += 1
        selected = triplets[count-1]
        while (fpp_fp(selected) < fpp_fp(triplets[count]) 
               and (selected[2]<triplets[count][1]) 
               and count < len(triplets)-1):
            count += 1
        selected = triplets[count-1]
        self.results['remo'] = ['remo', selected[0], selected[1], selected[2]]

        #convert eV to keV
        self.data[:,0] *= 1e-3 # convert x-axis to keV 
        for key in self.results.keys():
            self.results[key][1] *= 1e-3
        return True
            
gobject.type_register(AutoChooch)



