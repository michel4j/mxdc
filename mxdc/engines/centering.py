from __future__ import print_function

import os
import shutil
import tempfile
import time
import threading
import numpy
import uuid
import traceback
from datetime import datetime


from twisted.python.components import globalRegistry
from gi.repository import GObject
from mxdc.beamlines.interfaces import IBeamline
from mxdc.engines.snapshot import take_sample_snapshots
from mxdc.utils import imgproc, datatools, misc
from mxdc.com import ca
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import get_short_uuid


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
        'error': (GObject.SIGNAL_RUN_LAST, None, (str,))
    }
    complete = GObject.Property(type=bool, default=False)

    def __init__(self):
        super(Centering, self).__init__()
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

    def get_features(self):
        angle = self.beamline.omega.get_position()
        img = self.beamline.sample_video.get_frame()
        info = imgproc.get_loop_info(img, orientation=self.beamline.config['orientation'])
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
        logger.info('Centering Done in {:0.1f} seconds'.format(time.time() - start_time))

    def center_loop(self):
        self.beamline.sample_frontlight.set_off()
        low_zoom, med_zoom, high_zoom = self.beamline.config['zoom_levels']
        self.beamline.sample_backlight.set(100)
        self.beamline.sample_video.zoom(low_zoom)
        time.sleep(1)
        angle, info = self.get_features()
        if not 'x' in info or not 'y' in info:
            logger.warning('No sample found, homing centering stage!')
            self.beamline.sample_stage.move_xyz(0.0, 0.0, 0.0)
        widths = []
        scores = []
        for j in range(2):
            if j == 1:
                self.beamline.sample_video.zoom(med_zoom)
                time.sleep(1)
            for i in range(3):
                self.beamline.sample_stage.wait()
                self.beamline.omega.move_by(90, wait=True)
                angle, info = self.get_features()

                if 'x' in info and 'y' in info:
                    xmm, ymm = self.screen_to_mm(info['x'], info['y'])
                    if not self.beamline.sample_stage.is_busy():
                        self.beamline.sample_stage.move_screen_by(-xmm, -ymm, 0.0)
                    widths.append((angle, info['width'], info['height']))
                    scores.append(1.0)
                else:
                    scores.append(0.5 if 'x' in info or 'y' in info else 0.0)
                logger.debug('Centering: {}'.format(info))
        sizes = numpy.array(widths)
        best_angle =  sizes[:,2][sizes[:,2].argmax()]
        self.beamline.omega.move_to(best_angle, wait=True)

        angle, info = self.get_features()
        loop_x = info.get('loop-x', info.get('x'))
        loop_y = info.get('loop-y', info.get('y'))
        if loop_x and loop_y:
            xmm, ymm = self.screen_to_mm(loop_x, loop_y)
            if not self.beamline.sample_stage.is_busy():
                self.beamline.sample_stage.move_screen_by(-xmm, -ymm, 0.0)

        self.score = numpy.mean(scores)

    def center_crystal(self):
        self.center_loop()
        loop_score = self.score

    def center_diffraction(self):

        from mxdc.controllers.microscope import IMicroscope
        from mxdc.controllers.samplestore import ISampleStore
        from mxdc.engines.rastering import IRasterCollector

        current =  str(uuid.uuid4())

        microscope = globalRegistry.lookup([], IMicroscope)
        sample_store = globalRegistry.lookup([], ISampleStore)
        collector = globalRegistry.lookup([], IRasterCollector)

        #self.center_loop()
        #loop_score = self.score

        angle, info = self.get_features()
        if 'loop-x' in info and 'loop-y' in info:
            half_height = info['height']/(2*numpy.sqrt(2))
            xmm_s, ymm_s = self.screen_to_mm(info['loop-x'], info['loop-y'] - half_height)
            xmm_e, ymm_e = self.screen_to_mm(info['loop-x'], info['loop-y'] + half_height)

            step_size = (self.beamline.aperture.get()*1e-3)*2**-0.5
            nY = (ymm_s - ymm_e)/step_size
            xmm = numpy.linspace(xmm_s, xmm_e, nY)
            ymm = numpy.linspace(ymm_s, ymm_e, nY)

            origin = self.beamline.sample_stage.get_xyz()
            ox, oy, oz = origin
            angle = self.beamline.omega.get_position()
            gx, gy, gz = self.beamline.sample_stage.xvw_to_xyz(-xmm, -ymm, numpy.radians(angle))
            grid_xyz = numpy.dstack([gx + ox, gy + oy, gz + oz])[0]

            if nY <=1:
                logger.warning('No sample found, diffraction centering not done!')
                return

            params = {
                "origin": origin,
                "angle": angle,
                "scale": 1,
                "exposure": 1.0,
                "resolution": self.beamline.maxres.get_position(),
                "energy": self.beamline.energy.get_position(),
                "distance": self.beamline.distance.get_position(),
                "attenuation": self.beamline.attenuator.get(),
                "delta": RASTER_DELTA,
                "uuid":  current,
                "name": datetime.now().strftime('%y%m%d-%H%M'),
                "activity": "centering",
            }
            params = datatools.update_for_sample(params, sample_store.get_current())
            microscope.props.grid_params = params
            microscope.props.grid_xyz = grid_xyz

            collector.configure(grid_xyz, params)

            GObject.idle_add(collector.emit, 'started')
            collector.acquire()
            GObject.idle_add(collector.emit, 'done')

            self.beamline.fast_shutter.close()
            self.beamline.detector_cover.close()

            scores = numpy.array([
                (index, misc.frame_score(info)) for index, info in sorted(collector.results.items())
            ])

            best = scores[:,1].argmax()
            index = int(scores[best,0])
            point = grid_xyz[index]

            self.beamline.sample_stage.move_xyz(point[0], point[1], point[2])
            self.score = scores[best, 1]
        else:
            logger.warning('No sample found, diffraction centering not done!')


    def center_capillary(self):
        low_zoom, med_zoom, high_zoom = self.beamline.config['zoom_levels']
        self.beamline.sample_frontlight.set_off()
        self.beamline.sample_backlight.set(100)
        self.beamline.sample_video.zoom(low_zoom)
        time.sleep(1)
        scores = []
        angle, info = self.get_features()
        if not 'x' in info or not 'y' in info:
            logger.warning('No sample found, homing centering stage!')
            self.beamline.sample_stage.move_xyz(0.0, 0.0, 0.0)

        half_width = self.beamline.sample_video.size[0] // 2
        for j in range(2):
            if j == 1:
                self.beamline.sample_video.zoom(med_zoom)
                time.sleep(1)
            for i in range(3):
                self.beamline.sample_stage.wait()
                self.beamline.omega.move_by(90, wait=True)
                angle, info = self.get_features()
                if 'x' in info and 'y' in info:
                    x = info['x'] - half_width
                    xmm, ymm = self.screen_to_mm(x, info['y'])
                    if not self.beamline.sample_stage.is_busy():
                        self.beamline.sample_stage.move_screen_by(-xmm, -ymm, 0.0)
                    scores.append(1.0)
                else:
                    scores.append(0.5 if 'x' in info or 'y' in info else 0.0)
                logger.debug('Centering: {}'.format(info))

        # final shift
        xmm, ymm = self.screen_to_mm(half_width, 0)
        if not self.beamline.sample_stage.is_busy():
            self.beamline.sample_stage.move_screen_by(xmm, 0.0, 0.0)


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



