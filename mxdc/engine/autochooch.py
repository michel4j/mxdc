import os, re
from gi.repository import GObject
import threading
import subprocess
import numpy

import numpy
from mxdc.utils import converter

class AutoChooch(GObject.GObject):
    """An event driven engine for performing analysis of MAD Scans with CHOOCH.
    
    Signals:
        - `done`: Emitted when the analysis is complete.
        - `error`: Emitted if an error occurs.
    """
    __gsignals__ = {}
    __gsignals__['error'] = (GObject.SignalFlags.RUN_LAST, None, (str,))
    __gsignals__['done'] = (GObject.SignalFlags.RUN_LAST, None, [])
    
    def __init__(self):
        GObject.GObject.__init__(self)
        self.results = {}

    def configure(self, config, data, uname=None):
        """
        Prepare the run chooch
        @param config: a dictionary containing the MAD-Scan configuration
        @param data: a numpy array containing the raw data
        @param uname: optional username
        @return:
        """
        self.config = config
        self.data = numpy.empty_like(data)
        self.data[:] = data
        self.data[:,0] *= 1000  # Convert keV to eV

        self.inp_file = "{}.dat".format(self.config['name'])
        self.esf_file = "{}.esf".format(self.config['name'])
        self.out_file = "{}.out".format(self.config['name'])
    
    def start(self):
        """Start the analysis asynchronously. Use signals to determine completion/failure."""
        worker = threading.Thread(target=self.run)
        worker.setDaemon(True)
        worker.start()
                        
    def run(self):
        self.results = {}
        element, edge = self.config['edge'].split('-')
        self.prepare_input()
        try:
            output = subprocess.check_output([
                'chooch', '-e', element, '-a', edge, self.inp_file, '-o', self.esf_file
            ], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            GObject.idle_add(self.emit, 'error','CHOOH Failed.')
        else:
            self.read_results(output)
            GObject.idle_add(self.emit, 'done')
        finally:
            os.remove(os.path.join(self.config['directory'], self.inp_file))

        return self.results

    def prepare_input(self):
        with open(os.path.join(self.config['directory'], self.inp_file), 'w') as handle:
            handle.write('#CHOOCH INPUT DATA\n%d\n' % len(self.data[:,0]))
            numpy.savetxt(handle, self.data[:,0:2], fmt='%0.2f')

    def read_results(self, output):
        try:
            data = numpy.loadtxt(os.path.join(self.config['directory'], self.esf_file), comments="#").astype(float)
            self.results['esf'] = {
                'energy': data[:,0] * 1e-3, # convert back to keV
                'fpp': data[:,1],
                'fp': data[:,2]
            }
        except IOError:
            GObject.idle_add(self.emit, 'error', 'CHOOH Failed.')
            return

        # extract MAD wavelengths from output
        r = re.compile(
            '\|\s+(?P<label>[^|]+)\s+\|\s+(?P<wavelength>(?P<energy>\d+\.\d+))\s+'
            '\|\s+(?P<fpp>-?\d+\.\d+)\s+\|\s+(?P<fp>-?\d+\.\d+)\s+\|'
        )

        energies = [m.groupdict() for m in r.finditer(output)]
        converters = {
            'energy': lambda x: float(x)*1e-3,
            'wavelength': lambda x: converter.energy_to_wavelength(float(x)*1e-3),
            'fpp': float,
            'fp': float,
            'label': lambda x: x
        }
        choices = [
            {key: converters[key](value) for key, value in dataset.items()}
            for dataset in energies
        ]

        if choices:
            # select remote energy, maximize f" x delta-f'
            infl = choices[1]
            sel  = self.results['esf']['energy'] < (infl['energy'] + 0.1)
            sel &= self.results['esf']['energy'] > (infl['energy'] + 0.05)
            fpp = self.results['esf']['fpp'][sel]
            fp = self.results['esf']['fp'][sel]
            energy = self.results['esf']['energy'][sel]
            opt = fpp * (fp - infl['fp'])
            opt_i = opt.argmax()
            choices.append({
                'label': 'remo', 'energy': energy[opt_i], 'fpp': fpp[opt_i], 'fp': fp[opt_i],
                'wavelength': converter.energy_to_wavelength(energy[opt_i])
            })

            new_output = "Selected Energies for 3-Wavelength MAD data \n"
            new_output +="and corresponding anomalous scattering factors.\n"
            new_output += "+------+------------+----------+--------+--------+\n"
            new_output += "|      | wavelength |  energy  |   f''  |   f'   |\n"
            for choice in choices:
                new_output += '| {label:4s} | {wavelength:10.5f} | {energy:8.5f} | {fpp:6.2f} | {fp:6.2f} |\n'.format(
                    **choice
                )
            new_output += "+------+------------+----------+--------+--------+\n"
            with open(os.path.join(self.config['directory'], self.out_file), 'w') as handle:
                handle.write(new_output)
            self.results['choices'] = choices


    


