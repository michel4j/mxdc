from __future__ import annotations

import time
import traceback
import uuid
from datetime import datetime
from typing import Any

import cv2
import numpy
import scipy.stats

from mxdc import Registry, Engine, Device
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
    sample_store: Any
    collector: Engine | None
    device: Device | None
    method: callable
    score: float

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
            self.method = self.center_external
        else:
            self.method = self.center_loop

    def position_to_mm(self, x: int, y: int) -> tuple:
        """
        Convert position in pixel coordinates to mm offset from the center
        :param x: x pixel coordinate
        :param y: y pixel coordinate
        :return: Tuple of x, y in mm
        """
        mm_scale = self.beamline.camera_scale.get()
        cx, cy = numpy.array(self.beamline.sample_video.size) * 0.5
        xmm = (cx - x) * mm_scale
        ymm = (cy - y) * mm_scale
        return xmm, ymm

    def pixel_to_mm(self, pixels):
        """
        Convert pixels to mm
        :param pixels: single value or array of pixel values
        :return: Float or array of floats
        """
        return self.beamline.camera_scale.get() * pixels

    def loop_face(self):
        """
        Rotate the sample to the widest face of the loop
        """

        start_angle = self.beamline.goniometer.omega.get_position()
        recorder = imgproc.LoopRecorder(self.beamline)
        recorder.start()
        self.beamline.goniometer.omega.move_by(180, wait=True)
        recorder.stop()

        heights = recorder.get_heights()
        angles = numpy.linspace(start_angle, start_angle + 180, len(heights))
        face_angle = angles[numpy.argmin(heights)] - 90
        self.beamline.goniometer.omega.move_to(face_angle % 360, wait=True)

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

    def center_external(self, label='loop', trials=3):
        """
        External centering device
        :param trials: Number of trials to perform
        :param label: 'loop' or 'crystal'
        """
        if not (self.device and self.device.is_active()):
            logger.warning('External centering device not present/active')
            self.score = 0.0
            return

        scores = []
        for i in range(trials):
            last_trial = (i == trials - 1)
            if i > 0 and not last_trial:
                cur_pos = self.beamline.goniometer.omega.get_position()
                self.beamline.goniometer.omega.move_to((90 + cur_pos) % 360, wait=True)
            elif last_trial:
                self.loop_face()

            found = self.device.wait(2)
            if found is not None:
                cx, cy, reliability, label = found
                logger.debug(f'... {label} found at {cx}, {cy}, Confidence={reliability}')
                xmm, ymm = self.position_to_mm(cx, cy)
                self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
                logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))
            else:
                reliability = 0.0
                logger.warning('... No object found in field-of-view')
            scores.append(reliability)

        self.score = 100 * numpy.mean(scores)

    def center_loop(self, trials=4):
        self.beamline.sample_frontlight.set_off()

        # Find tip of loop
        failed = True
        info = {}
        for i in range(trials):
            last_trial = (i == trials - 1)
            if 0 < i < trials - 1:
                cur_pos = self.beamline.goniometer.omega.get_position()
                self.beamline.goniometer.omega.move_to((90 + cur_pos) % 360, wait=True)
            elif last_trial and not failed:
                self.loop_face()

            angle, info = self.get_features()
            self.score = info.get('score', 0.0)
            failed = (info['found'] == 0)

            if info['found'] == 0:
                logger.warning('Loop not found in field-of-view')
                logger.warning('Attempting to translate into view')
                x, y = info['x'], info['y']
            elif not last_trial:
                x, y = info['x'], info['y'] if i == 0 else info.get('loop-y', info['y'])
                logger.debug('... tip found at {}, {}'.format(x, y))
            elif last_trial and info['found'] == 2:
                x, y = info.get('loop-x', info.get('x')), info.get('loop-y', info.get('y'))
            else:
                continue
            xmm, ymm = self.position_to_mm(x, y)
            self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
            logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))

        if failed:
            logger.error('Sample not found. Centering Failed!')
            info = {}

        self.beamline.sample_frontlight.set_on()
        return info

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
        exposure = self.beamline.config.raster.exposure
        det_exp_limit = 1 / self.beamline.config.raster.max_freq
        mtr_exp_limit = aperture * 1e-3 / self.beamline.config.raster.max_speed
        exposure = max(exposure, det_exp_limit, mtr_exp_limit)

        for step in ['face', 'edge']:
            logger.info('Performing raster scan on {}'.format(step))
            self.beamline.goniometer.wait(start=False)
            if step == 'edge':
                self.beamline.goniometer.omega.move_by(90, wait=True)
            angle, info = self.get_features()
            width = self.pixel_to_mm(1.75 * abs(info['x'] - info['loop-x'])) * 1e3  # in microns
            height = self.pixel_to_mm(info['loop-height']) * 1e3  # in microns
            width = max(width, height)

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
                params.update({'hsteps': 1, 'vsteps': int(height * 3 // aperture)})
            else:
                params.update({'hsteps': int(width * 1.2 // aperture), 'vsteps': int(height * 1.2 // aperture)})

            params = datatools.update_for_sample(
                params, sample=self.sample_store.get_current(), session=self.beamline.session_key
            )
            logger.info('Finding best diffraction spot in grid')
            self.collector.configure(params)
            self.collector.run(switch_to_center=(step == "edge"))

            # wait for results
            while not self.collector.is_complete():
                time.sleep(.1)

            grid_config = self.collector.get_grid()

            grid_scores = grid_config['grid_scores']  # gaussian_filter(grid_config['grid_scores'], 2, mode='reflect')
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

    def center_capillary(self, trials=5):
        self.beamline.sample_frontlight.set_off()

        # Find tip of loop
        failed = True
        info = {}
        half_width = self.beamline.sample_video.size[0] // 2
        for i in range(trials):
            last_trial = (i == trials - 1)
            if i > 0 and not last_trial:
                cur_pos = self.beamline.goniometer.omega.get_position()
                self.beamline.goniometer.omega.move_to((90 + cur_pos) % 360, wait=True)

            angle, info = self.get_features()

            if info['found']:
                failed = False
                x, y = info['capillary-x'], info['capillary-y']
                logger.debug('... capillary found at {}, {}'.format(x, y))
            elif i == 0:
                x, y = info['x'], info['y']
                if x <= half_width:
                    logger.warning('Capillary does not fill view')
                    logger.warning('Attempting to translate')
                    x = 0
                logger.warning('Capillary not found in field-of-view')
            else:
                continue


            xmm, ymm = self.position_to_mm(x, y)
            self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
            logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))

        self.score = info.get('score', 0.0)
        if failed:
            logger.error('Capillary not found. Centering Failed!')
            info = {}

        self.beamline.sample_frontlight.set_on()
        return info
