import os
import time
import tempfile
from bcm.engine.snapshot import take_sample_snapshots
from twisted.python.components import globalRegistry
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger
from bcm.utils.misc import get_short_uuid
from bcm.utils.imgproc import get_pin_tip
import Image
import commands
import shutil

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


def pre_center():
    """Rough automatic centering of the sample pin using simple image processing."""
    try:
        beamline = globalRegistry.lookup([], IBeamline)
    except:
        _logger.warning('No registered beamline found')
        return {'RELIABILITY': -99}
    
    beamline.sample_frontlight.set(100)
    zoom = beamline.sample_zoom.get()
    blight = beamline.sample_backlight.get()
    back_filename = '%s/data/%s/bg-%d_%d.png' % (os.environ.get('BCM_CONFIG_PATH'), beamline.name, int(zoom), int(blight))
    if os.path.exists(back_filename):
        bkg = Image.open(back_filename)
    else:
        bkg = None

    cx = beamline.camera_center_x.get()
    cy = beamline.camera_center_y.get()
    for _ in range(3):
        img = beamline.sample_video.get_frame()
        x, y = get_pin_tip(img, bkg, orientation=int(beamline.config['orientation']))
   
        # calculate motor positions and move

        xmm = (cx - x) * beamline.sample_video.resolution
        beamline.sample_stage.x.move_by(-xmm, wait=True)

        ymm = (cy - y) * beamline.sample_video.resolution
        beamline.sample_stage.y.move_by(-ymm, wait=True)
        beamline.omega.move_by(60.0, wait=True)
    

def auto_center(pre_align=True):
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
               
    # determine direction based on current omega
    angle = beamline.omega.get_position()
    if angle >  270:
        direction = -1.0
    else:
        direction = 1.0

    # set lighting and zoom
    ZOOM = 2
    BLIGHT = 65
    FLIGHT = 0
    backlt = beamline.sample_backlight.get()
    frontlt = beamline.sample_frontlight.get()
    beamline.sample_zoom.set(ZOOM)
    beamline.sample_backlight.set(BLIGHT)

    pre_center();
    beamline.sample_frontlight.set(FLIGHT)

    # get images
    prefix = get_short_uuid()
    directory = tempfile.mkdtemp(prefix='centering')
    angles = [angle]
    count = 1
    while count < 8:
        count += 1
        angle = (angle + (direction * 40.0)) % 360
        angles.append(angle)
    imglist = take_sample_snapshots(prefix, directory, angles, decorate=False)

    # determine zoom level to select appropriate background image
    zoom = beamline.sample_zoom.get()
    back_filename = '%s/data/%s/bg-%d_%d.png' % (os.environ.get('BCM_CONFIG_PATH'), beamline.name, int(zoom), BLIGHT)

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
    if pre_align:
        in_data+= 'PREALIGN\n'
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
    result = auto_center(pre_align=True)
    if result['RELIABILITY'] < 70:
        if (result.get('X_CENTRE', -1) == -1) and  (result.get('Y_CENTRE', -1) == -1):
            _logger.error('Loop centering failed. No loop detected.')
        else:
            _logger.info('Loop centering was not reliable enough.')
            #result = auto_center(pre_align=True)
    _logger.debug('Loop centering complete in %d seconds.' % (time.time() - tst))
    return result

def auto_center_crystal():
    """Convenience function to run automated crystal centering and return the result, 
    displaying appropriate log messages on failure.    
    """
    tst = time.time()
    result = auto_center(pre_align=True)
    if result['RELIABILITY'] < 70:
        if (result.get('X_CENTRE', -1) == -1) and  (result.get('Y_CENTRE', -1) == -1):
            _logger.error('Initial Loop centering failed. No loop detected.')
        else:
            _logger.info('Loop centering was not reliable enough. Repeating ')
            result = auto_center(pre_align=True)
    result = auto_center(pre_align=False)
    _logger.debug('Crystal centering complete in %d seconds.' % (time.time() - tst))
    return result

        
