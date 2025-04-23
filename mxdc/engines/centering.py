from __future__ import annotations

import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy
import scipy.stats
import yaml

from mxdc import Registry, Engine, Device
from mxdc.devices.interfaces import ICenter
from mxdc.utils import imgproc, datatools, converter, misc
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
    snapshots: bool
    directory: str | None
    name: str | None
    results: dict

    def __init__(self):
        super().__init__()
        self.name = 'Auto Centering'
        self.method = None
        self.method_name = 'loop'
        self.device = None
        self.score = 0.0
        self.snapshots = True
        self.directory = None
        self.name = None
        self.start_time = 0
        self.results = {}

        self.methods = {
            'loop': self.center_external,
            'crystal': self.center_external,
            'capillary': self.center_capillary,
            'diffraction': self.center_diffraction,
            'external': self.center_external,
        }

    def configure(self, method='loop', **kwargs):
        from mxdc.controllers.samplestore import ISampleStore
        from mxdc.engines.rastering import IRasterCollector
        self.method_name = method
        self.sample_store = Registry.get_utility(ISampleStore)
        self.collector = Registry.get_utility(IRasterCollector)
        self.device = Registry.get_utility(ICenter)

        if method in self.methods:
            self.method = self.methods[method]
        elif self.device:
            self.method = self.center_external
        else:
            self.method = self.center_loop

        for key in ['snapshots', 'directory', 'name']:
            if key in kwargs:
                setattr(self, key, kwargs[key])

        if not (self.directory and self.name):
            self.snapshots = False

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

        total_range = 180
        recorder = imgproc.LoopRecorder(self.beamline.goniometer.omega, total_range,  self.device)
        recorder.start()
        self.beamline.goniometer.omega.move_by(total_range, wait=True)
        recorder.stop()

        if recorder.has_objects():
            face_angle = recorder.get_face_angle()
            logger.info(f'Centering on loop face ... {face_angle:0.2f}')
            self.beamline.goniometer.omega.move_to(face_angle, wait=True)

        return recorder

    def find_loop(self):
        """
        Rotate the sample to try and find an object
        """

        total_range = 180
        recorder = imgproc.LoopRecorder(self.beamline.goniometer.omega, total_range,  self.device)
        recorder.start()
        self.beamline.goniometer.omega.move_by(total_range, wait=True)
        recorder.stop()

        if recorder.has_objects():
            face_angle = recorder.get_face_angle()
            self.beamline.goniometer.omega.move_to(face_angle, wait=True)

        return recorder

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
        self.start_time = time.time()
        with self.beamline.lock:
            self.emit('started', None)
            self.take_snapshot(index=0)
            try:
                self.method()
            except Exception as e:
                logger.exception(e)
                self.emit('error', str(e))
            else:
                self.emit('done', None)
            self.take_snapshot(index=1)
            self.save_results()

        logger.info(
            'Centering Done in {:0.1f} seconds [Confidence={:0.0f}%]'.format(
                time.time() - self.start_time, self.score
            )
        )
        return self.results

    def center_external(self, label='loop', trials=4):
        """
        External centering device
        :param trials: Number of trials to perform
        :param label: 'loop' or 'crystal'
        """
        if not (self.device and self.device.is_active()):
            logger.warning('External centering device not present/active')
            return self.center_loop()

        good_trials = 0
        max_trials = 8
        omega_step = 90
        valid_objects = ['loop', 'crystal', 'pin']
        recorder = None
        steps = []

        for i in range(max_trials):
            step = {'trial': i, 'looking_for': valid_objects}

            last_trial = (good_trials >= trials - 1)
            if i > 0 and not last_trial:
                self.beamline.goniometer.omega.move_by(omega_step, wait=True)
                step['omega_step'] = omega_step

            elif last_trial:
                recorder = self.loop_face()
                step['loop_face'] = recorder.get_face_angle()

            # find first valid object, loop first then crystal then pin
            objects = self.device.wait(2)
            for kind in valid_objects:
                if kind in objects:
                    found = objects[kind]
                    break
            else:
                found = None

            if found:
                cx, cy = found.x, found.y
                reliability = found.score
                label = found.label

                logger.debug(f'... {label} found at {cx}, {cy}, Confidence={reliability}')
                xmm, ymm = self.position_to_mm(cx, cy)
                self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
                logger.debug(f'Adjustment: {-xmm:0.4f}, {-ymm:0.4f}')
                good_trials += 1
                if good_trials > 2:
                    valid_objects = ['loop', 'xtal']    # ignore pins after two good trials

                omega_step = 90
                step['object_found'] = found
                step['adjustment'] = [float(-xmm), float(-ymm)]
            else:
                step['object_found'] = None
                reliability = 0.0
                logger.warning('... No object found in field-of-view')

            step['reliability'] = reliability
            steps.append(step)

            if good_trials >= trials:
                break

        # calculate score
        if recorder and recorder.has_objects():
            score_info = recorder.get_stats()
            self.score = score_info['score'].avg * 100
        else:
            self.score = 0.0

        self.results = {
            'method': self.method_name,
            'score': self.score,
            'trials': good_trials,
            'steps': steps,
        }

    def take_snapshot(self, index=0):
        """
        Take a snapshot of the current frame
        :param index: Index of the snapshot
        """
        if self.snapshots:
            self.beamline.dss.setup_folder(self.directory, misc.get_project_name())
            file_path = Path(self.directory)
            file_name = f"{self.name}-{index}.png"

            # take snapshot
            self.beamline.sample_camera.save_frame(file_path / file_name)
            logger.debug(f'Snapshot saved... {file_name}')

    def save_results(self):
        """
        Save the results of the centering process to a YAML file
        """
        if not self.directory:
            return
        self.results['duration'] = time.time() - self.start_time
        filename = Path(self.directory) / 'centering.yml'
        with open(filename, 'w') as file:
            yaml.dump(self.results, file)
            logger.info(f'Centering results saved to {filename}')

    def center_loop(self, trials=6):
        self.beamline.sample_frontlight.set_off()

        # Find tip of loop
        failed = True
        steps = []
        for i in range(trials):
            step = {'trial': i}
            last_trial = (i == trials - 1)
            if 0 < i < trials - 1:
                cur_pos = self.beamline.goniometer.omega.get_position()
                self.beamline.goniometer.omega.move_to((90 + cur_pos) % 360, wait=True)
                step['omega_step'] = 90

            elif last_trial and not failed:
                self.loop_face()
                step['loop_face'] = self.beamline.goniometer.omega.get_position()

            angle, info = self.get_features()
            self.score = info.get('score', 0.0)
            failed = (info['found'] == 0)
            step['object_found'] = info

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
                steps.append(step)
                continue
            xmm, ymm = self.position_to_mm(x, y)
            step['adjustment'] = [float(-xmm), float(-ymm)]
            self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
            logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))
            steps.append(step)
        if failed:
            logger.error('Sample not found. Centering Failed!')

        self.beamline.sample_frontlight.set_on()
        self.results = {
            'method': self.method_name,
            'score': float(self.score),
            'trials': trials,
            'steps': steps,
        }

    def center_crystal(self):
        return self.center_loop()

    def center_diffraction(self):
        self.center_loop()
        steps = {'loop': self.results}
        scores = [self.score]

        if self.score < 0.25:
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

            steps[step] = {
                'parameters': params,
                'scores': grid_scores,
            }

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
        self.results = {
            'method': self.method_name,
            'score': float(self.score),
            'trials': 3,
            'steps': steps
        }

    def center_capillary(self, trials=5):
        self.beamline.sample_frontlight.set_off()
        steps = []
        # Find tip of loop
        failed = True
        info = {}
        half_width = self.beamline.sample_video.size[0] // 2
        for i in range(trials):
            step = {'trial': i}
            last_trial = (i == trials - 1)
            if i > 0 and not last_trial:
                cur_pos = self.beamline.goniometer.omega.get_position()
                self.beamline.goniometer.omega.move_to((90 + cur_pos) % 360, wait=True)

            angle, info = self.get_features()
            step['object_found'] = info
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
                steps.append(step)
                continue

            xmm, ymm = self.position_to_mm(x, y)
            self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
            step['adjustment'] = [float(-xmm), float(-ymm)]
            logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))
            steps.append(step)

        self.score = info.get('score', 0.0)
        if failed:
            logger.error('Capillary not found. Centering Failed!')

        self.beamline.sample_frontlight.set_on()
        self.results = {
            'method': self.method_name,
            'score': float(self.score),
            'trials': trials,
            'steps': steps,
        }
