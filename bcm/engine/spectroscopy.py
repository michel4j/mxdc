"""This module defines classes aid interfaces for X-Ray fluorescence."""
import os
import time
import gobject
from zope.interface import Interface, Attribute, invariant
from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from bcm.engine.scanning import BasicScan, ScanError
from bcm.utils.science import *
from bcm.utils.log import get_module_logger
from bcm.utils import science
from bcm.engine.autochooch import AutoChooch
from bcm.utils.misc import get_short_uuid
from bcm.service.utils import  send_array

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

class XRFScan(BasicScan):    
    def __init__(self, energy=None, t=0.5, attenuation=0.0, directory=''):
        BasicScan.__init__(self)
        self.configure(t, energy, attenuation, directory, 'xrf')
        
    def configure(self, energy,  t,  attenuation, directory, prefix):
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None

        self._energy = energy
        self._duration = t
        self._directory = directory
        self._suffix = get_short_uuid()
        self._prefix = prefix
        self._filename = os.path.join(self._directory, "%s_%0.3f_%s.raw" % (self._prefix, self._energy, self._suffix))    
        self._attenuation = attenuation
        self.data = []
        self.data_names = ['Energy',
                           'Counts']
        self.results = {}
        
        
    def analyse(self):
        
        x = self.data[:,0]
        y = self.data[:,1]
        peaks = science.peak_search(x, y, w=31, threshold=0.1, min_peak=0.05)
        self.results['peaks'] = science.assign_peaks(peaks,  dev=0.04)
        self.results = {
            'data': send_array(self.data),
            'peaks': science.assign_peaks(peaks,  dev=0.04),
            'parameters ': {'directory': self._directory,
                            'energy': self._energy,
                            'exposure_time': self._duration,
                            'output_file': self._filename}
            }
        
        
    def run(self):
        _logger.debug('Exitation Scan waiting for beamline to become available.')
        self.beamline.lock.acquire()
        _saved_attenuation = self.beamline.attenuator.get()
        try:
            _logger.debug('Exitation Scan started')
            gobject.idle_add(self.emit, 'started')   
            # prepare environment for scannning
            self.beamline.goniometer.set_mode('COLLECT')
            self.beamline.mca.configure(retract=True, cooling=True, energy=None)
            self.beamline.attenuator.set(self._attenuation)
            if self._energy is not None:
                self.beamline.monochromator.energy.move_to(self._energy)
                self.beamline.monochromator.energy.wait()
            self.beamline.exposure_shutter.open()
            self.data = self.beamline.mca.acquire(t=self._duration)
            self.save(self._filename)
            self.analyse()
            gobject.idle_add(self.emit, "done")
            gobject.idle_add(self.emit, "progress", 1.0)
        finally:
            self.beamline.exposure_shutter.close()
            self.beamline.attenuator.set(_saved_attenuation)
            self.beamline.mca.configure(retract=False)
            self.beamline.lock.release()
        return self.results
            

class XANESScan(BasicScan):
    def __init__(self, edge='Se-K', t=0.5, attenuation=0.0, directory=''):
        BasicScan.__init__(self)
        self.configure(edge, t, attenuation, directory, 'xanes')
        self.autochooch = AutoChooch()
        
    def configure(self, edge, t, attenuation, directory, prefix):
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
        self._duration = t
        self._edge = edge
        self._energy_db = get_energy_database()
        self._edge_energy, self._roi_energy = self._energy_db[edge]
        self._targets = xanes_targets(self._edge_energy)
        self._attenuation = attenuation
        self.data = []
        self._directory = directory
        self._suffix = get_short_uuid()
        self._prefix = prefix
        self._filename = os.path.join(self._directory, "%s_%s_%s.raw" % (self._prefix, self._edge, self._suffix))
        self.chooch_results = {} 
                    
    def analyse(self):
        self.autochooch.configure(self._edge, self._directory, self._prefix, self._suffix)
        success = self.autochooch.run()
        if success:
            self.results = {
                'data': self.data,
                'efs': self.autochooch.get_data(),
                'energies': self.autochooch.get_results(),
                'text': self.autochooch.get_results_text(),
                'log': self.autochooch.log,
                'name_template': "%s_%s_%s" % (self._prefix, self._edge, self._suffix),
                'directory': self._directory}
        else:
            gobject.idle_add(self.emit, 'error', 'Analysis Failed')
            self.results = {
                'data': self.data,
                'log': self.autochooch.log,
                'name_template': "%s_%s_%s" % (self._prefix, self._edge, self._suffix),
                'directory': self._directory}
         
        
    def run(self):
        _logger.info('Edge Scan waiting for beamline to become available.')
        self.beamline.lock.acquire()
        _saved_attenuation = self.beamline.attenuator.get()
        try:
            gobject.idle_add(self.emit, 'started')
            _logger.info('Edge Scan started.')
            self.beamline.goniometer.set_mode('COLLECT')
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
            self.beamline.lock.release()           
        return self.results
    