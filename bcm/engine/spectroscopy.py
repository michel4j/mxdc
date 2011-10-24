"""This module defines classes aid interfaces for X-Ray fluorescence."""
import os
import time
import gobject
import re
from zope.interface import Interface, Attribute, invariant
from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from bcm.engine.scanning import BasicScan, ScanError
from bcm.utils.science import *
from bcm.utils.log import get_module_logger
from bcm.utils import science, json
from bcm.engine.autochooch import AutoChooch
from bcm.utils.misc import get_short_uuid
from bcm.service.utils import  send_array


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

class XRFScan(BasicScan):    
    def __init__(self, energy=None, edge='Se-K', t=0.5, attenuation=0.0, directory=''):
        BasicScan.__init__(self)
        self.data_names = ['Energy', 'Counts']
        self.configure(t, energy, edge, attenuation, directory, 'xrf')
        
    def configure(self, energy, edge, t, attenuation, directory, prefix, crystal=None, uname=None):
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
        self.scan_parameters = {}
        self.scan_parameters['energy'] = energy
        self.scan_parameters['edge'] = edge
        self.scan_parameters['duration'] = t
        self.scan_parameters['directory'] = directory
        self.scan_parameters['prefix'] = prefix
        self.scan_parameters['user_name'] = uname
        self.scan_parameters['filename'] = os.path.join(directory, "%s_%0.3f.raw" % (prefix, energy))
        self.scan_parameters['results_file'] = os.path.join(directory, "%s_%0.3f.out" % (prefix, energy))
        self.scan_parameters['attenuation'] = attenuation
        self.scan_parameters['crystal_id'] = crystal
        self.meta_data = {'energy': energy, 'time': t, 'attenuation': attenuation, 'prefix': prefix, 'user_name': uname}
        self.results = {}
        
    def analyse(self):        
        x = self.data[:,0].astype(float)
        y = self.data[:,1].astype(float)
        peaks = science.find_peaks(x,y,sensitivity=0.005)
        energy = self._energy
        elastic_candidates = []
        for peak in peaks:
            if peak[1] > peaks[0][1]/10.0 :
                dev = abs(energy-peak[0])
                if dev < 0.45:
                    elastic_candidates.append(peak)
        
        for peak in peaks:
            if peak[1] > 1:
                zero_peak = peak
                break
                 
        if len(elastic_candidates) == 1:
            elastic_peak = elastic_candidates[0]
        elif len(elastic_candidates) > 1:
            elastic_peak = elastic_candidates[-1]
        else:
            elastic_peak = (energy, 0.0)
        scale = energy/(elastic_peak[0]+-zero_peak[0])
        scale = max(min(scale, 1.03), 0.97)
        
        # initial adjustment of MCA calibration
        x = (x - zero_peak[0]) * scale        
        elements, bblocks, coeffs = science.interprete_xrf(x, y, energy, speedup=8)
        x = x / coeffs[-1]
        
        assigned = {}        
        for i, el_info in enumerate(elements):
            symbol = el_info[0]
            if coeffs[i] > 0.001: 
                a = bblocks[:,i].sum()
                prob = 100.0*a/y.sum()
                if prob > 0.5:
                    line_info = science.get_line_info(el_info, coeffs[i])
                    if line_info is not None:
                        assigned[symbol] = [prob, science.get_line_info(el_info, coeffs[i])]         
        
        # twisted does not like numpy.float64 so we need to convert x, y to native python
        # floats here
        ys = science.smooth_data(y, times=2, window=21)
        self.results = {
            'data': {'energy': map(float, list(x)), 
                     'counts': map(float, list(ys)),
                     'fit' : map(float, list(bblocks.sum(1)))},
            'assigned': assigned,
            'parameters': {'directory': self._directory,
                            'energy': self._energy,
                            'edge': self._edge,
                            'exposure_time': self._duration,
                            'output_file': self._filename,
                            'attenuation': self._attenuation,
                            'crystal_id': self._crystal_id,
                            'prefix': self._prefix },
            'kind': 1, # Excitation Scan
            }
        fp = open(self._results_file, 'w')
        json.dump(self.results, fp)
        fp.close()
        
        
        
    def run(self):
        _logger.debug('Excitation Scan waiting for beamline to become available.')
        self.beamline.lock.acquire()
        # get parameters from recent configure
        self._energy = self.scan_parameters['energy']
        self._edge = self.scan_parameters['edge']
        self._duration = self.scan_parameters['duration']
        self._directory = self.scan_parameters['directory']
        self._prefix = self.scan_parameters['prefix']
        self._crystal_id = self.scan_parameters['crystal_id']
        self._user_name = self.scan_parameters['user_name']
        self._filename = self.scan_parameters['filename']
        self._results_file = self.scan_parameters['results_file']
        self._attenuation = self.scan_parameters['attenuation']
        self.data = []        
        _saved_attenuation = self.beamline.attenuator.get()
        try:
            _logger.debug('Exitation Scan started.')
            gobject.idle_add(self.emit, 'started')   
            # prepare environment for scannning
            self.beamline.goniometer.set_mode('SCANNING')
            self.beamline.mca.configure(retract=True, cooling=True, energy=None)
            self.beamline.attenuator.set(self._attenuation)
            if self._energy is not None:
                self.beamline.monochromator.energy.move_to(self._energy)
                self.beamline.monochromator.energy.wait()
            gobject.idle_add(self.emit, "progress", 0.15)
            self.beamline.exposure_shutter.open()
            self.data = self.beamline.mca.acquire(t=self._duration)
            self.beamline.exposure_shutter.close()
            self.save(self._filename)
            gobject.idle_add(self.emit, "progress", 0.3)
            _logger.debug('Interpreting scan...')
            self.analyse()
            gobject.idle_add(self.emit, "done")
            gobject.idle_add(self.emit, "progress", 1.0)
        finally:
            self.beamline.exposure_shutter.close()
            self.beamline.attenuator.set(_saved_attenuation)
            self.beamline.mca.configure(retract=False)
            _logger.debug('Excitation scan done.')
            self.beamline.goniometer.set_mode('COLLECT')
            self.beamline.lock.release()
        return self.results
            

