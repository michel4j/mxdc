import time
import traceback
import uuid
from datetime import datetime

import cv2
import numpy
from gi.repository import GLib

from mxdc import Registry, Engine
from mxdc.utils import imgproc, datatools, misc, converter
from mxdc.utils.log import get_module_logger

from mxdc.devices.interfaces import ICenter

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)

RASTER_DELTA = 0.5
RASTER_EXPOSURE = 0.5
RASTER_RESOLUTION = 2

SAMPLE_SHIFT_STEP = 0.2  # mm
CENTERING_ZOOM = 2
CENTERING_BLIGHT = 65.0
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
        mm_scale = self.beamline.sample_video.resolution
        cx, cy = numpy.array(self.beamline.sample_video.size) * 0.5
        xmm = (cx - x) * mm_scale
        ymm = (cy - y) * mm_scale
        return xmm, ymm

    def loop_face(self, down=False):
        heights = []
        self.beamline.goniometer.wait(start=False, stop=True)
        cur = self.beamline.goniometer.omega.get_position()
        self.beamline.goniometer.omega.wait(start=True, stop=False)
        for angle in numpy.arange(0, 80, 20):
            self.beamline.goniometer.omega.move_to(angle + cur, wait=True)
            img = self.beamline.sample_video.get_frame()
            height = imgproc.mid_height(img)
            heights.append((angle + cur, height))
        values = numpy.array(heights)
        best = values[numpy.argmax(values[:, 1]), 0]
        if down:
            best -= 90.0
        self.beamline.goniometer.omega.move_to(best, wait=True)

    def get_video_frame(self):
        self.beamline.goniometer.wait(start=False, stop=True)
        raw = self.beamline.sample_video.get_frame()
        return cv2.cvtColor(numpy.asarray(raw), cv2.COLOR_RGB2BGR)

    def get_features(self):
        angle = self.beamline.goniometer.omega.get_position()
        frame = self.get_video_frame()
        scale = 256. / frame.shape[1]
        info = imgproc.get_loop_features(frame, scale=scale, orientation=self.beamline.config['orientation'])
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
            'Centering Done in {:0.1f} seconds [Reliability={:0.0f}%]'.format(
                time.time() - start_time, 100 * self.score
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

        self.beamline.sample_frontlight.set_off()
        low_zoom, med_zoom, high_zoom = self.beamline.config['zoom_levels']

        max_trials = low_trials + med_trials
        trial_count = 0
        scores = []
        failed = False
        for zoom_level, trials in [(low_zoom, low_trials), (med_zoom, med_trials)]:
            if failed:
                break

            self.beamline.sample_video.zoom(zoom_level, wait=True)

            for i in range(2):
                trial_count += 1
                for j in range(2):
                    self.beamline.goniometer.stage.wait(start=False, stop=True)
                    found = self.device.wait(2)
                    if found:
                        x, y, reliability, label = self.device.fetch()
                        scores.append(reliability)
                        logger.debug(f'... {label} found at {x}, {y}, prob={reliability}')
                        xmm, ymm = self.screen_to_mm(x, y)
                        self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
                        logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))
                    else:
                        failed = True
                        break

                # final 90 rotation not needed
                if trial_count < max_trials:
                    cur_pos = self.beamline.goniometer.omega.get_position()
                    self.beamline.goniometer.omega.move_to((90 + cur_pos) % 360, wait=True)

        self.score = numpy.mean(scores)

    def center_loop(self, low_trials=3, med_trials=2):
        self.beamline.sample_frontlight.set_off()
        low_zoom, med_zoom, high_zoom = self.beamline.config['zoom_levels']

        scores = []
        # Find tip of loop at low and high zoom
        max_trials = low_trials + med_trials
        trial_count = 0
        failed = False
        for zoom_level, trials in [(low_zoom, low_trials), (med_zoom, med_trials)]:
            if failed:
                break
            self.beamline.sample_video.zoom(zoom_level, wait=True)
            for i in range(trials):
                trial_count += 1
                angle, info = self.get_features()
                scores.append(info.get('score', 0.0))
                if info['score'] == 0.0:
                    logger.warning('Loop not found in field-of-view')
                    if (zoom_level, i) == (low_zoom, 0):
                        logger.warning('Attempting to translate into view')
                        x, y = info['x'], info['y']
                        xmm, ymm = self.screen_to_mm(x, y)
                        self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
                    else:
                        failed = True
                        break
                else:
                    x, y = info['x'], info['y']
                    logger.debug('... tip found at {}, {}'.format(x, y))
                    xmm, ymm = self.screen_to_mm(x, y)
                    self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
                    logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))

                # final 90 rotation not needed
                if trial_count < max_trials:
                    cur_pos = self.beamline.goniometer.omega.get_position()
                    self.beamline.goniometer.omega.move_to((90 + cur_pos) % 360, wait=True)

        # Center in loop on loop face
        if not failed:
            self.loop_face()
            angle, info = self.get_features()
            if info['score'] == 0.0:
                logger.warning('Sample not found in field-of-view')
            else:
                xmm, ymm = self.screen_to_mm(info.get('loop-x', info.get('x')), info.get('loop-y', info.get('y')))
                self.beamline.goniometer.stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
                logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))
            scores.append(info.get('score', 0.0))
        else:
            logger.error('Sample not found. Centering Failed!')
        self.score = numpy.mean(scores)

    def center_crystal(self):
        self.center_loop()

    def center_diffraction(self):
        self.center_loop(3, 1)
        scores = []
        if self.score < 0.5:
            logger.error('Loop-centering failed, aborting!')
            return

        scores.append(self.score)
        aperture = self.beamline.aperture.get()
        resolution = RASTER_RESOLUTION
        energy = self.beamline.energy.get_position()

        for step in ['edge', 'face']:
            logger.info('Performing raster scan on {}'.format(step))
            self.beamline.goniometer.wait(start=False)
            if step == 'face':
                self.beamline.goniometer.omega.move_by(-90, wait=True)

            time.sleep(2.0)
            params = {
                'name': datetime.now().strftime('%y%m%d-%H%M'),
                'uuid': str(uuid.uuid4()),
                'activity': 'raster',
                'energy': energy,
                'delta': RASTER_DELTA,
                'exposure': RASTER_EXPOSURE,
                'attenuation': self.beamline.attenuator.get(),
                'aperture': aperture,
                'distance': converter.resol_to_dist(
                    resolution, self.beamline.detector.mm_size, energy
                ),
                'origin': self.beamline.goniometer.stage.get_xyz(),
                'resolution': resolution,
            }
            if step == 'edge':
                params.update({
                    'angle': self.beamline.goniometer.omega.get_position(),
                    'width': min(aperture*5, 200.0),
                    'height': min(aperture*5, 200.0),
                    'frames': 5,
                    'lines': 5,
                })
            else:
                params.update({
                    'angle': self.beamline.goniometer.omega.get_position(),
                    'width': min(aperture * 4, 200.0),
                    'height': min(aperture * 4, 200.0),
                    'frames': 4,
                    'lines': 4,
                })

            params = datatools.update_for_sample(params, self.sample_store.get_current())
            logger.info('Finding best diffraction spot in grid')
            self.collector.configure(params)
            self.collector.run()

            grid_scores = numpy.array([
                (index, misc.frame_score(report)) for index, report in sorted(self.collector.results.items())
            ])

            best = grid_scores[:, 1].argmax()

            index = int(grid_scores[best, 0])
            score = grid_scores[best, 1]

            logger.info(f'Best diffraction at {index}: score={score}')
            grid = self.collector.get_grid()
            point = grid[best]

            self.beamline.goniometer.stage.move_xyz(point[0], point[1], point[2], wait=True)
            scores.append(score/100.)
        self.score = numpy.mean(scores)

    def center_capillary(self):
        low_zoom, med_zoom, high_zoom = self.beamline.config['zoom_levels']
        self.beamline.sample_frontlight.set_off()
        self.beamline.sample_backlight.set(self.beamline.config['centering_backlight'])
        self.beamline.sample_video.zoom(low_zoom, wait=True)

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
