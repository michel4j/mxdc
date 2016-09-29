from bcm.beamline.interfaces import IBeamline
from bcm.engine import fitting
from bcm.engine.snapshot import take_sample_snapshots
from bcm.utils import imgproc
from bcm.utils.log import get_module_logger
from bcm.utils.misc import get_short_uuid, logistic_score
from twisted.python.components import globalRegistry
from PIL import Image
from PIL import ImageChops
import commands
import numpy
import os
import shutil
import tempfile
import time

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

_SAMPLE_SHIFT_STEP = 0.2  # mm
_CENTERING_ZOOM = 2
_CENTERING_BLIGHT = 65.0
_CENTERING_FLIGHT = 0
_MAX_TRIES = 5


def get_current_bkg():
    """Move Sample back and capture background image 
    to be used for auto centering
    
    """
    try:
        beamline = globalRegistry.lookup([], IBeamline)
    except:
        _logger.warning('No registered beamline found')
        return

    # set lighting and zoom
    _t = time.time()
    dev = 100

    # Save current position to return to
    start_x = beamline.sample_stage.x.get_position()
    number_left = 10

    if beamline.config['orientation'] == 2:
        offset = 0.5
    elif beamline.config['orientation'] == 3:
        offset = -0.5
    else:
        offset = 0.0

    while dev > 1.0 and number_left > 0:
        img1 = beamline.sample_video.get_frame()
        beamline.sample_stage.x.move_by(offset, wait=True)
        img2 = beamline.sample_video.get_frame()
        dev = imgproc.image_deviation(img1, img2)
        number_left = number_left - 1
    bkg = beamline.sample_video.get_frame()
    beamline.sample_stage.x.move_to(start_x, wait=True)
    return bkg


def center_loop():
    """Automatic centering of the sample pin using simple image processing."""
    beamline = globalRegistry.lookup([], IBeamline)

    # set lighting and zoom
    beamline.sample_frontlight.set_off()
    backlt = beamline.sample_backlight.get()
    frontlt = beamline.sample_frontlight.get()
    beamline.sample_video.zoom(_CENTERING_ZOOM)
    beamline.sample_backlight.set(beamline.config.get('centering_backlight', _CENTERING_BLIGHT))
    # beamline.sample_frontlight.set(_CENTERING_FLIGHT)

    cx = beamline.camera_center_x.get()
    cy = beamline.camera_center_y.get()

    bkg_img = get_current_bkg()

    # check if there is something on the screen
    img1 = beamline.sample_video.get_frame()
    dev = imgproc.image_deviation(bkg_img, img1)
    if dev < 1.0:
        # Nothing on screen, go to default start
        beamline.sample_stage.x.move_to(0.0, wait=True)
        beamline.sample_stage.y.move_to(0.0, wait=True)
        beamline.omega.move_by(90.0, wait=True)

    _logger.debug('Attempting to center loop')

    ANGLE_STEP = 90.0
    count = 0
    max_width = 0.0
    adj_mm = []
    avg_devs = []
    converged = False
    loop_w = 100
    while count < _MAX_TRIES and not converged:
        count += 1
        img = beamline.sample_video.get_frame()
        x, y, w = imgproc.get_loop_center(img, bkg_img, orientation=int(beamline.config['orientation']))

        # calculate motor positions and move
        # FIXME, keep array of valid loop widths and average as we progress
        if w > 10:
            loop_w = w * beamline.sample_video.resolution

        if count > _MAX_TRIES // 2:
            max_width = max(loop_w, max_width)

        ymm = (cy - y) * beamline.sample_video.resolution
        xmm = 0
        if count <= _MAX_TRIES // 2 or loop_w > 0.6 * max_width or loop_w < 0:
            xmm = (cx - x) * beamline.sample_video.resolution
            beamline.sample_stage.x.move_by(-xmm, wait=True)
        adj_mm.append((xmm, ymm))

        beamline.sample_stage.y.move_by(-ymm, wait=True)
        beamline.omega.move_by(ANGLE_STEP, wait=True)

        # check progress quality
        if count > 2:
            adj_a = numpy.array(adj_mm[-2:])
        else:
            adj_a = numpy.array(adj_mm)
        _dev = numpy.array([adj_a[:, 0].mean(), adj_a[:, 1].mean()])
        avg_devs.append(_dev)

        # converges if last H/V adjustments are all less than 5 image pixels
        if len(avg_devs) >= 2:
            if numpy.abs(avg_devs[-1:]).mean() <= 5 * beamline.sample_video.resolution:
                converged = True
        _logger.info("Centering ... [%d] (H): %0.3f, (V): %0.3f, Converged: %s" % (count, _dev[0], _dev[1], converged))

    # calcualte score based on average and maximum of last two adjustments a
    # an average of 20 pixels and a max of 20 pixels will give a score of 50%
    # while an average of 2 pixel and a max of 2 pixel will score 100%
    _dev = numpy.abs(avg_devs[-1:])
    scores = numpy.array([
        logistic_score(_dev.mean(), 0.05 * loop_w, 0.2 * loop_w),
        logistic_score(_dev.max(), 0.05 * loop_w, 0.2 * loop_w),
    ])
    quality = 100 * scores.mean()

    beamline.sample_frontlight.set_on()
    beamline.sample_backlight.set(backlt)
    beamline.sample_frontlight.set(frontlt)

    return quality


