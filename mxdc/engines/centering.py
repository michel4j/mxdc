import time
import traceback
import uuid
from datetime import datetime

import cv2
import numpy
import scipy.stats
from scipy.ndimage import gaussian_filter

from mxdc import Registry, Engine
from mxdc.devices.interfaces import ICenter
from mxdc.utils import imgproc, datatools, converter
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)

RASTER_DELTA = 0.1
RASTER_EXPOSURE = 0.1
RASTER_RESOLUTION = 2

SAMPLE_SHIFT_STEP = 0.2  # mm
CENTERING_ZOOM = 2
CENTERING_BLIGHT = 50.0
CENTERING_FLIGHT = 0
MAX_TRIES = 5


class Centering(Engine):

    def __init__(self):
        super().__init__()
        self.name = 'Auto Centering'
        self.method = None
        self.device = None
        self.score = 0.0
        self.methods = {
            'loop': self.center_loop,
            'crystal': self.center_crystal,
            'capillary': self.center_capillary,
            'diffraction': self.center_diffraction,
            'external': self.center_external,
        }

    def configure(self, method='loop'):

        from mxdc.controllers.samplestore import ISampleStore
        from mxdc.engines.rastering import IRasterCollector

        self.sample_store = Registry.get_utility(ISampleStore)
        self.collector = Registry.get_utility(IRasterCollector)
        self.device = Registry.get_utility(ICenter)

        if method in self.methods:
            self.method = self.methods[method]
        elif self.device:
            self.method = self.center_external()
        else:
            self.method = self.center_loop

    def screen_to_mm(self, x, y):
        mm_scale = self.beamline.camera_scale.get()
        cx, cy = numpy.array(self.beamline.sample_video.size) * 0.5
        xmm = (cx - x) * mm_scale
        ymm = (cy - y) * mm_scale
        return xmm, ymm

    def pixel_to_mm(self, pixels):
        return self.beamline.camera_scale.get() * pixels

    def loop_face(self):
        heights = []
        angle, info = self.get_features()
        heights.append((angle, info.get('loop-height', 0.0)))
        for i in range(5):
            self.beamline.goniometer.omega.move_by(20, wait=True)
            angle, info = self.get_features()
            heights.append((angle, info.get('loop-height', 0.0)))

        values = numpy.array(heights)
        best = values[numpy.argmax(values[:, 1]), 0]
        self.beamline.goniometer.omega.move_to(best, wait=True)

    def get_video_frame(self):
        self.beamline.goniometer.wait(start=False, stop=True)
        self.beamline.sample_video.fetch_frame()
        raw = self.beamline.sample_video.get_frame()
        return cv2.cvtColor(numpy.asarray(raw), cv2.COLOR_RGB2BGR)

    def get_features(self):
        angle = self.beamline.goniometer.omega.get_position()
        frame = self.get_video_frame()
        info = imgproc.get_loop_features(frame, orientation=self.beamline.config.orientation)
        return angle, info

    def run(self):
        self.score = 0.0
        start_time = time.time()
        with self.beamline.lock:
            self.emit('started', None)
            try:
                self.method()
            except Exception as e:
                traceback.print_exc()
                self.emit('error', str(e))
            else:
                self.emit('done', None)
        logger.info(
            'Centering Done in {:0.1f} seconds [Confidence={:0.0f}%]'.format(
                time.time() - start_time, self.score
            )
        )

    def center_external(self, low_trials=2, med_trials=2):
        """
        External centering device
        :param low_trials: Number of trials at low resolution
        :param med_trials: Number of trials at high resolution
        """
        if not self.device:
            logger.warning('External centering device not present')
            self.score = 0.0
            return

        trials = 5
        scores = []
        for i in range(trials):
            found = self.device.wait(2)
            if found:
                x, y, reliability, label = self.device.fetch()
                logger.debug(f'... {label} found at {x}, {y}, Confidence={reliability}')
                scores.append(reliability)
                if reliability > 0.5:
                    xmm, ymm = self.screen_to_mm(x, y)
                    self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0)
                    time.sleep(1.5)
                    logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))
            else:
                reliability = 0.0
            scores.append(reliability)
            if i < (trials - 1):
                cur_pos = self.beamline.goniometer.omega.get_position()
                self.beamline.goniometer.omega.move_to((90 + cur_pos) % 360, wait=True)

        self.score = 100*numpy.mean(scores)

    def center_loop(self, trials=5, face=True):
        self.beamline.sample_frontlight.set_off()
        zoom = self.beamline.config.zoom.centering

        # Find tip of loop at low and high zoom
        failed = False
        self.beamline.sample_video.zoom(zoom, wait=True)
        for i in range(trials):
            if i != 0:
                cur_pos = self.beamline.goniometer.omega.get_position()
                self.beamline.goniometer.omega.move_to((90 + cur_pos) % 360, wait=True)

            angle, info = self.get_features()
            if info['found'] == 0:
                logger.warning('Loop not found in field-of-view')
                logger.warning('Attempting to translate into view')
                x, y = info['x'], info['y']
                xmm, ymm = self.screen_to_mm(x, y)
                self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
            else:
                if i > 2:
                    x, y = info['x'], info['loop-y']
                else:
                    x, y = info['x'], info['y']
                logger.debug('... tip found at {}, {}'.format(x, y))
                xmm, ymm = self.screen_to_mm(x, y)
                self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
                logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))

        # Center in loop on loop face
        if not failed:
            self.beamline.sample_video.zoom(zoom + 1, wait=True)  # higher zoom gives better ellipses
            self.loop_face()
            angle, info = self.get_features()
            if info['found'] == 2:
                xmm, ymm = self.screen_to_mm(info.get('loop-x', info.get('x')), info.get('loop-y', info.get('y')))
                self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
                logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))
            self.score = info['score']
            return info
        else:
            self.score = 0.0
            logger.error('Sample not found. Centering Failed!')
            return {}

    def center_crystal(self):
        return self.center_loop()

    def center_diffraction(self):
        info = self.center_loop()
        scores = [self.score]

        if self.score < 0.5 or 'loop-x' not in info:
            logger.error('Loop-centering failed, aborting diffraction centering!')
            return

        scores.append(self.score)
        aperture = self.beamline.aperture.get()

        resolution = RASTER_RESOLUTION
        energy = self.beamline.energy.get_position()
        exposure =  self.beamline.config.raster.exposure
        det_exp_limit = 1/self.beamline.config.raster.max_freq
        mtr_exp_limit = aperture*1e-3/self.beamline.config.raster.max_speed
        exposure = max(exposure, det_exp_limit, mtr_exp_limit)

        #self.beamline.goniometer.omega.move_by(90, wait=True)
        for step in ['face', 'edge']:
            logger.info('Performing raster scan on {}'.format(step))
            self.beamline.goniometer.wait(start=False)
            if step == 'edge':
                self.beamline.goniometer.omega.move_by(90, wait=True)
            angle, info = self.get_features()
            width = self.pixel_to_mm(1.75*abs(info['x'] - info['loop-x'])) * 1e3  # in microns
            height = self.pixel_to_mm(info['loop-height']) * 1e3  # in microns

            params = {
                'name': datetime.now().strftime('%y%m%d-%H%M'),
                'uuid': str(uuid.uuid4()),
                'activity': 'raster',
                'energy': energy,
                'delta': RASTER_DELTA,
                'exposure': exposure,
                'attenuation': self.beamline.attenuator.get_position(),
                'aperture': aperture,
                'distance': converter.resol_to_dist(
                    resolution, self.beamline.detector.mm_size, energy
                ),
                'origin': self.beamline.goniometer.stage.get_xyz(),
                'resolution': resolution,
                'angle': self.beamline.goniometer.omega.get_position(),

            }
            if step == 'edge':
                params.update({'hsteps': 1, 'vsteps':   int(height*2//aperture)})
            else:
                params.update({'hsteps': int(width*1.2//aperture), 'vsteps': int(height*1.2//aperture)})

            params = datatools.update_for_sample(
                params, sample=self.sample_store.get_current(), session=self.beamline.session_key
            )
            logger.info('Finding best diffraction spot in grid')
            self.collector.configure(params)
            self.collector.run(centering=(step == "edge"))

            # wait for results
            while not self.collector.is_complete():
                time.sleep(.1)

            grid_config = self.collector.get_grid()

            grid_scores = grid_config['grid_scores'] #gaussian_filter(grid_config['grid_scores'], 2, mode='reflect')
            best = numpy.unravel_index(grid_scores.argmax(axis=None), grid_scores.shape)

            best_score = grid_scores[best]
            best_index = grid_config['grid_index'].index(best)
            point = grid_config['grid_xyz'][best_index]
            score = scipy.stats.percentileofscore(grid_scores.ravel(), best_score)
            logger.info(f'Best diffraction at {best_index}: score={score:0.1f}%')
            self.beamline.goniometer.stage.move_xyz(point[0], point[1], point[2], wait=True)

            scores.append(score)
            self.beamline.goniometer.save_centering()

        self.beamline.low_dose.off()
        self.score = numpy.mean(scores)

    def center_capillary(self):
        zoom = self.beamline.config.zoom.centering
        self.beamline.sample_frontlight.set_off()
        self.beamline.sample_video.zoom(zoom, wait=True)

        scores = []
        half_width = self.beamline.sample_video.size[0] // 2
        for j in range(8):
            self.beamline.goniometer.stage.wait()
            self.beamline.goniometer.omega.move_by(90, wait=True)
            angle, info = self.get_features()
            if 'x' in info and 'y' in info:
                x = info['x'] - half_width
                ypix = info['capillary-y'] if 'capillary-y' in info else info['y']
                xmm, ymm = self.screen_to_mm(x, ypix)
                if j > 4:
                    xmm = 0.0

                if not self.beamline.goniometer.stage.is_busy():
                    self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0)
                scores.append(1.0)
            else:
                scores.append(0.5 if 'x' in info or 'y' in info else 0.0)
            logger.debug('Centering: {}'.format(info))
        self.score = numpy.mean(scores)
