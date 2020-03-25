import os
import random
import time

import numpy
from scipy import interpolate
from gi.repository import GObject
from mxdc import conf, Signal, Device
from mxdc.utils import fitting
from mxdc.utils.log import get_module_logger
from zope.interface import implementer

from .interfaces import IMultiChannelAnalyzer

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


@implementer(IMultiChannelAnalyzer)
class BasicMCA(Device):
    """
    Base class for single and multi-element fluorescence MCA detector objects.

    :param args: All arguments and key-worded arguments are passed to :func:`custom_setup`
        but before that, the following key-worded arguments are used if available.
    :param kwargs:
        elements: (int) number of detector elements, default 1
        channels: (int) number of channels per element, default 4096
    """

    class Signals:
        deadtime = Signal("deadtime", arg_types=(float,))

    def __init__(self, *args, **kwargs):
        Device.__init__(self)
        self.name = 'Multi-Channel Analyzer'
        self.channels = kwargs.get('channels', 4096)
        self.elements = kwargs.get('elements', 1)
        self.region_of_interest = (0, self.channels)
        self.data = None
        self.nozzle = None

        # Setup the PVS
        self.custom_setup(*args, **kwargs)

        # Default parameters
        self.half_roi_width = 0.075  # energy units
        self._monitor_id = None
        self.acquiring = False
        self._command_sent = False

    def custom_setup(self, *args, **kwargs):
        """This is where all the custom setup for derived classes is performed. 
        Must be overridden for derived classes. Care must be taken to make sure 
        call signatures of derived classes are compatible if using explicitly
        named ordered arguments. 
        """

        # Overwrite this method to setup PVs. following  are examples only
        # self.spectra = [self.add_pv("%s:mca%d" % (name, d+1), monitor=False) for d in range(elements)]
        # self.READ = self.add_pv("%s:mca1.READ" % name_root, monitor=False)
        # self.RDNG = self.add_pv("%s:mca1.RDNG" % name_root)
        # self.START = self.add_pv("%s:mca1.ERST" % name_root, monitor=False)
        # self.ERASE = self.add_pv("%s:mca1.ERAS" % name_root, monitor=False)
        # self.IDTIM = self.add_pv("%s:mca1.IDTIM" % name_root, monitor=False)
        # self.ACQG = self.add_pv("%s:mca1.ACQG" % name_root)
        # self.STOP = self.add_pv("%s:mca1.STOP" % name_root, monitor=False)
        # self._count_time = self.add_pv("%s:mca1.PRTM" % name_root)

        # Calibration parameters
        # self._slope = self.add_pv("%s:mca1.CALS" % name_root)
        # self._offset = self.add_pv("%s:mca1.CALO" % name_root)

        # Signal handlers, RDNG and ACQG must be PVs defined in custom_setup
        # self.ACQG.connect('changed', self._monitor_state)

        raise NotImplementedError("Derived class does not implement a`custom_setup` method!")

    def configure(self, **kwargs):
        """
        Configure the detector for data acquisition.
        
        :param Kwargs:
            - `roi` (tuple(int, int)): bounding channels enclosing region of interest.
            - `energy` (float): an energy value in keV around which to construct
              a region of interest. The ROI is calculated as a 150 eV window around
              the requested energy. If both `roi` and `energy` are given, `energy`
              takes precendence.
            - `cooling` (bool): cool down if available, ignore otherwise
            - `nozzle` (bool): move nozzle in if True and out if False, if nozzle is available, ignore otherwise
        """

        for k, v in list(kwargs.items()):
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
            if k == 'nozzle' and self.nozzle:
                if v:
                    self.nozzle.on()
                else:
                    self.nozzle.off()

    def get_roi(self, energy):
        return [energy - self.half_roi_width, energy + self.half_roi_width]

    def _monitor_state(self, obj, state):
        if state == 1:
            self.set_state(busy=True)
        else:
            self.set_state(busy=False)

    def channel_to_energy(self, channel):
        """
        Convert a channel number to an energy value using the detectors
        calibration tables.
        
        :param channel:  (int), channel number.
        :return: float. Energy in keV
        """

        self.slope = self._slope.get()
        self.offset = self._offset.get()
        return self.slope * channel + self.offset

    def energy_to_channel(self, e):
        """
        Convert a an energy to a channel number using the detectors
        calibration tables.

        :param e: (float), Energy in keV.
        :return:  (int), channel number
        """
        self.slope = self._slope.get()
        self.offset = self._offset.get()
        return int((e - self.offset) / self.slope)

    def get_roi_counts(self):
        """
        Obtain the counts for the region of interest for each element of the
        detector for the last performed data acquisition.
        
        :returns: Array(float). The array contains as many elements as the number of
            elements plus one. The first entry is an average of all elements combined.
        """
        # get counts for each spectrum within region of interest
        values = self.data[self.region_of_interest[0]:self.region_of_interest[1], 1:].sum(0)
        return tuple(values)

    def get_count_rates(self):
        """
        Obtain the input and output count rates for last performed data
        acquisition.
        
        :returns: [(int, int)]. A list of tuples, one for each element. the first entry
            is the input count rate and the second is the output count rate. If 
            the values are not available (-1, -1) is substituted
        """
        return [(-1, -1)]*self.elements

    def count(self, t):
        """
        Integrate the detector for the specified amount of time. This method
        blocks.
        
        :param t: (float), integrating time in seconds.
        :returns: float. The total integrated count from the region of interest of
            all detector elements. If individual counts for each element are
            desired, they can be obtained using :func:`get_roi_counts`.            
        """
        self._acquire_data(t)
        # use only the last column to integrate region of interest 
        # should contain corrected sum for multichannel devices
        values = self.get_roi_counts()
        return values[0]

    def acquire(self, t=1.0):
        """
        Integrate the detector for the specified amount of time and return
        the raw data from all elements without any ROI manipulation. This method 
        blocks.
        
        :param t: (float), integrating time in seconds.
        :returns: Array(float). An MxN array of counts from each channel of each
            element. Where M is the number of elements and N is the number of
            channels in the detector.            
        """
        self._acquire_data(t)
        return self.data

    def stop(self):
        """
        Stop data acquisition.
        """
        self.STOP.put(1)

    def wait(self):
        """
        Wait for the detector to start and then stop data acquisition.
        """
        self._wait_start()
        self._wait_stop()

    def _start(self, wait=True):
        self.START.put(1)
        if wait:
            self._wait_start()

    def _calc_deadtime(self, obj, val):
        req_time = self._count_time.get()
        if not req_time:
            return
        pct = 100.0 * val / req_time
        self.set_state(deadtime=pct)

    def _acquire_data(self, t=1.0):
        self.data = numpy.zeros((self.channels, len(self.spectra) + 2))  # one more for x-axis, one more for sum
        self._count_time.put(t)
        self._start()
        self._wait_stop()
        self.data[:, 0] = self.channel_to_energy(numpy.arange(0, self.channels, 1))
        for i, spectrum in enumerate(self.spectra):
            self.data[:, i + 2] = spectrum.get()
            self.data[:, 1] += spectrum.get()

    def _wait_start(self, poll=0.05, timeout=2):
        logger.debug('Waiting for MCA to start acquiring.')
        while self.ACQG.get() == 0 and timeout > 0:
            timeout -= poll
            time.sleep(poll)
        if timeout <= 0:
            logger.warning('Timed out waiting for MCA to start acquiring')
            return False
        return True

    def _wait_stop(self, poll=0.05):
        logger.debug('Waiting for MCA to finish acquiring.')
        timeout = 10
        while self.ACQG.get() == 1 and timeout > 0:
            timeout -= poll
            time.sleep(poll)
        if timeout <= 0:
            logger.warning('Timed out waiting for MCA finish acquiring')
            return False
        return True


