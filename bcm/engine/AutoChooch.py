import sys, os, re
import gobject
import threading
import commands
from numpy import loadtxt
from bcm.utils import converter

class AutoChooch(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    def __init__(self):
        gobject.GObject.__init__(self)
        self._results_text = ""

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
        self.log_file = "%s.log" % (file_root)
        chooch_command = "chooch -e %s -a %s %s -o %s | tee %s " % (element, edge, self.raw_file, self.efs_file, self.log_file)
        self.return_code, self.log = commands.getstatusoutput(chooch_command)
        self.log = '\n----------------- %s ----------------------\n\n' % (self.log_file) + self.log
        success = self.read_output()
        if success:
            gobject.idle_add(self.emit, 'done')
        else:
            gobject.idle_add(self.emit, 'error','Premature termination')
        
    def read_output(self):
        self.data = loadtxt(self.efs_file, comments="#")
        self.data[:, 0] *= 1e-3 # convert to keV
        ifile = open(self.log_file, 'r')
        output = ifile.readlines()
        pattern = re.compile('\|\s+([a-z]+)\s+\|\s+(.+)\s+\|\s+(.+)\s+\|\s+(.+)\s+\|')
        found_results = False
        for i, line in enumerate(output):
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
    
gobject.type_register(AutoChooch)



