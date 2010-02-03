'''
Created on Jan 26, 2010

@author: michel
'''

import sys
import os
import time
import tempfile
from bcm.engine.snapshot import take_sample_snapshots
from twisted.python.components import globalRegistry
from bcm.protocol import ca
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger
from bcm.utils.misc import get_short_uuid
import commands
import shutil

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

if sys.version_info[:2] >= (2,5):
    import uuid
else:
    from bcm.utils import uuid # for 2.3, 2.4


def auto_center(pre_align=True):
    try:
        beamline = globalRegistry.lookup([], IBeamline)
    except:
        _logger.warning('No registered beamline found')
        return None
           
    tst = time.time()
    
    # determine direction based on current omega
    angle = beamline.goniometer.omega.get_position()
    if angle >  270:
        direction = -1.0
    else:
        direction = 1.0

    # get images
    prefix = get_short_uuid()
    directory = tempfile.mkdtemp(prefix='centering')
    angles = [angle]
    count = 1
    while count < 6:
        count += 1
        angle = angle + (direction * 60.0)
        angles.append(angle)
    imglist = take_sample_snapshots(prefix, directory, angles, decorate=False)
    
    # create XREC input
    infile_name = os.path.join(directory, '%s.inp' % prefix)
    outfile_name = os.path.join(directory, '%s.out' % prefix)
    infile = open(infile_name, 'w')
    in_data = 'LOOP_POSITION  %s\n' % beamline.config['orientation']
    in_data+= 'NUMBER_OF_IMAGES 6 \n'
    in_data+= 'CENTER_COORD %d\n' % (beamline.camera_center_y.get())
    in_data+= 'BORDER 4\n'
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
        sts, output = commands.getstatusoutput('xrec %s %s' % (infile_name, outfile_name))
        if sts != 0:
            return None
        #read results and analyze it
        outfile = open(outfile_name)
        data = outfile.readlines()
        outfile.close()
    except:
        _logger.error('XREC cound not be executed')
        return None
    
    results = {}
    
    for line in data:
        vals = line.split()
        results[vals[0]] = int(vals[1])
        
    # calculate motor positions and move
    cx = beamline.camera_center_x.get()
    cy = beamline.camera_center_y.get()
    beamline.goniometer.omega.move_to(results['TARGET_ANGLE'], wait=True)
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
            
    # cleanup
    #shutil.rmtree(directory)
    
    _logger.info('Centering reliability is %d%%.' % results['RELIABILITY'])   
    return results

def auto_center_loop():
    tst = time.time()
    result = auto_center(pre_align=True)
    if result['RELIABILITY'] < 70:
        if (result['X_CENTRE'] == -1) and  (result['Y_CENTRE'] == -1):
            _logger.error('Loop centering failed. No loop detected.')
        else:
            _logger.info('Loop centering was not reliable enough.')
            #result = auto_center(pre_align=True)
    _logger.debug('Loop centering complete in %d seconds.' % (time.time() - tst))
    return result

def auto_center_crystal():
    tst = time.time()
    result = auto_center(pre_align=True)
    if result['RELIABILITY'] < 70:
        if (result['X_CENTRE'] == -1) and  (result['Y_CENTRE'] == -1):
            _logger.error('Initial Loop centering failed. No loop detected.')
        else:
            _logger.info('Loop centering was not reliable enough. Repeating ')
            result = auto_center(pre_align=True)
    result = auto_center(pre_align=False)
    _logger.debug('Crystal centering complete in %d seconds.' % (time.time() - tst))
    return result

        