class XFlashMCA(BasicMCA):
    """
    mcaRecord based single element fluorescence detector object.

    :param name: (str), Root PV name of the mcaRecord.
    :param nozzle: (device), An OnOff toggle device for controlling the nozzle
    :param channels: (int), Number of channels.
    """

    def __init__(self, name, channels=4096, nozzle=None):
        BasicMCA.__init__(self, name, elements=1, channels=channels)
        self.name = 'XFlash MCA'
        self.nozzle = nozzle

    def custom_setup(self, pv_root, **kwargs):
        self.spectra = [self.add_pv("%s:mca%d" % (pv_root, d + 1), monitor=False) for d in range(self.elements)]
        self.READ = self.add_pv("%s:mca1.READ" % pv_root, monitor=False)
        self.RDNG = self.add_pv("%s:mca1.RDNG" % pv_root)
        self.START = self.add_pv("%s:mca1.ERST" % pv_root, monitor=False)
        self.ERASE = self.add_pv("%s:mca1.ERAS" % pv_root, monitor=False)
        self.IDTIM = self.add_pv("%s:mca1.IDTIM" % pv_root)
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
        self.IDTIM.connect('changed', self._calc_deadtime)

    def configure(self, **kwargs):
        """Configure the detector for data acquisition.
        
        Kwargs:
            - `roi` (tuple(int, int)): bounding channels enclosing region of interest.
            - `energy` (float): an energy value in keV around which to construct
              a region of interest. The ROI is calculated as a 150 eV window around
              the requested energy. If both `roi` and `energy` are given, `energy`
              takes precendence.
            - `cooling` (bool): True means enable detector cooling, False means
              disable it. 
        """
        # configure the mcarecord scan parameters
        self._temp_scan.put(5)  # 2 seconds
        self._status_scan.put(9)  # 0.1 second
        self._read_scan.put(0)  # Passive

        for k, v in list(kwargs.items()):
            if k == 'cooling':
                if self.TMP.get() >= -25.0 and v:
                    self._set_temp(v)
                    logger.debug('(%s) Waiting for MCA to cool down' % (self.name,))
                    while self.TMP.get() > -25:
                        time.sleep(0.2)
                else:
                    self._set_temp(v)
        BasicMCA.configure(self, **kwargs)

    def _set_temp(self, on):
        if on:
            self.TMODE.put(2)
        else:
            self.TMODE.put(0)

    def _schedule_warmup(self, obj, val):
        if val == 0:
            if self._monitor_id is not None:
                GObject.source_remove(self._monitor_id)
            self._monitor_id = GObject.timeout_add(300000, self._set_temp, False)

    def get_count_rates(self):
        # get IRC and OCR tuple
        return [(-1, -1)]


