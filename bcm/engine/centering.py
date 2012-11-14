import os
import time
import tempfile
from bcm.engine.snapshot import take_sample_snapshots
from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger
from bcm.utils.misc import get_short_uuid
from bcm.engine import fitting
from bcm.utils import imgproc
import Image, ImageChops
import commands
import shutil
import numpy

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

_SAMPLE_SHIFT_STEP = 0.2 # mm
_CENTERING_ZOOM = 2
_CENTERING_BLIGHT = 65.0
_CENTERING_FLIGHT = 0
_MAX_TRIES = 8


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
    start_x = beamline.sample_x.get_position()
    
    while dev > 1.0:
        img1 = beamline.sample_video.get_frame()
        beamline.sample_x.move_by(0.5, wait=True)
        img2 = beamline.sample_video.get_frame()
        dev = imgproc.image_deviation(img1, img2)
    bkg = beamline.sample_video.get_frame()
    beamline.sample_x.move_to(start_x, wait=True)
    return bkg

def center_loop():
    """Automatic centering of the sample pin using simple image processing."""
    beamline = globalRegistry.lookup([], IBeamline)
    
    # set lighting and zoom
    beamline.sample_frontlight.set_off()
    backlt = beamline.sample_backlight.get()
    frontlt = beamline.sample_frontlight.get()
    beamline.sample_zoom.set(_CENTERING_ZOOM)
    beamline.sample_backlight.set(_CENTERING_BLIGHT)
    beamline.sample_frontlight.set(_CENTERING_FLIGHT)
       
    cx = beamline.camera_center_x.get()
    cy = beamline.camera_center_y.get()
    
    bkg_img = get_current_bkg()
    
    # check if there is something on the screen
    img1 = beamline.sample_video.get_frame()
    dev = imgproc.image_deviation(bkg_img, img1)
    if dev < 1.0:
        # Nothing on screen, go to default start
        beamline.sample_x.move_to(0.0, wait=True)
        beamline.sample_y.move_to(0.0, wait=True)
        beamline.omega.move_by(90.0, wait=True)
        beamline.sample_y.move_to(0.0, wait=True)

    _logger.debug('Attempting to center loop')
    
    ANGLE_STEP = 90.0
    count = 0
    max_width = 0.0
    adj_devs = []

    while count < _MAX_TRIES:
        count += 1
        img = beamline.sample_video.get_frame()
        x, y, w = imgproc.get_loop_center(img, bkg_img, orientation=int(beamline.config['orientation']))
        
        # calculate motor positions and move
        loop_w = w * beamline.sample_video.resolution
        if count > _MAX_TRIES//2:
            max_width = max(loop_w, max_width)

        ymm = (cy - y) * beamline.sample_video.resolution
        if count <= _MAX_TRIES//2 or loop_w > 0.6 * max_width or loop_w < 0:
            xmm = (cx - x) * beamline.sample_video.resolution
            beamline.sample_stage.x.move_by(-xmm, wait=True)
            _logger.info("Loop: %0.3f, Change: %0.3f, %0.3f" % (loop_w, xmm, ymm))
            adj_devs.append((xmm, ymm))
        else:
            _logger.warning("Loop: %0.3f, Change: %0.3f, %0.3f" % (loop_w, 0.0, ymm))
            adj_devs.append((0.0, ymm))

        beamline.sample_stage.y.move_by(-ymm, wait=True)
        beamline.omega.move_by(ANGLE_STEP, wait=True)
    
    # check quality of fit
    adj_a = numpy.array(adj_devs)
    adj_x = numpy.arange(adj_a.shape[0])
    fit = fitting.PeakFitter()
    fit(adj_x, adj_a[:,0], 'decay')
    _logger.warning("Centering quality (Horiz): %0.3f,  %0.3f, %d" % (fit.residual, fit.coeffs[2], fit.ier))
    fit(adj_x, adj_a[:,1], 'decay')
    _logger.warning("Centering quality (Vert): %0.3f,  %0.3f, %d" % (fit.residual, fit.coeffs[2], fit.ier))
    
    # print adj_a[:,0], adj_a[:,0]
    # Return lights to previous settings
    beamline.sample_frontlight.set_on()
    beamline.sample_backlight.set(backlt)
    beamline.sample_frontlight.set(frontlt)            

    #FIXME: Better return value
    return 99.9    
    

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
    beamline.sample_zoom.set(_CENTERING_ZOOM)
    beamline.sample_backlight.set(_CENTERING_BLIGHT)
    beamline.sample_frontlight.set(_CENTERING_FLIGHT)

    # get images
    # determine direction based on current omega
    bkg_img = get_current_bkg()
    angle = beamline.omega.get_position()
    if angle >  270:
        direction = -1.0
    else:
        direction = 1.0

    prefix = get_short_uuid()
    directory = tempfile.mkdtemp(prefix='centering')
    angles = [angle]
    STEPS=_MAX_TRIES
    ANGLE_STEP = 360.0/STEPS
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
    in_data+= 'NUMBER_OF_IMAGES 8 \n'
    in_data+= 'CENTER_COORD %d\n' % (beamline.camera_center_y.get())
    in_data+= 'BORDER 4\n'
    if os.path.exists(back_filename):
        in_data+= 'BACK %s\n' % (back_filename) 
    #in_data+= 'PREALIGN\n'
    in_data+= 'DATA_START\n'
    for angle,img in imglist:
        in_data+= '%d  %s \n' % (angle, img)
    in_data += 'DATA_END\n'
    infile.write(in_data)
    infile.close()
    
    #execute XREC
    try:
        sts, _ = commands.getstatusoutput('xrec %s %s' % (infile_name, outfile_name))
        if sts != 0:
            return {'RELIABILITY': -99}
        #read results and analyze it
        outfile = open(outfile_name)
        data = outfile.readlines()
        outfile.close()
    except:
        _logger.error('XREC cound not be executed')
        return  {'RELIABILITY': -99}
    
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

    if quality < 70:
        _logger.error('Loop centering failed. No loop detected.')

    _logger.info('Loop centering complete in %d seconds.' % (time.time() - tst))
    return quality

def auto_center_crystal():
    """Convenience function to run automated crystal centering and return the result, 
    displaying appropriate log messages on failure.    
    """
    tst = time.time()
    result = center_crystal()
    if result['RELIABILITY'] < 70:
        _logger.info('Loop centering was not reliable enough.')
    _logger.info('Crystal centering complete in %d seconds.' % (time.time() - tst))
    return result['RELIABILITY']

        
