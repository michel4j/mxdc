import os, re
import gobject
import threading
import commands
import numpy

from numpy import loadtxt, savetxt
from bcm.utils import converter

class AutoChooch(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    def __init__(self):
        gobject.GObject.__init__(self)
        self._results_text = ""

    def configure(self, edge, directory, prefix, suffix):
        self.directory = directory
        self._edge = edge
        self._prefix = prefix
        self._suffix = suffix
        self.results = {}
        
    def get_results(self):
        return self.results
    
    def get_data(self):
        return self.data
    
    def start(self):
        self.raw_file = None
        self.efs_file = None
        self.out_file = None
        self.data = None
        worker = threading.Thread(target=self.run)
        worker.setDaemon(True)
        worker.start()
        
    def prepare_input_data(self, raw_file, dat_file):
        dat = loadtxt(raw_file)
        f = open(dat_file,'w')
        f.write('#CHOOCH INPUT DATA\n%d\n' % len(dat[:,0]))
        dat[:,0] *= 1000    #converting to eV
        savetxt(f, dat[:,0:2])
        f.close()
        return
        
        
    def run(self):
        self.results = {}
        file_root = os.path.join(self.directory, "%s_%s_%s" % (self._prefix, self._edge, self._suffix))    
        self.raw_file = "%s.raw" % (file_root)
        self.dat_file = "%s.dat" % (file_root)
        self.efs_file = "%s.efs" % (file_root)
        self.out_file = "%s.out" % (file_root)
        self.log_file = "%s.log" % (file_root)
        element, edge = self._edge.split('-')
        self.prepare_input_data(self.raw_file, self.dat_file)
        chooch_command = "chooch -e %s -a %s %s -o %s | tee %s " % (element, edge, self.dat_file, self.efs_file, self.log_file)
        self.return_code, self.log = commands.getstatusoutput(chooch_command)
        self.log = '\n----------------- %s ----------------------\n\n' % (self.log_file) + self.log
        success = self.read_output()
        if success:
            gobject.idle_add(self.emit, 'done')
            return success
        else:
            gobject.idle_add(self.emit, 'error','Premature termination')
            return False
        
    def read_output(self):
        try:
            self.data = loadtxt(self.efs_file, comments="#")
        except IOError:
            return False
        
        self.data[:, 0] *= 1e-3 # convert to keV
        ifile = open(self.log_file, 'r')
        output = ifile.readlines()
        pattern = re.compile('\|\s+([a-z]+)\s+\|\s+(.+)\s+\|\s+(.+)\s+\|\s+(.+)\s+\|')
        found_results = False
        for line in output:
            lm = pattern.search(line)
            if lm:
                found_results = True
                # energy converted to keV
                self.results[lm.group(1)] =  [lm.group(1), float(lm.group(2))*1e-3, float(lm.group(3)), float(lm.group(4))]
        ifile.close()
        
        if not found_results:
            self.results = None
            gobject.idle_add(self.emit, 'error','AutoChooch Failed')
            return False
            
        # select remote energy, maximize f" x delta-f'
        fpp = self.data[:,1]
        fp = self.data[:,2]
        energy = self.data[:,0]
        opt = fpp * (fp - self.results['infl'][3])
        opt_i = opt.argmax()
        
        self.results['remo'] = ['remo', energy[opt_i], fpp[opt_i], fp[opt_i]]
        new_output = "Selected Energies for 3-Wavelength MAD data \n"
        new_output +="and corresponding anomalous scattering factors.\n"
        
        new_output += "+------+------------+----------+-------+-------+\n"
        new_output += "|      | wavelength |  energy  |   f'' |   f'  |\n"
        for k in ['peak','infl','remo']:
            new_output += '| %4s | %10.5f | %8.5f | %5.2f | %5.2f |\n' % (k, converter.energy_to_wavelength(self.results[k][1]),
                                                                self.results[k][1],
                                                                self.results[k][2],
                                                                self.results[k][3]
                                                                )
        new_output += "+------+------------+----------+-------+-------+\n"
        ofile = open(self.out_file, 'w')
        ofile.write(new_output)
        ofile.close()
        self._results_text = new_output
        return True

    def get_results_text(self):
        return self._results_text
    