class VortexMCA(BasicMCA):
    """EPICS based 4-element Vortex ME4 detector object."""

    def __init__(self, name, channels=2048, nozzle=None):
        BasicMCA.__init__(self, name, elements=4, channels=channels)
        self.name = 'Vortex MCA'
        self.nozzle = nozzle

    def custom_setup(self, pv_root, **kwargs):
        self.spectra = [self.add_pv("%s:mca%d" % (pv_root, d + 1), monitor=False) for d in range(self.elements)]
        self.READ = self.add_pv("%s:mca1.READ" % pv_root, monitor=False)
        self.RDNG = self.add_pv("%s:mca1.RDNG" % pv_root)
        self.START = self.add_pv("%s:EraseStart" % pv_root, monitor=False)
        self.ERASE = self.add_pv("%s:mca1.ERAS" % pv_root, monitor=False)
        self.IDTIM = self.add_pv("%s:DeadTime" % pv_root)
        self.ACQG = self.add_pv("%s:Acquiring" % pv_root)
        self.STOP = self.add_pv("%s:mca1.STOP" % pv_root, monitor=False)
        self.ICRS = [
            self.add_pv("%s:dxp1.ICR" % pv_root),
            self.add_pv("%s:dxp2.ICR" % pv_root),
            self.add_pv("%s:dxp3.ICR" % pv_root),
            self.add_pv("%s:dxp4.ICR" % pv_root)]

        self.OCRS = [
            self.add_pv("%s:dxp1.OCR" % pv_root),
            self.add_pv("%s:dxp2.OCR" % pv_root),
            self.add_pv("%s:dxp3.OCR" % pv_root),
            self.add_pv("%s:dxp4.OCR" % pv_root)]
        self.spectra.append(self.add_pv("%s:mcaCorrected" % pv_root, monitor=False))
        self._count_time = self.add_pv("%s:PresetReal" % pv_root)

        # Calibration parameters
        self._slope = self.add_pv("%s:mca1.CALS" % pv_root)
        self._offset = self.add_pv("%s:mca1.CALO" % pv_root)

        # Signal handlers, RDNG and ACQG must be PVs defined in custom_setup
        self.ACQG.connect('changed', self._monitor_state)
        self.IDTIM.connect('changed', self._calc_deadtime)

    def get_count_rates(self):
        # get IRC and OCR tuples
        pairs = list(zip(self.ICRS, self.OCRS))
        _crs = []
        for ICR, OCR in pairs:
            _crs.append((ICR.get(), OCR.get()))
        return _crs


