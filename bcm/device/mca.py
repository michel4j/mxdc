import time
import numpy
import os
import gobject
import random
from zope.interface import implements
from bcm.device.interfaces import IMultiChannelAnalyzer
from bcm.protocol import ca
from bcm.device.base import BaseDevice
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class MCAError(Exception):
    
    """MCA Exception."""

       
class BasicMCA(BaseDevice):
    
    implements(IMultiChannelAnalyzer)
    
    def __init__(self, name, nozzle=None, elements=1, channels=4096):
        BaseDevice.__init__(self)
        self.name = 'Multi-Channel Analyzer'
        self.channels = channels
        self.elements = elements
        self.region_of_interest = (0, self.channels)
        self.data = None
        
        # Setup the PVS
        self.custom_setup(name)

        
        # Default parameters
        self.half_roi_width = 0.075 # energy units
        self._monitor_id = None
        self._acquiring = False
        self._command_sent = False
        self.nozzle = nozzle
        
    def custom_setup(self, pv_root):
        # Overwrite this method to setup PVs. follow are examples only
        #self.spectra = [self.add_pv("%s:mca%d" % (name, d+1), monitor=False) for d in range(elements)]
        #self.READ = self.add_pv("%s:mca1.READ" % pv_root, monitor=False)
        #self.RDNG = self.add_pv("%s:mca1.RDNG" % pv_root)
        #self.START = self.add_pv("%s:mca1.ERST" % pv_root, monitor=False)
        #self.ERASE = self.add_pv("%s:mca1.ERAS" % pv_root, monitor=False)
        #self.IDTIM = self.add_pv("%s:mca1.IDTIM" % pv_root, monitor=False)
        #self.ACQG = self.add_pv("%s:mca1.ACQG" % pv_root)
        #self.STOP = self.add_pv("%s:mca1.STOP" % pv_root, monitor=False)
        #self._count_time = self.add_pv("%s:mca1.PRTM" % pv_root)

        # Calibration parameters
        #self._slope = self.add_pv("%s:mca1.CALS" % pv_root)
        #self._offset = self.add_pv("%s:mca1.CALO" % pv_root)

        # Signal handlers, RDNG and ACQG must be PVs defined in custom_setup
        #self.ACQG.connect('changed', self._monitor_state)
        pass
                
    def configure(self, **kwargs):
        if 'retract' in kwargs.keys():
            self._set_nozzle(kwargs['retract'])
            
        for k,v in kwargs.items():                   
            if k == 'roi':
                if v is None:
                    self.region_of_interest = (0, self.channels)
                else:
                    self.region_of_interest = v
            if k == 'energy':
                if v is None:
                    self.region_of_interest = (0, self.channels)
                else:
                    self.region_of_interest = (
                                self.energy_to_channel(v - self.half_roi_width),
                                self.energy_to_channel(v + self.half_roi_width))
    def _set_nozzle(self, out):
        if self.nozzle is None:
            return
        if out:
            _logger.debug('(%s) Moving nozzle closer to sample' % (self.name,))
            self.nozzle.set(0)
        else:
            _logger.debug('(%s) Moving nozzle away from sample' % (self.name,))
            self.nozzle.set(1)
        ca.flush()
        time.sleep(2)
                
    def _monitor_state(self, obj, state):
        if state == 1:
            self.set_state(busy=True)
        else:
            self.set_state(busy=False)

    def channel_to_energy(self, x):
        self.slope = self._slope.get()
        self.offset = self._offset.get()
        return self.slope*x + self.offset
    
    def energy_to_channel(self, y):
        self.slope = self._slope.get()
        self.offset = self._offset.get()
        return  int((y-self.offset)/self.slope)
    
    def get_roi_counts(self):                            
        # get counts for each spectrum within region of interest
        values = self.data[self.region_of_interest[0]:self.region_of_interest[1], 1:].sum(0)
        return values

    def get_count_rates(self):                            
        # get IRC and OCR tuple
        return [-1, -1]
    
    def count(self, t):
        self._acquire_data(t)
        # use only the last column to integrate region of interest 
        # should contain corrected sum for multichannel devices
        values = self.get_roi_counts()
        return values[-1]

    def acquire(self, t=1.0):
        self._acquire_data(t)
        return self.data
        
    def stop(self):
        self.STOP.set(1)

    def wait(self):
        self._wait_start()
        self._wait_stop()
    
    def get_state(self):
        if self._acquiring:
            return ['acquiring']
        else:
            return ['idle']
        
    def _start(self, wait=True):
        self.START.set(1)
        if wait:
            self._wait_start()
                              
    def _acquire_data(self, t=1.0):
        self.data = numpy.zeros((self.channels, len(self.spectra)+1)) # one more for x-axis
        self._count_time.set(t)
        self._start()
        self._wait_stop()        
        self.data[:,0] = self.channel_to_energy(numpy.arange(0,self.channels,1))
        for i, spectrum in enumerate(self.spectra):
            self.data[:,i+1] = spectrum.get()

    def _wait_start(self, poll=0.05, timeout=2):
        _logger.debug('Waiting for MCA to start acquiring.')
        while self.ACQG.get() == 0 and timeout > 0:
            timeout -= poll
            time.sleep(poll)
        if timeout <= 0:
            _logger.warning('Timed out waiting for MCA to start acquiring')
            return False                
        return True        
                
    def _wait_stop(self, poll=0.05):       
        _logger.debug('Waiting for MCA to finish acquiring.')
        timeout = 5 * self._count_time.get()    # use 5x count time for timeout
        while self.ACQG.get() == 1 and timeout > 0:
            timeout -= poll
            time.sleep(poll)
        if timeout <= 0:
            _logger.warning('Timed out waiting for MCA finish acquiring')
            return False                
        return True        

