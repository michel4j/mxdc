import time
import logging
import numpy
import gobject
from zope.interface import implements
from bcm.device.interfaces import IMultiChannelAnalyzer
from bcm.protocol import ca
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class MCAError(Exception):
    
    """MCA Exception."""

       
class MultiChannelAnalyzer(object):
    
    implements(IMultiChannelAnalyzer)
    
    def __init__(self, name, channels=4096):
        self.name = name
        name_parts = name.split(':')
        self._spectrum = ca.PV(name)
        self._count_time = ca.PV("%s.PRTM" % name)
        self._time_left = ca.PV("%s:timeRem" % name_parts[0])
        self.READ = ca.PV("%s.READ" % name, monitor=False)
        self.RDNG = ca.PV("%s.RDNG" % name)
        self.START = ca.PV("%s.ERST" % name, monitor=False)

        self.ERASE = ca.PV("%s.ERAS" % name, monitor=False)
        self.IDTIM = ca.PV("%s.IDTIM" % name, monitor=False)
        self.TMODE = ca.PV("%s:Rontec1SetMode" % name_parts[0], monitor=False)
        #self.SCAN = ca.PV("%s.SCAN" % name)
        self.ACQG = ca.PV("%s.ACQG" % name)
        #self._status_scan = ca.PV("%s:mca1Status.SCAN" % name_parts[0], monitor=False)
        #self._read_scan = ca.PV("%s:mca1Read.SCAN" % name_parts[0], monitor=False)
        self._stop_cmd = ca.PV("%s:mca1Stop" % name_parts[0], monitor=False)
        self.channels = channels
        self.region_of_interest = (0, self.channels)
        
        # Default parameters
        self.half_roi_width = 15 # in channel units 
        self.offset = -0.45347
        self.slope = 0.00498
        self._monitor_id = None
        self._acquiring = False
        self._data_read = False
        self._command_sent = False
        
        self.RDNG.connect('changed', self._monitor_stop)
        self.ACQG.connect('changed', self._monitor_start)
        
        self._x_axis = self.channel_to_energy( numpy.arange(0,4096,1) )

    def configure(self, **kwargs):
        for k,v in kwargs.items():
            if k == 'cooling':
                self._set_temp(v)
            if k == 'roi':
                if v is None:
                    self.region_of_interest = (0, self.channels)
                else:
                    midp = self.energy_to_channel(energy)
                    self.region_of_interest = (midp - self.half_roi_width, 
                                               midp + self.half_roi_width)
    def _set_temp(self, on):
        if on:
            self.TMODE.set(2)
        else:
            self.TMODE.set(0)         
                
    def _monitor_stop(self, obj, state):
        if state == 0:
            self._data_read = True      

    def _monitor_start(self, obj, state):
        if state == 1:
            self._acquiring = True
            self._command_sent = False
        else:
            self._acquiring = False

    def channel_to_energy(self, x):
        return ( x * self.slope + self.offset)
    
    def energy_to_channel(self, y):
        return   int(round((y - self.offset) / self.slope))
                                   
    def count(self, t):
        self._acquire_data(t)
        values = self._data[self.region_of_interest[0]:self.region_of_interest[1]]
        return sum(values)

    def acquire(self, t=1.0):
        self._acquire_data(t)
        return (self._x_axis, self._data)       
        
    def stop(self):
        self._stop_cmd.set(1)

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