def center_capillary():
    """Automatic centering of capillary sample using simple image processing."""
    beamline = globalRegistry.lookup([], IBeamline)

    # set lighting and zoom
    beamline.sample_frontlight.set_off()
    backlt = beamline.sample_backlight.get()
    frontlt = beamline.sample_frontlight.get()
    beamline.sample_video.zoom(_CENTERING_ZOOM)
    beamline.sample_backlight.set(beamline.config.get('centering_backlight', _CENTERING_BLIGHT))
    # beamline.sample_frontlight.set(_CENTERING_FLIGHT)

    cx = beamline.camera_center_x.get()
    cy = beamline.camera_center_y.get()

    bkg_img = get_current_bkg()  # sample will move off screen, take bkgd, then return sample.

    # check if there is something on the screen
    img1 = beamline.sample_video.get_frame()
    dev = imgproc.image_deviation(bkg_img, img1)
    if dev < 1.0:
        # Nothing on screen, go to default start
        beamline.sample_stage.x.move_to(0.0, wait=True)
        beamline.sample_stage.y.move_to(0.0, wait=True)
        beamline.omega.move_by(90, wait=True)

    _logger.debug('Attempting to center capillary')

    ANGLE_STEP = 90.0
    count = 0
    max_width = 0.0
    x_offset = 2  # milimeters
    adj_mm = []
    avg_devs = []
    converged = False
    cap_w = 100
    while count < _MAX_TRIES and not converged:
        count += 1
        img = beamline.sample_video.get_frame()  # new frame on each try
        x, y, w = imgproc.get_cap_center(img, bkg_img, orientation=int(beamline.config['orientation']))

        if w > 10:
            cap_w = w * beamline.sample_video.resolution

        if count > _MAX_TRIES // 2:
            max_width = max(cap_w, max_width)  # max width becomes cap width

        ymm = (cy - y) * beamline.sample_video.resolution
        xmm = 0
        if count <= _MAX_TRIES // 2 or cap_w > 0.6 * max_width or cap_w < 0:
            xmm = (cx - x) * beamline.sample_video.resolution  # center the tip
            beamline.sample_stage.move_by(-xmm, wait=True)
        adj_mm.append(((xmm - x_offset), ymm))  # move tip past edge of frame.

        beamline.sample_stage.y.move_by(-ymm, wait=True)
        beamline.omega.move_by(ANGLE_STEP, wait=True)

        # check progress quality
        if count > 2:
            adj_a = numpy.array(adj_mm[-2:])
        else:
            adj_a = numpy.array(adj_mm)
        _dev = numpy.array([adj_a[:, 0].mean(), adj_a[:, 1].mean()])
        avg_devs.append(_dev)

        # converges id last H/V adjustments are all less than 5 image pixels
        if len(avg_devs) >= 2:
            if numpy.abs(avg_devs[-1:]).mean() <= 5 * beamline.sample_video.resolution:
                converged = True
        _logger.info("Centering ... [%d] (H): %0.3f, (V): %0.3f, Converged: %s" % (
            count,
            _dev[0],
            _dev[1],
            converged
        ))
        # calculate score based on average and maximum of last two adjustments
    # an average of 20 pixels and a max of 20 pixels will give a score of 50%
    # while an average of 2 pixels and a max of 2 pixels will xcore 100%
    _dev = numpy.abs(avg_devs[-1:])
    scores = numpy.array([
        logistic_score(_dev.mean(), 0.05 * cap_w, 0.2 * cap_w),
        logistic_score(_dev.max(), 0.05 * cap_w, 0.2 * cap_w),
    ])
    quality = 100 * scores.mean()

    beamline.sample_frontlight.set_on()
    beamline.sample_backlight.set(backlt)
    beamline.sample_frontlight.set(frontlt)

    return quality


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
        _logger.warning('No registered beamline found')
        return {'RELIABILITY': -99}

    # set lighting and zoom
    beamline.sample_frontlight.set_off()
    backlt = beamline.sample_backlight.get()
    frontlt = beamline.sample_frontlight.get()
    beamline.sample_video.zoom(_CENTERING_ZOOM)
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

    # create XREC input
    infile_name = os.path.join(directory, '%s.inp' % prefix)
    outfile_name = os.path.join(directory, '%s.out' % prefix)
    infile = open(infile_name, 'w')
    in_data = 'LOOP_POSITION  %s\n' % beamline.config['orientation']
    in_data += 'NUMBER_OF_IMAGES 8 \n'
    in_data += 'CENTER_COORD %d\n' % (beamline.camera_center_y.get())
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
        _logger.error('XREC cound not be executed')
        return {'RELIABILITY': -99}

    results = {'RELIABILITY': -99}

    for line in data:
        vals = line.split()
        results[vals[0]] = int(vals[1])

    # verify integrity of results  
    for key in ['TARGET_ANGLE', 'Y_CENTRE', 'X_CENTRE', 'RADIUS']:
        if key not in results:
            _logger.info('Centering failed.')
            return results

    # calculate motor positions and move
    cx = beamline.camera_center_x.get()
    cy = beamline.camera_center_y.get()
    beamline.omega.move_to(results['TARGET_ANGLE'] % 360.0, wait=True)
    if results['Y_CENTRE'] != -1:
        x = results['Y_CENTRE']
        xmm = (cx - x) * beamline.sample_video.resolution
        beamline.sample_stage.x.move_by(-xmm, wait=True)
    if results['X_CENTRE'] != -1:
        y = results['X_CENTRE'] - results['RADIUS']
        ymm = (cy - y) * beamline.sample_video.resolution
        if int(beamline.config['orientation']) == 2:
            beamline.sample_stage.y.move_by(ymm)
        else:
            beamline.sample_stage.y.move_by(-ymm)

    beamline.sample_frontlight.set_on()
    beamline.sample_backlight.set(backlt)
    beamline.sample_frontlight.set(frontlt)

    # cleanup
    shutil.rmtree(directory)

    _logger.info('Centering reliability is %d%%.' % results['RELIABILITY'])
    return results


def auto_center_loop():
    """Convenience function to run automated loop centering and return the result, 
    displaying appropriate log messages on failure.    
    """

    tst = time.time()
    quality = center_loop()

    if quality < 75:
        _logger.warning('Loop centering not reliable enough.')

    _logger.info('Loop centering complete in %d seconds. [%0.0f %% reliable]' % (time.time() - tst, quality))
    return quality


def auto_center_capillary():
    """Convenience function to run automated capillary centering and return the result,
    displaying appropriate log messages on failure.
    """

    tst = time.time()
    quality = center_capillary()

    if quality < 75:
        _logger.warning('Capillary centering not reliable enough.')

    _logger.info('Capillary centering complete in %d seconds. [%0.0f %% reliable]' % (time.time() - tst, quality))
    return quality


def auto_center_crystal():
    """Convenience function to run automated crystal centering and return the result, 
    displaying appropriate log messages on failure.    
    """
    tst = time.time()
    result = center_crystal()
    if result['RELIABILITY'] < 75:
        _logger.info('Crystal centering was not reliable enough.')
    _logger.info('Crystal centering complete in %d seconds.' % (time.time() - tst))
    return result['RELIABILITY']
