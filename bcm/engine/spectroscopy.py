"""This module defines classes aid interfaces for X-Ray fluorescence."""
import gobject
from zope.interface import Interface, Attribute, invariant
from zope.component import globalSiteManager as gsm
from bcm.beamline.interfaces import IBeamline
from bcm.engine.scanning import BasicScan, ScanError
from bcm.utils.science import get_energy_database, xanes_targets
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

class XRFScan(BasicScan):    
    def __init__(self, t=0.5, energy=None, attenuation=0.0):
        BasicScan.__init__(self)
        self.configure(t, energy, attenuation)
        
    def configure(self, t, energy, attenuation):
        try:
            self.beamline = gsm.getUtility(IBeamline, 'bcm.beamline')
        except:
            self.beamline = None
        self._energy = energy
        self._duration = t
        self._attenuation = attenuation
        self.data = []
        self.data_names = ['Energy',
                           'Counts']
    def __simulate(self):
        import pylab
        import time
        raw = pylab.load('XRFTest.raw')
        self.data = raw
        gobject.idle_add(self.emit, "done")
        gobject.idle_add(self.emit, "progress", 1.0)
        
    def run(self):
        _logger.debug('Exitation Scan waiting for beamline to become available.')
        if self.beamline is None:
            _logger.error('Beamline unavailable')
            #gobject.idle_add(self.emit, "error", 'Beamline unavailable')
            self.__simulate()               
            return
        self.beamline.lock.acquire()
        try:
            _logger.debug('Exitation Scan started')
            gobject.idle_add(self.emit, 'started')     
            self.beamline.mca.configure(cooling=True, roi=None)
            self.beamline.attenuator.set(self._attenuation)
            if self._energy is not None:
                self.beamline.monochromator.energy.move_to(self._energy)
                self.beamline.monochromator.energy.wait()
            self.beamline.exposure_shutter.open()
            self.data = self.beamline.mca.acquire(t=self._duration)
            gobject.idle_add(self.emit, "done")
            gobject.idle_add(self.emit, "progress", 1.0)
        finally:
            self.beamline.exposure_shutter.close()
            self.beamline.attenuator.set(0.0)
            self.beamline.lock.release()
            

class XANESScan(BasicScan):
    def __init__(self, edge='Se-K', t=0.5, attenuation=0.0):
        BasicScan.__init__(self)
        self.configure(edge, t, attenuation)
        
    def configure(self, edge, t, attenuation):
        try:
            self.beamline = gsm.getUtility(IBeamline, 'bcm.beamline')
        except:
            self.beamline = None
        self._duration = t
        self._energy_db = get_energy_database()
        self._edge, self._energy = self._energy_db[edge]
        self._targets = xanes_targets(self._energy)
        self._attenuation = attenuation
        self.data = []
    
    def __simulate(self):
        import pylab
        import time
        raw = pylab.load('SeMet.raw')
        _logger.info("%4s %15s %15s %15s %15s" % ('#', 'Energy', 'Scaled Counts', 'Reference Count','Unscaled Counts'))
        for i in range(len(raw[:,0])):
            if self._stopped:
                _logger.info("Scan stopped!")
                break
            y = raw[i,1]
            x = raw[i,0]/1000.0
            i0 = 1.0
            self.data.append( [x, y/i0, i0, y] )
            fraction = float(i+1)/len(raw[:,0])
            _logger.info("%4d %15g %15g %15g %15g" % (i, x, y/i0, i0, y))
            gobject.idle_add(self.emit, "new-point", (x, y/i0, i0, y))
            gobject.idle_add(self.emit, "progress", fraction )
            time.sleep(self._duration)
                         
        if self._stopped:
            _logger.warning("XANES Scan stopped.")
            gobject.idle_add(self.emit, "stopped")
        else:
            _logger.info("XANES Scan complete.")
            gobject.idle_add(self.emit, "done")
            gobject.idle_add(self.emit, "progress", 1.0)
                
                
        
    def run(self):
        _logger.info('Edge Scan waiting for beamline to become available.')
        if self.beamline is None:
            _logger.error('Beamline unavailable')
            #gobject.idle_add(self.emit, "error", 'Beamline unavailable')
            self.__simulate()               
            return
        self.beamline.lock.acquire()
        try:
            gobject.idle_add(self.emit, 'started')
            _logger.info('Edge Scan started.')
            self.beamline.attenuator.set(self._attenuation)
            self.beamline.mca.configure(cooling=True, roi=self._energy)
            self.beamline.monochromator.energy.move_to(self._energy)
            self.beamline.monochromator.energy.wait()   
                   
            self.count = 0
            self.beamline.exposure_shutter.open()
            _logger.info("%4s %15s %15s %15s %15s" % ('#', 'Energy', 'Scaled Counts', 'I_0','Unscaled Counts'))
            self.data_names = ['Energy',
                               'Scaled Counts',
                               'I_0',
                               'Raw Counts']
            for x in self.energy_targets:
                if self._stopped:
                    _logger.info("Scan stopped!")
                    break
                    
                self.count += 1
                self.beamline.monochromator.simple_energy.move_to(x, wait=True)
                y = self.beamline.mca.count(self._duration)
                i0 = self.beamline.i0.count(self._duration)
                self.data.append( [self.count, x, y, i0, y / i0] )
                    
                fraction = float(self.count) / len(self.energy_targets)
                _logger.info("%4d %15g %15g %15g %15g" % (count, x, y/i0, i0, y))
                gobject.idle_add(self.emit, "new-point", (x, y/i0, i0, y))
                gobject.idle_add(self.emit, "progress", fraction )
                             
            if self.stopped:
                _logger.warning("XANES Scan stopped.")
                gobject.idle_add(self.emit, "stopped")
            else:
                _logger.info("XANES Scan complete.")
                gobject.idle_add(self.emit, "done")
                gobject.idle_add(self.emit, "progress", 1.0 )
        finally:
            self.beamline.exposure_shutter.close()
            self.beamline.attenuator.set(0.0)
            self.beamline.lock.release()
              

