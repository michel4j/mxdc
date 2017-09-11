import os
import pwd
import threading
import time

from gi.repository import GObject
from twisted.python.components import globalRegistry

from mxdc.com import ca
from mxdc.interface.beamlines import IBeamline
from mxdc.utils import runlists
from mxdc.utils.converter import energy_to_wavelength
from mxdc.utils.log import get_module_logger

_logger = get_module_logger(__name__)


class RasterCollector(GObject.GObject):
    __gsignals__ = {
        'new-image': (GObject.SIGNAL_RUN_LAST, None, (str,)),
        'progress': (GObject.SIGNAL_RUN_LAST, None, (float,)),
        'done': (GObject.SIGNAL_RUN_LAST, None, []),
        'paused': (GObject.SIGNAL_RUN_LAST, None, (bool, object)),
        'started': (GObject.SIGNAL_RUN_LAST, None, []),
        'stopped': (GObject.SIGNAL_RUN_LAST, None, []),
        'error': (GObject.SIGNAL_RUN_LAST, None, (str,))
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.collecting = False
        self.run_list = []
        self.runs = []
        self.results = {}
        self.config = {}
        self.total_frames = 0
        self.count = 0
        self.beamline = globalRegistry.lookup([], IBeamline)

    def configure(self, grid, parameters):
        self.config['grid'] = grid
        self.config['params'] = parameters
        self.config['frames'] = runlists.generate_grid_frames(grid, parameters)
        self.beamline.image_server.set_user(pwd.getpwuid(os.geteuid())[0], os.geteuid(), os.getegid())

    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Raster Collector')
        worker_thread.start()

    def prepare(self, params):
        # setup folder for wedge
        self.beamline.image_server.setup_folder(params['directory'])

        # make sure shutter is closed before starting
        self.beamline.exposure_shutter.close()

        # setup devices
        if abs(self.beamline.energy.get_position() - params['energy']) >= 0.0005:
            self.beamline.energy.move_to(params['energy'], wait=True)

        if abs(self.beamline.distance.get_position() - params['distance']) >= 0.1:
            self.beamline.distance.move_to(params['distance'], wait=True)

        if abs(self.beamline.attenuator.get() - params['attenuation']) >= 25:
            self.beamline.attenuator.set(params['attenuation'], wait=True)

    def run(self):
        self.paused = False
        self.stopped = False
        ca.threads_init()
        self.collecting = True
        self.beamline.detector_cover.open(wait=True)
        self.total_frames = sum([wedge['num_frames'] for wedge in self.config['wedges']])
        current_attenuation = self.beamline.attenuator.get()

        with self.beamline.lock:
            # Prepare endstation mode
            self.beamline.goniometer.set_mode('COLLECT', wait=True)
            GObject.idle_add(self.emit, 'started')
            try:
                self.acquire()
            finally:
                self.beamline.exposure_shutter.close()

        # Wait for Last image to be transferred (only if dataset is to be uploaded to MxLIVE)
        time.sleep(2.0)

        # self.results = self.save_summary(self.config['datasets'])
        # self.beamline.lims.upload_datasets(self.beamline, self.results)
        if not (self.stopped or self.paused):
            GObject.idle_add(self.emit, 'done')
        self.beamline.attenuator.set(current_attenuation)  # restore attenuation
        self.collecting = False
        self.beamline.detector_cover.close()

    def acquire(self):
        is_first_frame = True
        self.count = 0
        self.prepare(self.config['params'])
        for frame in self.config['frames']:
            if self.stopped or self.paused: break
            # Prepare image header
            detector_parameters = {
                'file_prefix': frame['dataset'],
                'start_frame': frame['first'],
                'directory': frame['directory'],
                'wavelength': energy_to_wavelength(frame['energy']),
                'energy': frame['energy'],
                'distance': frame['distance'],
                'exposure_time': frame['exposure'],
                'num_frames': 1,
                'start_angle': frame['start'],
                'delta_angle': frame['delta'],
                'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
            }
            # prepare goniometer for scan
            self.beamline.goniometer.configure(
                time=frame['exposure'], delta=frame['delta'], angle=frame['start']
            )

            if self.stopped or self.paused: break
            self.beamline.detector.set_parameters(detector_parameters)
            self.beamline.detector.start(first=is_first_frame)
            self.beamline.goniometer.scan(wait=True, timeout=frame['exposure'] * 4)
            self.beamline.detector.save()

            is_first_frame = False
            time.sleep(0)

    def analyse_image(self, cell_params=None):
        if cell_params is not None:
            cell, filename = cell_params
            self.image_queue.append((cell, filename))
        elif len(self.image_queue) == 0:
            return True

        cell, filename = self.image_queue[0]
        if os.path.exists(filename):
            self.image_queue.pop(0)
        else:
            return False
        try:
            self.pending_results.append(cell)
            _logger.info("Analyzing image: %s" % (filename))
            self.beamline.dpm.service.callRemote('analyseImage',
                                                 filename,
                                                 self.grid_parameters['directory'],
                                                 self._user_properties[0],
                                                 ).addCallbacks(self._result_ready, callbackArgs=[cell],
                                                                errback=self._result_fail, errbackArgs=[cell])
        except:
            self._result_fail(None, cell)

    def _result_ready(self, results, cell):
        GObject.idle_add(self.emit, 'new-result', cell, results)
        self.pending_results.remove(cell)

    def _result_fail(self, results, cell):
        _logger.error("Unable to process data")
        GObject.idle_add(self.emit, 'new-result', cell, results)
        self.pending_results.remove(cell)

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.stopped = True
