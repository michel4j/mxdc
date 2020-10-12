import os

from gi.repository import GLib
from twisted.internet.defer import returnValue, inlineCallbacks

from mxdc import Registry, Signal, Engine
from mxdc.engines.interfaces import IAnalyst
from mxdc.utils import misc
from mxdc.utils.converter import energy_to_wavelength
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


class SingleCollector(Engine):
    class Signals:
        result = Signal('result', arg_types=(object,))

    name = "Data Collector"

    def __init__(self):
        super().__init__()

        self.pending_results = set()
        self.runs = []
        self.results = {}
        self.config = {}
        self.total_frames = 0
        self.count = 0
        self.analyst = Registry.get_utility(IAnalyst)

    def configure(self, parameters):
        frame_template = self.beamline.detector.get_template(parameters['name'])
        self.config['params'] = parameters
        self.config['frame'] = {
            'name': parameters['name'],
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
        self.beamline.manager.collect(wait=True)

    def run(self):
        self.collecting = True
        self.beamline.detector_cover.open(wait=True)
        self.total_frames = 1
        self.pending_results = set()
        self.results = {}
        current_attenuation = self.beamline.attenuator.get()

        with self.beamline.lock:
            self.emit('started')
            try:
                self.acquire()
            finally:
                self.beamline.fast_shutter.close()

        self.emit('done')
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

        # perform scan
        self.beamline.detector.configure(**detector_parameters)
        self.beamline.detector.start(first=True)
        self.beamline.goniometer.scan(
            kind='simple',
            time=frame['exposure'],
            delta=frame['delta'],
            angle=frame['start'],
            wait=True,
            timeout=frame['exposure'] * 4
        )
        self.beamline.detector.save()
        file_path = os.path.join(frame['directory'], self.config['frame_name'])

        GLib.timeout_add(1000, self.analyse_frame, file_path)

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
        self.emit('result', info)

    def result_fail(self, error, file_path):
        self.pending_results.remove(file_path)
        logger.error("Unable to process data {}".format(file_path))
        logger.error(error)