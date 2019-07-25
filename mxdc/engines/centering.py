from __future__ import print_function

import threading
import time
import traceback
import uuid
from datetime import datetime

import cv2
import numpy
from gi.repository import GObject
from mxdc.beamlines.interfaces import IBeamline
from mxdc.com import ca
from mxdc.utils import imgproc, datatools, misc
from mxdc.utils.log import get_module_logger
from twisted.python.components import globalRegistry

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)
RASTER_DELTA = 0.5
_SAMPLE_SHIFT_STEP = 0.2  # mm
CENTERING_ZOOM = 2
_CENTERING_BLIGHT = 65.0
_CENTERING_FLIGHT = 0
_MAX_TRIES = 5


class Centering(GObject.GObject):
    __gsignals__ = {
        'started': (GObject.SIGNAL_RUN_LAST, None, []),
        'done': (GObject.SIGNAL_RUN_LAST, None, []),
        'error': (GObject.SIGNAL_RUN_LAST, None, (str,)),
        'message': (GObject.SIGNAL_RUN_LAST, None, (str,)),
    }
    complete = GObject.Property(type=bool, default=False)

    def __init__(self):
        super(Centering, self).__init__()
        self.name = 'Auto Centering'
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.method = None
        self.score = 0.0
        self.methods = {
            'loop': self.center_loop,
            'crystal': self.center_crystal,
            'capillary': self.center_capillary,
            'diffraction': self.center_diffraction,
        }

    def configure(self, method='loop'):
        from mxdc.controllers.microscope import IMicroscope
        from mxdc.controllers.samplestore import ISampleStore
        from mxdc.engines.rastering import IRasterCollector

        self.microscope = globalRegistry.lookup([], IMicroscope)
        self.sample_store = globalRegistry.lookup([], ISampleStore)
        self.collector = globalRegistry.lookup([], IRasterCollector)

        self.method = self.methods[method]

    def start(self):
        worker = threading.Thread(target=self.run)
        worker.setDaemon(True)
        worker.setName('Centering')
        worker.start()

    def screen_to_mm(self, x, y):
        mm_scale = self.beamline.sample_video.resolution
        cx, cy = numpy.array(self.beamline.sample_video.size) * 0.5
        xmm = (cx - x) * mm_scale
        ymm = (cy - y) * mm_scale
        return xmm, ymm

    def loop_face(self, down=False):
        heights = []
        self.beamline.goniometer.wait(start=False, stop=True)
        cur = self.beamline.omega.get_position()
        self.beamline.omega.wait(start=True, stop=False)
        for angle in numpy.arange(0, 80, 20):
            self.beamline.omega.move_to(angle + cur, wait=True)
            img = self.beamline.sample_video.get_frame()
            height = imgproc.mid_height(img)
            heights.append((angle + cur, height))
        values = numpy.array(heights)
        best = values[numpy.argmax(values[:, 1]), 0]
        if down:
            best -= 90.0
        self.beamline.omega.move_to(best, wait=True)

    def get_video_frame(self):
        self.beamline.goniometer.wait(start=False, stop=True)
        raw = self.beamline.sample_video.get_frame()
        return cv2.cvtColor(numpy.asarray(raw), cv2.COLOR_RGB2BGR)

    def get_features(self):
        angle = self.beamline.omega.get_position()
        frame = self.get_video_frame()
        scale = 256. / frame.shape[1]
        info = imgproc.get_loop_features(frame, scale=scale, orientation=self.beamline.config['orientation'])
        return angle, info

    def run(self):
        ca.threads_init()
        self.score = 0.0
        start_time = time.time()
        with self.beamline.lock:
            GObject.idle_add(self.emit, 'started')
            try:
                self.method()
            except Exception as e:
                traceback.print_exc()
                GObject.idle_add(self.emit, 'error', str(e))
            else:
                GObject.idle_add(self.emit, 'done')
        logger.info('Centering Done in {:0.1f} seconds [Reliability={:0.0f}%]'.format(time.time() - start_time,
                                                                                      100 * self.score))

    def center_loop(self, low_trials=3, med_trials=2):
        self.beamline.sample_frontlight.set_off()
        low_zoom, med_zoom, high_zoom = self.beamline.config['zoom_levels']
        self.beamline.sample_backlight.set(self.beamline.config['centering_backlight'])

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
                        self.beamline.sample_stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
                    else:
                        failed = True
                        break
                else:
                    x, y = info['x'], info['y']
                    logger.debug('... tip found at {}, {}'.format(x, y))
                    xmm, ymm = self.screen_to_mm(x, y)
                    self.beamline.sample_stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
                    logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))

                # final 90 rotation not needed
                if trial_count < max_trials:
                    cur_pos = self.beamline.omega.get_position()
                    self.beamline.omega.move_to((90 + cur_pos) % 360, wait=True)

        # Center in loop on loop face
        if not failed:
            self.loop_face()
            angle, info = self.get_features()
            if info['score'] == 0.0:
                logger.warning('Sample not found in field-of-view')
            else:
                xmm, ymm = self.screen_to_mm(info.get('loop-x', info.get('x')), info.get('loop-y', info.get('y')))
                self.beamline.sample_stage.move_screen_by(-xmm, -ymm, 0.0, wait=True)
                logger.debug('Adjustment: {:0.4f}, {:0.4f}'.format(-xmm, -ymm))
            scores.append(info.get('score', 0.0))
        else:
            logger.error('Sample not found. Centering Failed!')
        self.score = numpy.mean(scores)

    def center_crystal(self):
        self.center_loop()

    def center_diffraction(self):
        self.center_loop(3,1)
        scores = []
        if self.score < 0.5:
            logger.error('Loop-centering failed, aborting!')
            return

        scores.append(self.score)

        for step in ['edge', 'face']:
            logger.info('Performing raster scan on {}'.format(step))
            raster_params = {}
            self.beamline.goniometer.wait(start=False)
            if step == 'face':
                self.beamline.omega.move_by(-90, wait=True)

            angle, info = self.get_features()
            if step == 'edge':
                # close polygon
                if info['points'] and (info['points'][0] != info['points'][-1]):
                    info['points'].append(info['points'][0])
                points = info['points']
            else:
                # no horizontal centering for face, use camera center
                points = [
                    (info['center-x'], info['loop-y'] - info['loop-size']),
                    (info['center-x'], info['loop-y'] + info['loop-size']),
                    (info['center-x'], info['loop-y'] - info['loop-size']),
                ]
            if not len(points):
                logger.error('Unable to find loop edges')
                return
                
            grid_info = self.microscope.calc_polygon_grid(points, grow=0.5, scaled=False)
            GObject.idle_add(self.microscope.configure_grid, grid_info)
            raster_params.update(grid_info['grid_params'])
            raster_params.update({
                "exposure": 0.5,
                "resolution": self.beamline.maxres.get_position(),
                "energy": self.beamline.energy.get_position(),
                "distance": self.beamline.distance.get_position(),
                "attenuation": self.beamline.attenuator.get(),
                "delta": RASTER_DELTA,
                "uuid": str(uuid.uuid4()),
                "name": datetime.now().strftime('%y%m%d-%H%M'),
                "activity": "raster",
            })
            # 2D grid on face
            logger.info('Finding best diffraction spot in grid')
            raster_params = datatools.update_for_sample(raster_params, self.sample_store.get_current())
            grid = grid_info['grid_xyz']
            self.collector.configure(grid, raster_params)
            self.collector.run()

            grid_scores = numpy.array([
                (index, misc.frame_score(report)) for index, report in sorted(self.collector.results.items())
            ])

            best = grid_scores[:, 1].argmax()
            index = int(grid_scores[best, 0])
            point = grid[index]

            self.beamline.sample_stage.move_xyz(point[0], point[1], point[2], wait=True)
            scores.append(grid_scores[best, 1])
        self.score = numpy.mean(scores)

    def center_capillary(self):
        low_zoom, med_zoom, high_zoom = self.beamline.config['zoom_levels']
        self.beamline.sample_frontlight.set_off()
        self.beamline.sample_backlight.set(self.beamline.config['centering_backlight'])
        self.beamline.sample_video.zoom(low_zoom, wait=True)

        scores = []
        half_width = self.beamline.sample_video.size[0] // 2
        for j in range(8):
            self.beamline.sample_stage.wait()
            self.beamline.omega.move_by(90, wait=True)
            angle, info = self.get_features()
            if 'x' in info and 'y' in info:
                x = info['x'] - half_width
                ypix = info['capillary-y'] if 'capillary-y' in info else info['y']
                xmm, ymm = self.screen_to_mm(x, ypix)
                if j > 4:
                    xmm = 0.0

                if not self.beamline.sample_stage.is_busy():
                    self.beamline.sample_stage.move_screen_by(-xmm, -ymm, 0.0)
                scores.append(1.0)
            else:
                scores.append(0.5 if 'x' in info or 'y' in info else 0.0)
            logger.debug('Centering: {}'.format(info))

        # # final shift
        # xmm, ymm = self.screen_to_mm(half_width, 0)
        # if not self.beamline.sample_stage.is_busy():
        #     self.beamline.sample_stage.move_screen_by(xmm, 0.0, 0.0)
        self.score = numpy.mean(scores)

def get_current_bkg():
    """Move Sample back and capture background image
    to be used for auto centering

    """
    try:
        beamline = globalRegistry.lookup([], IBeamline)
    except:
        logger.warning('No registered beamline found')
        return

    # set lighting and zoom
    _t = time.time()
    dev = 100

    # Save current position to return to
    start_x, start_y, start_z = beamline.sample_stage.get_xyz()
    number_left = 10

    if beamline.config['orientation'] == 2:
        offset = 0.5
    elif beamline.config['orientation'] == 3:
        offset = -0.5
    else:
        offset = 0.0

    while dev > 1.0 and number_left > 0:
        img1 = beamline.sample_video.get_frame()
        beamline.sample_stage.move_xyz_by(offset, 0.0, 0.0)
        img2 = beamline.sample_video.get_frame()
        dev = imgproc.image_deviation(img1, img2)
        number_left = number_left - 1
    bkg = beamline.sample_video.get_frame()
    beamline.sample_stage.move_xyz(start_x, start_y, start_z)
    return bkg