class XANESScan(BasicScan):
    def __init__(self, edge='Se-K', t=0.5, attenuation=0.0, directory=''):
        BasicScan.__init__(self)
        self._energy_db = get_energy_database()
        self.autochooch = AutoChooch()
        self.configure(edge, t, attenuation, directory, 'xanes')
        
    def configure(self, edge, t, attenuation, directory, prefix, crystal=None, uname=None):
        #FIXME: Possible race condition here if new configure is issued while previous scan is still running
        # - maybe we should use queues and have the scan constantly check and perform a scan
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
        self.scan_parameters = {}
        self.scan_parameters['edge'] = edge
        self.scan_parameters['edge_energy'],  self.scan_parameters['roi_energy'] = self._energy_db[edge]
        self.scan_parameters['duration'] = t
        self.scan_parameters['directory'] = directory
        self.scan_parameters['prefix'] = prefix
        self.scan_parameters['user_name'] = uname
        self.scan_parameters['targets'] = xanes_targets(self.scan_parameters['edge_energy'])
        self.scan_parameters['filename'] = os.path.join(directory, "%s_%s.raw" % (prefix, edge))
        self.scan_parameters['attenuation'] = attenuation
        self.scan_parameters['crystal_id'] = crystal
        self.meta_data = {'edge': edge, 'time': t, 'attenuation': attenuation, 'prefix': prefix, 'user_name': uname}
        
                    
    def analyse_file(self, filename):
        import numpy
        data = numpy.loadtxt(filename)
        raw_text = file(filename).read()
        self.data = zip(data[:,0], data[:,1], data[:,2], data[:,3])
        
        meta = re.search('# Meta Data: ({.+})', raw_text)
        if meta:
            self.meta_data = json.loads(meta.group(1))
            self._edge = self.meta_data['edge']
            self._directory = os.path.dirname(filename)
            self._prefix = self.meta_data['prefix']
            self._user_name = self.meta_data['user_name']
                        
        self.analyse()
        gobject.idle_add(self.emit, "done")
    
    def analyse(self):
        self.autochooch.configure(self._edge, self._directory, self._prefix, self._user_name)
        success = self.autochooch.run()
        res_data = {'energy': [float(v[0]) for v in self.data], 
                    'counts': [float(v[1]) for v in self.data]}
        if success:
            _efs = self.autochooch.get_data()
            efs_data = {'energy': map(float, _efs[:,0]),
                        'fp': map(float, _efs[:,2]), 
                        'fpp': map(float, _efs[:,1])
                        }
            self.results = {
                'data': res_data,
                'efs': efs_data,
                'energies': self.autochooch.get_results(),
                'text': self.autochooch.get_results_text(),
                'log': self.autochooch.log,
                'name_template': "%s_%s" % (self._prefix, self._edge),
                'directory': self._directory,
                'edge': self._edge,
                'crystal_id': self._crystal_id,
                'attenuation': self._attenuation,
                'energy': self._edge_energy,
                'kind': 0 # MAD Scan
                }
        else:
            gobject.idle_add(self.emit, 'error', 'Analysis Failed')
            self.results = {
                'data': res_data,
                'log': self.autochooch.log,
                'name_template': "%s_%s" % (self._prefix, self._edge),
                'directory': self._directory}
         
        
    def run(self):
        _logger.info('Edge Scan waiting for beamline to become available.')
        self.beamline.lock.acquire()

        # Obtain scan parameters from recent configure
        self._duration = self.scan_parameters['duration']
        self._edge = self.scan_parameters['edge']
        self._edge_energy = self.scan_parameters['edge_energy']
        self._roi_energy = self.scan_parameters['roi_energy']      
        self._targets = self.scan_parameters['targets']        
        self._attenuation = self.scan_parameters['attenuation']
        self._directory = self.scan_parameters['directory']
        self._prefix = self.scan_parameters['prefix']
        self._user_name = self.scan_parameters['user_name']
        self._filename = self.scan_parameters['filename']
        self._crystal_id = self.scan_parameters['crystal_id']
        self.data = []
        self.chooch_results = {} 
        _saved_attenuation = self.beamline.attenuator.get()
        try:
            gobject.idle_add(self.emit, 'started')
            _logger.info('Edge scan started.')
            self.beamline.goniometer.set_mode('SCANNING')
            self.beamline.attenuator.set(self._attenuation)
            self.beamline.mca.configure(retract=True, cooling=True, energy=self._roi_energy)
            self.beamline.monochromator.energy.move_to(self._edge_energy)
            self.beamline.monochromator.energy.wait()   
                   
            self.count = 0
            self.beamline.exposure_shutter.open()
            #_logger.info("%4s %15s %15s %15s %15s" % ('#', 'Energy', 'Scaled Counts', 'I_0','Unscaled Counts'))
            self.data_names = ['Energy',
                               'Scaled Counts',
                               'I_0',
                               'Raw Counts']
            for x in self._targets:
                if self._stopped:
                    _logger.info("Scan stopped!")
                    break
                    
                self.count += 1
                self.beamline.monochromator.simple_energy.move_to(x, wait=True)
                y = self.beamline.mca.count(self._duration)
                i0 = self.beamline.i_0.count(self._duration)
                if self.count == 1:
                    scale = 1.0
                else:
                    scale = (self.data[0][2]/i0)
                self.data.append( [x, y*scale, i0, y] )
                    
                fraction = float(self.count) / len(self._targets)
                #_logger.info("%4d %15g %15g %15g %15g" % (self.count, x, y*scale, i0, y))
                gobject.idle_add(self.emit, "new-point", (x, y*scale, i0, y))
                gobject.idle_add(self.emit, "progress", fraction )
                             
            if self._stopped:
                _logger.warning("XANES Scan stopped. Will Attempt CHOOCH Analysis")
                self.save(self._filename)
                self.analyse()
                gobject.idle_add(self.emit, "stopped")
            else:
                _logger.info("XANES Scan complete. Analysing scan with CHOOCH.")
                self.save(self._filename)
                self.analyse()
                gobject.idle_add(self.emit, "done")
                gobject.idle_add(self.emit, "progress", 1.0 )
        finally:
            self.beamline.monochromator.energy.move_to(self._edge_energy)
            self.beamline.exposure_shutter.close()
            self.beamline.attenuator.set(_saved_attenuation)
            self.beamline.mca.configure(retract=False)
            _logger.info('Edge scan done.')
            self.beamline.goniometer.set_mode('COLLECT')
            self.beamline.lock.release()           
        return self.results
    