class XFlashMCA(BasicMCA):
    
    def __init__(self, name, nozzle=None, channels=4096):
        BasicMCA.__init__(self, name, nozzle=nozzle, elements=1, channels=channels)
        self.name = 'XFlash MCA'
        
    def custom_setup(self, pv_root):       
        self.spectra = [self.add_pv("%s:mca%d" % (pv_root, d+1), monitor=False) for d in range(self.elements)]
        self.READ = self.add_pv("%s:mca1.READ" % pv_root, monitor=False)
        self.RDNG = self.add_pv("%s:mca1.RDNG" % pv_root)
        self.START = self.add_pv("%s:mca1.ERST" % pv_root, monitor=False)
        self.ERASE = self.add_pv("%s:mca1.ERAS" % pv_root, monitor=False)
        self.IDTIM = self.add_pv("%s:mca1.IDTIM" % pv_root, monitor=False)
        self.ACQG = self.add_pv("%s:mca1.ACQG" % pv_root)
        self.STOP = self.add_pv("%s:mca1.STOP" % pv_root, monitor=False)
        
        # Calibration parameters
        self._slope = self.add_pv("%s:mca1.CALS" % pv_root)
        self._offset = self.add_pv("%s:mca1.CALO" % pv_root)
        
        # temperature parameters
        self.TMP = self.add_pv("%s:Rontec1Temperature" % pv_root)
        self.TMODE = self.add_pv("%s:Rontec1SetMode" % pv_root, monitor=False)
        
        # others
        self._count_time = self.add_pv("%s:mca1.PRTM" % pv_root)
        self._status_scan = self.add_pv("%s:mca1Status.SCAN" % pv_root, monitor=False)
        self._read_scan = self.add_pv("%s:mca1Read.SCAN" % pv_root, monitor=False)
        self._temp_scan = self.add_pv("%s:Rontec1ReadTemperature.SCAN" % pv_root, monitor=False)
        
        # schecule a warmup at the end of every acquisition
        self.ACQG.connect('changed', self._schedule_warmup)
        
        
    def configure(self, **kwargs):
        # configure the mcarecord scan parameters
        self._temp_scan.put(5) # 2 seconds
        self._status_scan.put(9) # 0.1 second
        self._read_scan.put(0) # Passive
        
        for k,v in kwargs.items():        
            if k == 'cooling':
                if self.TMP.get() >= -25.0 and v:
                    self._set_temp(v)
                    _logger.debug('(%s) Waiting for MCA to cool down' % (self.name,))
                    while self.TMP.get() > -25:
                        time.sleep(0.2)
                else:
                    self._set_temp(v)
        BasicMCA.configure(self, **kwargs)
        
    def _set_temp(self, on):
        if on:
            self.TMODE.set(2)
        else:
            self.TMODE.set(0)

    def _schedule_warmup(self, obj, val):
        if val == 0:
            if self._monitor_id is not None:
                gobject.source_remove(self._monitor_id)
            self._monitor_id = gobject.timeout_add(300000, self._set_temp, False)

    def get_count_rates(self):                            
        # get IRC and OCR tuple
        return [-1, -1]

