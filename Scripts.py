#!/usr/bin/env python

from Beamline import beamline
from LogServer import LogServer
import tempfile, numpy
import time, os

def prepare_for_mounting():
    safe_distance = 700
    safe_beamstop = 45
    beamline['motors']['detector_dist'].move_to(safe_distance, wait=True)
    beamline['motors']['bst_z'].move_to(safe_beamstop, wait=True)
    return True

def restore_beamstop():
    distance = 300
    beamstop = 1
    beamline['motors']['bst_z'].move_to(beamstop, wait=True)
    beamline['motors']['detector_dist'].move_to(distance, wait=True)
    return True

def center_sample(crystal=False):
    tst = time.time()
    LogServer.log('Starting Loop centering.')
    prefix = tempfile.mktemp()
    omega = beamline['motors']['omega']
    camera = beamline['cameras']['sample']
    zoom   = beamline['motors']['zoom']
    sample_x   = beamline['motors']['sample_x']
    sample_y1  = beamline['motors']['sample_y']
    sample_y2  = beamline['motors']['sample_z']
    cross_x = beamline['variables']['beam_x']
    cross_y = beamline['variables']['beam_y']
    #reset zoom to 1
    #zoom.move_to(1, wait=True)
    
    count = 0
    imglist = []
    tst = time.time()
    
    # determine direction based on current omega
    angle = omega.get_position()
    if angle % 360 > 180:
        direction = -1.0
    else:
        direction = 1.0

    # get images
    while count < 6:
        count += 1
        omega.move_to(angle, wait=True)
        imgname = '%s_%03d.png' % (prefix, count)
        camera.save(imgname)
        imglist.append( (angle%360, imgname) )
        LogServer.log('Saving image: %s' % imgname)
        angle = angle + (direction * 60.0)

    
    # create XREC input
    infile_name = '%s_data.inp' % prefix
    outfile_name = '%s_result.out' % prefix
    infile = open(infile_name, 'w')
    in_data = 'LOOP_POSITION  3 \n'
    in_data+= 'NUMBER_OF_IMAGES 6 \n'
    if not crystal:
        in_data+= 'PREALIGN\n'
    in_data+= 'DATA_START\n'
    for angle,img in imglist:
        in_data+= '%d  %s \n' % (angle, img)
    in_data += 'DATA_END\n'
    infile.write(in_data)
    infile.close()
    
    #execute XREC
    os.system('xrec %s %s' % (infile_name, outfile_name) )
    
    #read results and analyze it
    outfile = open(outfile_name)
    data = outfile.readlines()
    outfile.close()
    results = {}
    
    for line in data:
        vals = line.split()
        results[vals[0]] = int(vals[1])
    if results['RELIABILITY'] >= 70:
        LogServer.log('Loop centering reliability is %d%%.')

    else:
        LogServer.log('Loop centering was not reliable enough.')
        
    # calculate motor positions and move
    x = results['Y_CENTRE']
    y = results['X_CENTRE'] - results['RADIUS']
    tmp_omega = results['TARGET_ANGLE']
    sin_w = numpy.sin(tmp_omega * numpy.pi / 180)
    cos_w = numpy.cos(tmp_omega * numpy.pi / 180)
    pixel_size = 5.34e-3 * numpy.exp( -0.18 * zoom.get_position())
    x_offset = cross_x.get_position() - x
    y_offset = cross_y.get_position() - y
    xmm = x_offset * pixel_size
    ymm = y_offset * pixel_size

    sample_x.move_by( -xmm )
    sample_y1.move_by( -ymm * sin_w  )
    sample_y2.move_by( ymm * cos_w  )
        
    LogServer.log('Loop centering cleaning up ...')
    for angle,img in imglist:
        os.remove(img)
    os.remove(outfile_name)
    os.remove(infile_name)
    LogServer.log('Loop centering complete in %d seconds.' % (time.time() - tst))
    return True

