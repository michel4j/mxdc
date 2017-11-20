import os
import re
import threading

from gi.repository import GObject
from twisted.internet.defer import returnValue, inlineCallbacks
from twisted.python.components import globalRegistry

from mxdc.beamlines.interfaces import IBeamline
from mxdc.com import ca
from mxdc.engines.interfaces import IAnalyst
from mxdc.utils import datatools, misc
from mxdc.utils.converter import energy_to_wavelength
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class SingleCollector(GObject.GObject):
    __gsignals__ = {
        'new-image': (GObject.SIGNAL_RUN_LAST, None, (str,)),
        'result': (GObject.SIGNAL_RUN_LAST, None, (object,)),
        'done': (GObject.SIGNAL_RUN_LAST, None, []),
        'started': (GObject.SIGNAL_RUN_LAST, None, []),
        'error': (GObject.SIGNAL_RUN_LAST, None, (str,))
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.collecting = False
        self.pending_results = set()
        self.runs = []
        self.results = {}
        self.config = {}
        self.total_frames = 0
        self.count = 0

        self.beamline = globalRegistry.lookup([], IBeamline)
        self.analyst = globalRegistry.lookup([], IAnalyst)
        self.frame_link = self.beamline.detector.connect('new-image', self.on_new_image)
        self.unwatch_frames()

    def configure(self, parameters):
        frame_template = datatools.make_file_template(parameters['name'])
        self.config['params'] = parameters
        self.config['frame'] = {
            'dataset': parameters['name'],
            'uuid': parameters['uuid'],
            'saved': False,
            'first': 1,
            'frame_name': frame_template.format(1),
            'start': parameters['angle'],
            'delta': parameters['delta'],
            'exposure': parameters['exposure'],
            'energy': parameters['energy'],
            'distance': parameters['distance'],
            'two_theta': parameters.get('two_theta', 0.0),
            'attenuation': parameters.get('attenuation', 0.0),
            'directory': parameters['directory'],
        }

    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Single Frame Collector')
        worker_thread.start()

    def prepare(self, params):
        # setup folder for
        self.beamline.dss.setup_folder(params['directory'], misc.get_project_name())
        logger.debug('Setting up folder: {}'.format(params['directory']))
        # make sure shutter is closed before starting
        self.beamline.fast_shutter.close()

        if abs(self.beamline.distance.get_position() - params['distance']) >= 0.1:
            self.beamline.distance.move_to(params['distance'], wait=True)

        # switch to collect mode
        img = self.beamline.sample_camera.get_frame()
        img.save(os.path.join(self.config['params']['directory'], '{}.png'.format(self.config['params']['name'])))
        self.beamline.goniometer.set_mode('COLLECT', wait=True)

    def run(self):
        self.paused = False
        self.stopped = False
        ca.threads_init()
        self.collecting = True
        self.beamline.detector_cover.open(wait=True)
        self.total_frames = 1
        self.pending_results = set()
        self.results = {}
        current_attenuation = self.beamline.attenuator.get()

        with self.beamline.lock:
            GObject.idle_add(self.emit, 'started')
            try:
                self.acquire()
            finally:
                self.beamline.fast_shutter.close()

        GObject.idle_add(self.emit, 'done')
        self.beamline.attenuator.set(current_attenuation)  # restore attenuation
        self.collecting = False
        self.beamline.detector_cover.close()

    def acquire(self):
        self.count = 0
        self.prepare(self.config['params'])
        self.watch_frames()
        frame = self.config['frame']

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
        self.beamline.goniometer.configure(time=frame['exposure'], delta=frame['delta'], angle=frame['start'])

        self.beamline.detector.set_parameters(detector_parameters)
        self.beamline.detector.start(first=True)
        self.beamline.goniometer.scan(wait=True, timeout=frame['exposure'] * 4)
        self.beamline.detector.save()
        GObject.timeout_add(5000, self.unwatch_frames)

    def watch_frames(self):
        self.beamline.detector.handler_unblock(self.frame_link)

    def unwatch_frames(self):
        self.beamline.detector.handler_block(self.frame_link)

    def on_new_image(self, obj, file_path):
        GObject.idle_add(self.emit, 'new-image', file_path)
        self.analyse_frame(file_path)

    @inlineCallbacks
    def analyse_frame(self, file_path):
        self.pending_results.add(file_path)
        logger.info("Analyzing frame: {}".format(file_path))
        try:
            report = yield self.beamline.dps.analyse_frame(file_path, misc.get_project_name())
        except Exception as e:
            self.result_fail(e, file_path)
            returnValue({})
        else:
            self.result_ready(report, file_path)
            returnValue(report)

    def result_ready(self, result, file_path):
        info = result
        self.pending_results.remove(file_path)
        info['filename'] = file_path
        GObject.idle_add(self.emit, 'result', info)

    def result_fail(self, error, file_path):
        self.pending_results.remove(file_path)
        logger.error("Unable to process data {}".format(file_path))
        logger.error(error)