class VortexMCA(BasicMCA):
    
    def __init__(self, name, channels=2048):
        BasicMCA.__init__(self, name, nozzle=None, elements=4, channels=channels)
        self.name = 'Vortex MCA'
        
    def custom_setup(self, pv_root):
        self.spectra = [self.add_pv("%s:mca%d" % (pv_root, d+1), monitor=False) for d in range(self.elements)]
        self.READ = self.add_pv("%s:mca1.READ" % pv_root, monitor=False)
        self.RDNG = self.add_pv("%s:mca1.RDNG" % pv_root)
        self.START = self.add_pv("%s:EraseStart" % pv_root, monitor=False)
        self.ERASE = self.add_pv("%s:mca1.ERAS" % pv_root, monitor=False)
        self.IDTIM = self.add_pv("%s:DeadTime" % pv_root, monitor=False)
        self.ACQG = self.add_pv("%s:Acquiring" % pv_root)
        self.STOP = self.add_pv("%s:mca1.STOP" % pv_root, monitor=False)
        self.ICR = self.add_pv("%s:dxpSum:ICR" % pv_root)
        self.OCR = self.add_pv("%s:dxpSum:OCR" % pv_root)
        self.spectra.append(self.add_pv("%s:mcaCorrected" % pv_root, monitor=False))
        self._count_time = self.add_pv("%s:PresetReal" % pv_root)

        # Calibration parameters
        self._slope = self.add_pv("%s:mca1.CALS" % pv_root)
        self._offset = self.add_pv("%s:mca1.CALO" % pv_root)

        # Signal handlers, RDNG and ACQG must be PVs defined in custom_setup
        self.ACQG.connect('changed', self._monitor_state)
        
    def get_count_rates(self):                            
        # get IRC and OCR tuple
        return [self.ICR.get(), self.OCR.get()]

class MultiChannelAnalyzer(BaseDevice):
    
    implements(IMultiChannelAnalyzer)
    
    def __init__(self, name, nozzle=None, channels=4096):
        BaseDevice.__init__(self)
        self.name = 'Multi-Channel Analyzer'
        name_parts = name.split(':')
        self._spectrum = self.add_pv(name)
        self._count_time = self.add_pv("%s.PRTM" % name)
        self._time_left = self.add_pv("%s:timeRem" % name_parts[0])
        self.READ = self.add_pv("%s.READ" % name, monitor=False)
        self.RDNG = self.add_pv("%s.RDNG" % name)
        self.START = self.add_pv("%s.ERST" % name, monitor=False)
        self.TMP = self.add_pv("%s:Rontec1Temperature" % name_parts[0])

        self.ERASE = self.add_pv("%s.ERAS" % name, monitor=False)
        self.IDTIM = self.add_pv("%s.IDTIM" % name, monitor=False)
        self.TMODE = self.add_pv("%s:Rontec1SetMode" % name_parts[0], monitor=False)
        self._temp_scan = self.add_pv("%s:Rontec1ReadTemperature.SCAN" % name_parts[0], monitor=False)
        self.ACQG = self.add_pv("%s.ACQG" % name)
        self._status_scan = self.add_pv("%s:mca1Status.SCAN" % name_parts[0], monitor=False)
        self._read_scan = self.add_pv("%s:mca1Read.SCAN" % name_parts[0], monitor=False)
        self.STOP = self.add_pv("%s:mca1Stop" % name_parts[0], monitor=False)
        self._slope = self.add_pv("%s.CALS" % name)
        self._offset = self.add_pv("%s.CALO" % name)
        self.channels = int(channels)
        self.region_of_interest = (0, self.channels)
        
        # Default parameters
        self.half_roi_width = 15 # in channel units 
        self.slope = 17.0/3298 #50000     #0.00498
        self.offset = -96.0 * self.slope #9600 #-0.45347
        self._monitor_id = None
        self._acquiring = False
        self._data_read = False
        self._command_sent = False
        
        self.ACQG.connect('changed', self._monitor_state)
        
        self.nozzle = nozzle

    def configure(self, **kwargs):
        # configure the mcarecord scan parameters
        self._temp_scan.put(5) # 2 seconds
        self._status_scan.put(9) # 0.1 second
        self._read_scan.put(0) # Passive
        
        if 'retract' in kwargs.keys():
            self._set_nozzle(kwargs['retract'])
            
        for k,v in kwargs.items():        
            if k == 'cooling':
                if self.TMP.get() >= -25.0 and v:
                    self._set_temp(v)
                    _logger.debug('(%s) Waiting for MCA to cool down' % (self.name,))
                    while self.TMP.get() > -25:
                        time.sleep(0.2)
                else:
                    self._set_temp(v)
                    
                
            if k == 'roi':
                if v is None:
                    self.region_of_interest = (0, self.channels)
                else:
                    self.region_of_interest = v
            if k == 'energy':
                if v is None:
                    self.region_of_interest = (0, self.channels)
                else:
                    midp = self.energy_to_channel(v)
                    self.region_of_interest = (midp - self.half_roi_width, 
                                               midp + self.half_roi_width)        
    def _set_temp(self, on):
        if on:
            self.TMODE.set(2)
        else:
            self.TMODE.set(0)
            
    def _set_nozzle(self, out):
        if self.nozzle is None:
            return
        if out:
            _logger.debug('(%s) Moving nozzle closer to sample' % (self.name,))
            self.nozzle.set(0)
        else:
            _logger.debug('(%s) Moving nozzle away from sample' % (self.name,))
            self.nozzle.set(1)
        ca.flush()
        time.sleep(2)
                
    def _monitor_state(self, obj, state):
        if state == 1:
            self._acquiring = True
            self._command_sent = False
        else:
            self._acquiring = False

    def channel_to_energy(self, x):
        self.slope = self._slope.get()
        self.offset = self._offset.get()
        return self.slope*x + self.offset
    
    def energy_to_channel(self, y):
        self.slope = self._slope.get()
        self.offset = self._offset.get()
        return   int((y-self.offset)/self.slope)
                                   
    def count(self, t):
        self._acquire_data(t)
        values = self._data[self.region_of_interest[0]:self.region_of_interest[1]]
        return sum(values)

    def acquire(self, t=1.0):
        self._x_axis = self.channel_to_energy(numpy.arange(0,4096,1))
        self._acquire_data(t)
        return numpy.array(zip(self._x_axis, self._data))
        
    def stop(self):
        self.STOP.set(1)

    def wait(self):
        self._wait_start()
        self._wait_stop()
    
    def get_state(self):
        if self._acquiring:
            return ['acquiring']
        else:
            return ['idle']
        
    def _start(self, retries=5):
        i = 0
        success = False
        while i < retries and not success:
            i += 1
            self._command_sent = True
            self.START.set(1)
            success = self._wait_start()
        if i==retries and not success:
            _logger.error('MCA acquire failed after %s retries' % retries)
                              
    def _acquire_data(self, t=1.0):
        self._count_time.set(t)
        self._start()
        self._wait_stop()
        self._data = self._spectrum.get()
        self._schedule_warmup()

    def _schedule_warmup(self):
        if self._monitor_id is not None:
            gobject.source_remove(self._monitor_id)
        self._monitor_id = gobject.timeout_add(300000, self._set_temp, False)

    def _wait_start(self, poll=0.05, timeout=2):
        _logger.debug('Waiting for MCA to start counting.')
        while self._command_sent and not self._acquiring and timeout > 0:
            timeout -= poll
            time.sleep(poll)
        if timeout <= 0:
            _logger.warning('Timed out waiting for MCA to start acquiring')
            return False                
        return True        
                
    def _wait_stop(self, poll=0.05):       
        _logger.debug('Waiting for MCA to finish acquiring.')
        timeout = 5 * self._count_time.get()    # use 5x count time for timeout
        while (self._acquiring or not self._data_read) and timeout > 0:
            timeout -= poll
            time.sleep(poll)
        if timeout <= 0:
            _logger.warning('Timed out waiting for MCA finish acquiring')
            return False                
        return True      