def center_crystal():
    """More precise auto-centering of the crystal using the XREC package.

    Kwargs:
        - `pre_align` (bool): Activates fast loop alignment. Default True.

    Returns:
        A dictionary. With fields TARGET_ANGLE, RADIUS, Y_CENTRE, X_CENTRE,
        PRECENTRING, RELIABILITY, corresponding to the XREC output. All fields are
        integers. If XREC fails,  only the RELIABILITY field will be present,
        with a value of -99. (See the XREC 3.0 Manual).
    """
    try:
        beamline = globalRegistry.lookup([], IBeamline)
    except:
        logger.warning('No registered beamline found')
        return {'RELIABILITY': -99}

    # set lighting and zoom
    beamline.sample_frontlight.set_off()
    backlt = beamline.sample_backlight.get()
    frontlt = beamline.sample_frontlight.get()
    beamline.sample_video.zoom(CENTERING_ZOOM)
    beamline.sample_backlight.set(beamline.config.get('centering_backlight', _CENTERING_BLIGHT))
    # beamline.sample_frontlight.set(_CENTERING_FLIGHT)

    # get images
    # determine direction based on current omega
    bkg_img = get_current_bkg()
    angle = beamline.omega.get_position()
    if angle > 270:
        direction = -1.0
    else:
        direction = 1.0

    prefix = get_short_uuid()
    directory = tempfile.mkdtemp(prefix='centering')
    angles = [angle]
    STEPS = _MAX_TRIES
    ANGLE_STEP = 360.0 / STEPS
    count = 1
    while count < STEPS:
        count += 1
        angle = (angle + (direction * ANGLE_STEP)) % 360
        angles.append(angle)
    imglist = take_sample_snapshots(prefix, directory, angles, decorate=False)

    # determine zoom level to select appropriate background image
    back_filename = os.path.join(directory, "%s-bg.png" % prefix)
    bkg_img.save(back_filename)

    cx, cy = map(lambda x: x//2, beamline.sample_video.size)

    # create XREC input
    infile_name = os.path.join(directory, '%s.inp' % prefix)
    outfile_name = os.path.join(directory, '%s.out' % prefix)
    infile = open(infile_name, 'w')
    in_data = 'LOOP_POSITION  %s\n' % beamline.config['orientation']
    in_data += 'NUMBER_OF_IMAGES 8 \n'
    in_data += 'CENTER_COORD %d\n' % (cy)
    in_data += 'BORDER 4\n'
    if os.path.exists(back_filename):
        in_data += 'BACK %s\n' % (back_filename)
        # in_data+= 'PREALIGN\n'
    in_data += 'DATA_START\n'
    for angle, img in imglist:
        in_data += '%d  %s \n' % (angle, img)
    in_data += 'DATA_END\n'
    infile.write(in_data)
    infile.close()

    # execute XREC
    try:
        sts, _ = commands.getstatusoutput('xrec %s %s' % (infile_name, outfile_name))
        if sts != 0:
            return {'RELIABILITY': -99}
        # read results and analyze it
        outfile = open(outfile_name)
        data = outfile.readlines()
        outfile.close()
    except:
        logger.error('XREC cound not be executed')
        return {'RELIABILITY': -99}

    results = {'RELIABILITY': -99}

    for line in data:
        vals = line.split()
        results[vals[0]] = int(vals[1])

    # verify integrity of results
    for key in ['TARGET_ANGLE', 'Y_CENTRE', 'X_CENTRE', 'RADIUS']:
        if key not in results:
            logger.info('Centering failed.')
            return results

    # calculate motor positions and move
    cx, cy = map(lambda x:x*0.5, beamline.sample_video.size)
    beamline.omega.move_to(results['TARGET_ANGLE'] % 360.0, wait=True)
    xmm = ymm = 0.0
    if results['Y_CENTRE'] != -1:
        x = results['Y_CENTRE']
        xmm = (cx - x) * beamline.sample_video.resolution
    if results['X_CENTRE'] != -1:
        y = results['X_CENTRE'] - results['RADIUS']
        ymm = (cy - y) * beamline.sample_video.resolution
        if int(beamline.config['orientation']) != 2:
            ymm = -ymm
    beamline.sample_stage.move_screen_by(-xmm, -ymm, 0.0)

    beamline.sample_frontlight.set_on()
    beamline.sample_backlight.set(backlt)
    beamline.sample_frontlight.set(frontlt)

    # cleanup
    shutil.rmtree(directory)

    logger.info('Centering reliability is %d%%.' % results['RELIABILITY'])
    return results
