"""This module defines classes aid interfaces for X-Ray fluorescence."""

from zope.interface import Interface, Attribute, invariant
from zope.component import globalSiteManager as gsm
from bcm.beamline.interfaces import IBeamline
from bcm.engine.scanning import BasicScan
from bcm.utils.chemistry import get_energy_database, xanes_targets
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

class XRFScan(BasicScan):    
    def __init__(self, t, energy=None):
        BasicScan.__init__(self)
        self.beamline = gsm.getUtility(IBeamline, 'bcm.beamline')
        self._energy = energy
        self._duration = t
        self.data = []
                            
    def run(self):
        _logger.debug('Exitation Scan waiting for beamline to become available.')
        self.beamline.lock.acquire()
        try:
            _logger.debug('Exitation Scan started')
            gobject.idle_add(self.emit, 'started')     
            self.beamline.mca.configure(cooling=True, roi=None)
            if self._energy is not None:
                self.beamline.energy.move_to(self._energy)
                self.beamline.energy.wait()
            self.beamline.exposure_shutter.open()
            self.data = self.beamline.mca.acquire(t=self._duration)
            gobject.idle_add(self.emit, "done")
            gobject.idle_add(self.emit, "progress", 1.0 )
        finally:
            self.beamline.exposure_shutter.close()
            self.beamline.lock.release()
            

class XANESScan(BasicScan):
    def __init__(self, beamline):
        ScannerBase.__init__(self, edge, t)
        self.beamline = gsm.getUtility(IBeamline, 'bcm.beamline')
        self._duration = t
        self._energy_db = get_energy_database()
        self._edge, self._energy = self._energy_db[edge]
        self._targets = xanes_targets(self._energy)
        
    def run(self):       
        _logger.info('Edge Scan waiting for beamline to become available.')
        self.beamline.lock.acquire()
        try:
            gobject.idle_add(self.emit, 'started')
            _logger.info('Edge Scan started.')
            self.beamline.mca.configure(cooling=True, roi=self._energy)
            self.beamline.energy.move_to(self._energy)
            self.beamline.energy.wait()   
                   
            self.count = 0
            self.beamline.exposure_shutter.open()
            self.beamline.mca.erase()
            _logger.info("%4s %15s %15s %15s" % ('#', 'Energy', 'Counts', 'Scale Factor'))
            for x in self.energy_targets:
                if self.stopped or self.aborted:
                    scan_logger.info('Edge Scan stopped.')
                    break
                    
                self.count += 1
                prev = self.beamline.bragg_energy.get_position()                
                self.beamline.bragg_energy.move_to(x, wait=True)
                if self.count == 1:
                    self.first_intensity = (self.beamline.i0.count(0.5) * 1e9)
                    self.factor = 1.0
                else:
                    self.factor = self.first_intensity/(self.beamline.i0.count(0.5)*1e9)
                y = self.beamline.mca.count(self.time)
                    
                y = y * self.factor
                self.x_data_points.append( x )
                self.y_data_points.append( y )
                
                fraction = float(self.count) / len(self.energy_targets)
                _logger.info("%4d %15g %15g %15g" % (self.count, x, y, self.factor))
                gobject.idle_add(self.emit, "new-point", x, y )
                gobject.idle_add(self.emit, "progress", fraction )
                             
            if self.aborted:
                _logger.warning("Edge Scan aborted.")
                gobject.idle_add(self.emit, "aborted")
                gobject.idle_add(self.emit, "progress", 0.0 )
            else:
                _logger.warning("Edge Scan completed.")
                gobject.idle_add(self.emit, "done")
                gobject.idle_add(self.emit, "progress", 1.0 )
        finally:
            self.beamline.shutter.close()
            self.beamline.lock.release()
              