class SimMultiChannelAnalyzer(BasicMCA):
    
    
    def __init__(self, name, channels=4096):
        BasicMCA.__init__(self, name, None, 1, channels)
        self.name = name
        self.channels = channels
        self.elements = 1
        self.region_of_interest = (0, self.channels)
        
        # Default parameters
        self.slope = 17.0/3298 #50000     #0.00498
        self.offset = -96.0 * self.slope #9600 #-0.45347
                
        self._counts_data = numpy.loadtxt(os.path.join(os.environ['BCM_PATH'],'test/scans/xanes_002.raw'), comments="#")
        self._counts_data = self._counts_data[:,1]        
        self._last_t = time.time()
        self._last_pos = 0
        self.set_state(active=True)
        
    def configure(self, **kwargs):
        self._last_pos = 0
        self._last_t = time.time()     
        BasicMCA.configure(self, **kwargs)
                
    def channel_to_energy(self, x):
        return self.slope*x + self.offset
    
    def energy_to_channel(self, y):
        return   int((y-self.offset)/self.slope)
                                   
    def count(self, t):
        self._aquiring = True
        time.sleep(t)
        self._acquiring = False
        val = self._counts_data[self._last_pos]
        if self._last_pos < len(self._counts_data)-1:
            self._last_pos += 1
        return val

    def acquire(self, t=1.0):
        self._aquiring = True
        time.sleep(t)
        self._acquiring = False
        fname = os.path.join(os.environ['BCM_PATH'],'test/scans/xrf_%03d.raw' % 1)
        self._raw_data = numpy.loadtxt(fname, comments="#")
        self._x_axis = self._raw_data[:,0]
        return numpy.array(zip(self._x_axis, self._raw_data[:,1]))
    
    def get_roi_counts(self):
        return [0.0]

    def get_count_rates(self):
        return [-1, -1]
        
    def stop(self):
        pass

    def wait(self):
        time.sleep(0.5)
    
    def get_state(self):
        if self._acquiring:
            return ['acquiring']
        else:
            return ['idle']

__all__ = ['XFlashMCA', 'VortexMCA', 'MultiChannelAnalyzer', 'SimMultiChannelAnalyzer']
