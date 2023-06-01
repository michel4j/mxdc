from __future__ import annotations

import os
import random
import time

import epics
import numpy
from enum import IntFlag, auto

from scipy import interpolate
from gi.repository import GLib
from mxdc import Signal, Device, APP_DIR
from mxdc.utils import fitting
from mxdc.utils.log import get_module_logger
from zope.interface import implementer

from typing import List
from numpy.typing import NDArray

from .interfaces import IMultiChannelAnalyzer

WARMUP_TIMEOUT = 300000

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class MCAFeatures(IntFlag):
    TIMED_READS = auto()


@implementer(IMultiChannelAnalyzer)
class BaseMCA(Device):
    """
    Base class for single and multi-element fluorescence MCA detector objects.

    Signals:
        - **dead-time**: float, dead time

    :param args: All arguments and key-worded arguments are passed to :func:`custom_setup`
        but before that, the following key-worded arguments are used if available.
    :param kwargs:
        elements: (int) number of detector elements, default 1
        channels: (int) number of channels per element, default 4096
    """

    class Signals:
        dead_time = Signal("dead-time", arg_types=(float,))
        counts = Signal("counts", arg_types=(int, int))         # element index, sum of values in ROI
        spectra = Signal("spectra", arg_types=(int, object))    # element index, full spectrum
        progress = Signal("progress", arg_types=(float,))

    start_cmd: epics.PV
    stop_cmd: epics.PV
    mode_cmd: epics.PV
    temperature: epics.PV
    acquiring: epics.PV
    progress: epics.PV
    slope: epics.PV
    offset: epics.PV
    count_time: epics.PV
    input_counts: epics.PV | List[epics.PV]
    output_counts: epics.PV | List[epics.PV]
    mca_data: List[epics.PV]
    spectra: NDArray

    def __init__(self, *args, **kwargs):
        Device.__init__(self)
        self.name = 'Multi-Channel Analyzer'
        self.channels = kwargs.get('channels', 4096)
        self.elements = kwargs.get('elements', 1)
        self.region_of_interest = (0, self.channels)
        self.data = numpy.zeros((self.channels, self.elements), int)
        self.dark = numpy.zeros((self.channels, self.elements), int)
        self.spectra = numpy.zeros((self.channels, self.elements + 2), float)

        # Default parameters
        self.half_roi_width = 0.075  # energy units
        self.warmup_monitor = 0
        self.progress_value = 0.0
        self.command_sent = False
        self.mca_data = []

        # Set up the PVS
        self.custom_setup(*args, **kwargs)
        for i, pv in enumerate(self.mca_data):
            pv.connect('changed', self.on_new_spectrum, i)

    def custom_setup(self, *args, **kwargs):
        """
        This is where all the custom setup for derived classes is performed.
        Must be overridden for derived classes. Care must be taken to make sure 
        call signatures of derived classes are compatible if using explicitly
        named ordered arguments. 
        """

        raise NotImplementedError("Derived class does not implement a`custom_setup` method!")

    def configure(self, **kwargs):
        """
        Configure the detector for data acquisition.
        
        Kwargs:
            - `roi` (tuple(int, int)): bounding channels enclosing region of interest.
            - `energy` (float): an energy value in keV around which to construct
              a region of interest. The ROI is calculated as a 150 eV window around
              the requested energy. If both `roi` and `energy` are given, `energy`
              takes precendence.
            - `cooling` (bool): cool down if available, ignore otherwise
            - `dark` (bool): take dark current
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
            if k == 'dark':
                self.dark[:] = self.acquire_dark()

    def get_roi(self, energy):
        """
        Get region of interest tuple for the given energy

        :param energy: Energy
        """
        return energy - self.half_roi_width, energy + self.half_roi_width

    def channel_to_energy(self, channel):
        """
        Convert a channel number to an energy value using the detectors
        calibration tables.
        
        :param channel:  (int), channel number.
        :return: float. Energy in keV
        """

        slope = self.slope.get()
        offset = self.offset.get()
        return slope * channel + offset

    def energy_to_channel(self, energy):
        """
        Convert an energy to a channel number using the detectors
        calibration tables.

        :param energy: (float), Energy in keV.
        :return:  (int), channel number
        """
        slope = self.slope.get()
        offset = self.offset.get()
        return int((energy - offset) / slope)

    def get_roi_counts(self):
        """
        Obtain the counts for the region of interest for each element of the
        detector for the last performed data acquisition.
        
        :returns: Array(float). The array contains as many elements as the number of
            elements.
        """
        # get counts for each spectrum within region of interest
        values = self.data[self.region_of_interest[0]:self.region_of_interest[1], :].sum(0)
        return tuple(values)

    def get_dark_counts(self):
        """
        Obtain the counts for the region of interest for each element of the
        detector for the dark data.

        :returns: Array(float). The array contains as many elements as the number of
            elements.
        """
        # get counts for each spectrum within region of interest
        values = self.dark[self.region_of_interest[0]:self.region_of_interest[1], :].sum(0)
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

    def count(self, duration):
        """
        Integrate the detector for the specified amount of time. This method
        blocks.
        
        :param duration: (float), integrating time in seconds.
        :returns: float. The total integrated count from the region of interest of
            all detector elements. If individual counts for each element are
            desired, they can be obtained using :func:`get_roi_counts`.            
        """
        self.acquire_data(duration)
        # use only the last column to integrate region of interest 
        # should contain corrected sum for multichannel devices
        values = self.get_roi_counts()
        dark = self.get_dark_counts()
        return sum(values) - sum(dark)

    def acquire(self, duration=1.0):
        """
        Integrate the detector for the specified amount of time and return
        the raw data from all elements without any ROI manipulation. This method 
        blocks.
        
        :param duration: (float), integrating time in seconds.
        :returns: Array(float). An MxN array of counts from each channel of each
            element. Where M is the number of elements and N is the number of
            channels in the detector.            
        """
        self.acquire_data(duration)
        return self.spectra

    def start(self, wait=False):
        """
        Start Acquisition
        :param wait: Whether to wait for acquisition to start
        """
        self.start_cmd.put(1)
        if wait:
            self.wait_start()

    def stop(self, wait=False):
        """
        Stop data acquisition.
        """
        self.stop_cmd.put(1)
        if wait:
            self.wait_stop()

    def wait(self):
        """
        Wait for the detector to start and then stop data acquisition.
        """
        self.wait_start()
        self.wait_stop()

    def acquire_data(self, t=1.0):
        self.count_time.put(t)
        self.progress_value = 0
        src_id = GLib.timeout_add(int(t*1000/50), self.update_progress, 50/1000.)
        self.start()
        self.wait()
        GLib.source_remove(src_id)

        for i, spec in enumerate(self.mca_data):
            self.data[:, i] = spec.get()

        corrected = self.data - self.dark
        self.spectra[:, 0] = self.channel_to_energy(numpy.arange(0, self.channels, 1))
        self.spectra[:, 1] = corrected.sum(1)
        self.spectra[:, 2:] = self.data

    def acquire_dark(self, t=1.0):
        self.acquire_data(t)
        return self.data

    def wait_start(self, poll=0.001, timeout=2):
        logger.debug('Waiting for MCA to start acquiring.')
        while self.acquiring.get() == 0 and timeout > 0:
            timeout -= poll
            time.sleep(poll)
        if timeout <= 0:
            logger.warning('Timed out waiting for MCA to start acquiring')
            return False
        return True

    def wait_stop(self, poll=0.001, timeout=30):
        logger.debug('Waiting for MCA to finish acquiring.')
        while self.acquiring.get() == 1 and timeout > 0:
            timeout -= poll
            time.sleep(poll)
        if timeout <= 0:
            logger.warning('Timed out waiting for MCA finish acquiring')
            return False
        return True

    def update_progress(self, increment):
        self.progress_value += increment
        self.set_state(progress=min(self.progress_value, 1))
        return True

    def on_count_time(self, obj, val):
        req_time = self.count_time.get()
        if not req_time:
            return
        pct = 100.0 * val / req_time
        self.set_state(dead_time=pct)

    def on_state_changed(self, obj, state):
        if state == 1:
            self.set_state(busy=True)
        else:
            self.set_state(busy=False)

    def on_new_spectrum(self, obj, value, index):
        """
        Process and emit signals when a new spectrum is recorded
        :param obj: Process Variable
        :param value: spectrum array
        :param index: element index
        """

        counts = value[self.region_of_interest[0]:self.region_of_interest[1]].sum()

        self.set_state(counts=(index, counts), spectra=(index, value))


class XFlashMCA(BaseMCA):
    """
    mcaRecord based single element fluorescence detector object.

    :param root: (str), Root PV name of the mcaRecord.
    :param channels: (int), Number of channels.
    """
    count_time_fbk: epics.PV

    def __init__(self, root, channels=4096, descr='XFlash MCA'):
        super().__init__(root, elements=1, channels=channels)
        self.name = descr

    def custom_setup(self, root, **kwargs):
        self.start_cmd = self.add_pv(f"{root}:mca1.ERST")
        self.mode_cmd = self.add_pv(f"{root}:Rontec1SetMode")
        self.stop_cmd = self.add_pv(f"{root}:mca1.STOP")
        self.mca_data = [self.add_pv(f"{root}:mca{d + 1:d}") for d in range(self.elements)]

        self.acquiring = self.add_pv(f"{root}:mca1.ACQG")
        self.acquiring.connect('changed', self.schedule_warmup) # schedule a warmup at the end of every acquisition

        self.count_time = self.add_pv(f"{root}:mca1.PRTM")
        self.count_time_fbk = self.add_pv(f"{root}:mca1.ERTM")
        self.slope = self.add_pv(f"{root}:mca1.CALS")
        self.offset = self.add_pv(f"{root}:mca1.CALO")
        self.temperature = self.add_pv(f"{root}:Rontec1Temperature")

        self.count_time_fbk.connect("changed", self.on_progress_time)


    def configure(self, **kwargs):
        for k, v in kwargs.items():
            if k == 'cooling':
                if v:
                    self.cooldown()
                else:
                    self.warmup()
        super().configure(**kwargs)

    def cooldown(self):
        if self.warmup_monitor:
             GLib.source_remove(self.warmup_monitor)
             self.warmup_monitor = None
        self.mode_cmd.put(1)

    def warmup(self):
        self.mode_cmd.put(0)
        self.warmup_monitor = None

    def schedule_warmup(self, obj, val):
        if val == 0:
            if self.warmup_monitor:
                GLib.source_remove(self.warmup_monitor)
                self.warmup_monitor = None
            self.warmup_monitor = GLib.timeout_add(WARMUP_TIMEOUT, self.warmup)

    def get_count_rates(self):
        # get IRC and OCR tuple
        return [(-1, -1)]

    def on_progress_time(self, obj, value):
        total = self.count_time.get()
        if total:
            self.set_state(progress=min(1.0, value/total))

    def update_progress(self, increment):
        return True

class QuantaxMCA(XFlashMCA):
    """
    Quantax XFlashQM100 MCA Device.

    :param root: (str), Root PV name of the mcaRecord.
    :param channels: (int), Number of channels.
    """

    def __init__(self, root, channels=4096):
        super().__init__(root, channels=channels, descr='Quantax XFlash MCA')

    def custom_setup(self, root, **kwargs):
        self.mca_data = [self.add_pv(f"{root}:mca1")]
        self.start_cmd = self.add_pv(f"{root}:CMD:start")
        self.stop_cmd = self.add_pv(f"{root}:CMD:stop")
        self.input_counts = self.add_pv(f'{root}:counts:inp')
        self.output_counts = self.add_pv(f'{root}:counts:out')

        self.temperature = self.add_pv(f"{root}:temperature")
        self.slope = self.add_pv(f"{root}:slope")
        self.offset = self.add_pv(f"{root}:offset")
        self.acquiring = self.add_pv(f"{root}:running")
        self.progress = self.add_pv(f"{root}:progress")
        self.mode_cmd = self.add_pv(f"{root}:SET:mode")
        self.count_time = self.add_pv(f"{root}:SET:realtime")

        # schedule a warmup at the end of every acquisition
        self.acquiring.connect('changed', self.schedule_warmup)
        self.progress.connect('changed', self.on_progress)


    def get_count_rates(self):
        # get IRC and OCR tuple
        return [(self.input_counts.get(), self.output_counts.get())]

    def update_progress(self, *args):
        return True

    def on_progress(self, obj, value):
        self.set_state(progress=value/100)


class VortexMCA(BaseMCA):
    """
    EPICS based 4-element Vortex ME4 detector object.
    """
    count_time_fbk: epics.PV

    def __init__(self, name, channels=2048):
        BaseMCA.__init__(self, name, elements=4, channels=channels)
        self.name = 'Vortex MCA'

    def custom_setup(self, root, **kwargs):
        self.mca_data = [self.add_pv(f"{root}:mca{d + 1:d}") for d in range(self.elements)]
        self.mca_data.append(self.add_pv(f"{root}:mcaCorrected"))
        self.stop_cmd = self.add_pv("%s:mca1.STOP" % root)
        self.start_cmd = self.add_pv(f"{root}:EraseStart")

        self.count_time = self.add_pv(f"{root}:PresetReal")
        self.count_time_fbk = self.add_pv(f"{root}:DeadTime")
        self.acquiring = self.add_pv(f"{root}:Acquiring")

        self.input_counts = [
            self.add_pv(f"{root}:dxp1.ICR"),
            self.add_pv(f"{root}:dxp2.ICR"),
            self.add_pv(f"{root}:dxp3.ICR"),
            self.add_pv(f"{root}:dxp4.ICR")]

        self.output_counts = [
            self.add_pv(f"{root}:dxp1.OCR"),
            self.add_pv(f"{root}:dxp2.OCR"),
            self.add_pv(f"{root}:dxp3.OCR"),
            self.add_pv(f"{root}:dxp4.OCR")]

        # Calibration parameters
        self.slope = self.add_pv(f"{root}:mca1.CALS")
        self.offset = self.add_pv(f"{root}:mca1.CALO")

        # Signal handlers
        self.acquiring.connect('changed', self.on_state_changed)
        self.count_time_fbk.connect('changed', self.on_count_time)

    def get_count_rates(self):
        return [(icr.get(), ocr.get()) for icr, ocr in zip(self.input_counts, self.output_counts)]


SIM_XRF_TEMPLATE = os.path.join(APP_DIR, 'share/data/simulated/xrf_{:03d}.raw')
SIM_XRF_FILES = [1, 2, 3]


class SimMCA(BaseMCA):
    """
    Simulated MCA detector.
    """

    def __init__(self, root, energy=None, channels=4096):
        self.energy = energy
        self._acquiring = False
        self.half_life = 60 * 30  # 1 hr
        self.start_time = time.time()
        self.roi_counts = []
        self._raw_data = None
        self._slope = 0
        self._offset = 0
        self._count_source = None

        super().__init__(root, elements=1, channels=channels)
        self.name = root
        self.scales = [1 - random.random() * 0.3 for i in range(self.elements)]

    def custom_setup(self, *args, **kwargs):
        # Default parameters
        self.mca_data = []
        self._slope = 17.0 / 3298  # 50000     #0.00498
        self._offset = -96.0 * self._slope  # 9600 #-0.45347
        self.roi_counts = [0.0] * self.elements
        self.set_state(active=True, health=(0, '', ''))

    def update_spectrum(self, edge):
        fwhm = 0.01
        self.start_time = time.time()
        offset = random.random()/2
        x = numpy.linspace(edge - 0.5, edge + 1, 1000)
        y = (
            fitting.step_response(x, [0.5 + offset, fwhm, edge, 0]) +
            fitting.gauss(x, [0.5 + 0.5-offset, fwhm, edge + fwhm * 0.5, 0]) +
            numpy.random.uniform(0.01, 0.02, len(x))
        )
        self._count_source = interpolate.interp1d(x, 5000 * y, kind='cubic', assume_sorted=True)

    def configure(self, **kwargs):
        super().configure(**kwargs)
        self.update_spectrum(kwargs.get('edge', 12.658))

    def channel_to_energy(self, x):
        return self._slope * x + self._offset

    def energy_to_channel(self, y):
        return int((y - self._offset) / self._slope)

    def count(self, duration):
        self.acquire_data(duration)

        val = duration * self._count_source(self.energy.get_position())
        self.roi_counts = [self.scales[i] * val for i in range(self.elements)]

        self.set_state(dead_time=random.random() * 51.0)
        return sum(self.roi_counts)

    def acquire_data(self, t=1.0):
        self._acquiring = True
        time.sleep(t)
        self._acquiring = False
        filename = SIM_XRF_TEMPLATE.format(random.choice(SIM_XRF_FILES))
        logger.debug('Simulated Spectrum: {}'.format(filename))
        self._raw_data = numpy.loadtxt(filename, comments="#")
        self.set_state(dead_time=random.random() * 51.0)

        for i in range(self.elements):
            self.data[:, i] = (1-0.25*random.random())*self._raw_data[:, 1]

        corrected = (self.data - self.dark)
        self.spectra[:, 0] = self.channel_to_energy(numpy.arange(0, self.channels, 1))
        self.spectra[:, 1] = corrected.sum(1)
        self.spectra[:, 2:] = self.data

    def acquire_dark(self, t=1.0):
        self.dark[:] = 0
        return self.dark

    def stop(self, wait=False):
        pass

    def wait(self):
        time.sleep(0.5)


__all__ = ['XFlashMCA', 'VortexMCA', 'QuantaxMCA', 'SimMCA']