class SimMultiChannelAnalyzer(BasicMCA):
    """Simulated single channel MCA detector."""

    def __init__(self, name, energy=None, channels=4096, nozzle=None):
        self.energy = energy
        self.acquiring = False
        self.half_life = 60 * 30  # 1 hr
        self.start_time = time.time()
        super().__init__(name, elements=4, channels=channels)
        self.name = name
        self.nozzle = nozzle

    def custom_setup(self, *args, **kwargs):
        # Default parameters
        self.slope = 17.0 / 3298  # 50000     #0.00498
        self.offset = -96.0 * self.slope  # 9600 #-0.45347
        self._roi_counts = [0.0] * self.elements
        self.set_state(active=True, health=(0, '', ''))

    def update_spectrum(self, edge):
        fwhm = 0.01
        self.start_time = time.time()
        offset = random.random()/2
        x = numpy.linspace(edge - 0.5, edge + 1, 1000)
        y = (
                    fitting.step_response(x, [0.5 + offset, fwhm, edge, 0])
                    + fitting.gauss(x, [0.5 + 0.5-offset, fwhm, edge + fwhm * 0.5, 0])
            ) + numpy.random.uniform(0.01, 0.02, len(x))
        self.count_source = interpolate.interp1d(x, 5000 * y, kind='cubic', assume_sorted=True)

    def configure(self, **kwargs):
        BasicMCA.configure(self, **kwargs)
        self.update_spectrum(kwargs.get('edge', 12.658))

    def channel_to_energy(self, x):
        return self.slope * x + self.offset

    def energy_to_channel(self, y):
        return int((y - self.offset) / self.slope)

    def count(self, t):
        self.aquiring = True
        time.sleep(t)
        self.acquiring = False
        val = t * self.count_source(self.energy.get_position())
        self._roi_counts = [(1-0.1*random.random())*val for i in range(self.elements)]
        self.set_state(deadtime=random.random() * 51.0)
        return sum(self._roi_counts)

    def acquire(self, t=1.0):
        self.aquiring = True
        time.sleep(t)
        self.acquiring = False
        fname = os.path.join(conf.APP_DIR, 'test/scans/xrf_%03d.raw' % random.choice(list(range(1, 7))))
        logger.debug('Simulated Spectrum: {}'.format(fname))
        self._raw_data = numpy.loadtxt(fname, comments="#")
        self._x_axis = self._raw_data[:, 0]
        self.set_state(deadtime=random.random() * 51.0)

        y_sum = self._raw_data[:, 1]
        y_channels = [self._raw_data[:, 1]]
        for i in range(self.elements - 1):
            y_channel = (1-0.25*random.random())*self._raw_data[:, 1]
            y_sum = y_sum + y_channel
            y_channels.append(y_channel)
        return numpy.array(list(zip(self._x_axis , y_sum, *y_channels)))

    def get_roi_counts(self):
        return tuple(self._roi_counts)

    def get_count_rates(self):
        self.set_state(deadtime=random.random() * 51.0)
        return [(-1, -1)]

    def stop(self):
        pass

    def wait(self):
        time.sleep(0.5)


__all__ = ['XFlashMCA', 'VortexMCA', 'SimMultiChannelAnalyzer']
