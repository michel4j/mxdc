
import logging
import numpy
from zope.interface import implements
from bcm.device.interfaces import IMultiChannelAnalyzer
from bcm.protocol import ca
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)
       
class MultiChannelAnalyzer(object):
    
    implements(IMultiChannelAnalyzer)
    
    def __init__(self, name, channels=4096):
        self.name = name
        name_parts = name.split(':')
        self._spectrum = ca.PV(name)
        self._count_time = ca.PV("%s.PRTM" % name, monitor=False)
        self._time_left = ca.PV("%s:timeRem" % name_parts[0])
        self.READ = ca.PV("%s.READ" % name, monitor=False)
        self.RDNG = ca.PV("%s.RDNG" % name)
        self.START = ca.PV("%s.ERST" % name, monitor=False)
        self.ERASE = ca.PV("%s.ERAS" % name, monitor=False)
        self.IDTIM = ca.PV("%s.IDTIM" % name, monitor=False)
        self.TMODE = ca.PV("%s:Rontec1SetMode" % name_parts[0], monitor=False)
        self.SCAN = ca.PV("%s.SCAN" % name)
        self.ACQG = ca.PV("%s.ACQG" % name)
        self._status_scan = ca.PV("%s:mca1Status.SCAN" % name_parts[0], monitor=False)
        self._read_scan = ca.PV("%s:mca1Read.SCAN" % name_parts[0], monitor=False)
        self.channels = channels
        self.region_of_interest = (0, self.channels)
        
        # Default parameters
        self.half_roi_width = 15 # in channel units 
        self.offset = -0.45347
        self.slope = 0.00498
        self._monitor_id = None
        self._read_state = False
        self.RDNG.connect('changed', self._monitor_reading)
        self._x_axis = self.channel_to_energy( numpy.arange(0,4096,1) )

    def configure(self, props):
        for k,v in props:
            if k == 'cooling':
                self._set_temp(v)
            if k == 'energy':
                if v is None:
                    self.region_of_interest = (0, self.channels)
                else:
                    midp = self.energy_to_channel(energy)
                    self.region_of_interest = (midp - self.half_roi_width, 
                                               midp + self.half_roi_width)
    def _set_temp(self, on):
        if on:
            self.TMODE.put(2)
        else:
            self.TMODE.put(0)         
                
    def _monitor_reading(self, obj, state):
        if state == 0:
            self._read_state = False         

    def channel_to_energy(self, x):
        return ( x * self.slope + self.offset)
    
    def energy_to_channel(self, y):
        return   int(round((y - self.offset) / self.slope))
                                   
    def count(self, t=1.0):
        self._collect(t)
        values = self._data[self.region_of_interest[0]:self.region_of_interest[1]]
        return sum(self.values)

    def acquire(self, t=1.0):
        self._collect(t)
        return (self._x_axis, self._data)       
        
            
        
    def _start(self, retries=5):
        i = 0
        success = False
        while i < retries and not success:
            i += 1
            self.START.put(1)
            success = self._wait_count()
            self._read_state = True
        if i==retries and not success:
            _logger.error('MCA acquire failed after %s retries' % retries)
                              
    def _collect(self, t=1.0):
        self._set_temp_monitor(False)
        self._count_time.put(t)
        self._start()
        self._wait_read()
        self._data = self._spectrum.get()
        self._set_temp_monitor(True)

    def _set_temp_monitor(self, mode):
        if mode:
              self._monitor_id = gobject.timeout_add(300000, self._set_temp, False)
        elif self._monitor_id:
            gobject.source_remove(self._monitor_id)

    def _wait_count(self, start=True, stop=False,poll=0.05, timeout=2):
        if (start):
            time_left = timeout
            _logger.debug('Waiting for MCA to start counting.')
            while self.ACQG.get() == 0 and time_left > 0:
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                _logger.warning('Timed out waiting for MCA acquire to start after %d sec' % timeout)
                return False                
        if (stop):
            time_left = timeout
            _logger.debug('Waiting for MCA to stop counting.')
            while self.ACQG.get() !=0 and time_left > 0:
                test = self.ACQG.get()         
                time_left -= poll
                time.sleep(poll)
            if time_left <= 0:
                _logger.warning('Timed out waiting for MCA acquire to stop after %d sec' % timeout)
                return False
        return True        
                
    def _wait_read(self, poll=0.05, timeout=5):       
        time_left = timeout
        _logger.debug('Waiting for MCA to start reading.')
        while self._read_state and time_left > 0:
            time_left -= poll
            time.sleep(poll)
        if time_left <= 0:
            _logger.warning('Timed out waiting for MCA to read after %d sec' % timeout)
            return False

