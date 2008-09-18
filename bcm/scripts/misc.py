import tempfile, numpy
import time, os

def prepare_for_mounting(bl):
    safe_distance = 700
    safe_beamstop = 45
    bl.det_z.move_to(safe_distance, wait=True)
    bl.bst_z.move_to(safe_beamstop, wait=True)
    return True

def restore_beamstop(bl):
    distance = 300
    beamstop = 30
    bl.bst_z.move_to(beamstop, wait=True)
    bl.det_z.move_to(distance, wait=True)
    return True

def center_sample(bl, crystal=False):
    tst = time.time()
    prefix = tempfile.mktemp()
    
    count = 0
    imglist = []
    tst = time.time()
    
    # determine direction based on current omega
    angle = bl.omega.get_position()
    if angle >  270:
        direction = -1.0
    else:
        direction = 1.0

    # get images
    while count < 6:
        count += 1
        bl.omega.move_to(angle, wait=True)
        imgname = '%s_%03d.png' % (prefix, count)
        bl.sample_cam.save(imgname)
        imglist.append( (angle%360, imgname) )
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
        bl.log('Loop centering reliability is %d%%.')

    else:
        bl.log('Loop centering was not reliable enough.')
        
    # calculate motor positions and move
    x = results['Y_CENTRE']
    y = results['X_CENTRE'] - results['RADIUS']
    tmp_omega = results['TARGET_ANGLE']
    sin_w = numpy.sin(tmp_omega * numpy.pi / 180)
    cos_w = numpy.cos(tmp_omega * numpy.pi / 180)
    pixel_size = 5.34e-3 * numpy.exp( -0.18 * bl.sample_zoom.get_position())
    x_offset = bl.cross_x.get_position() - x
    y_offset = bl.cross_y.get_position() - y
    xmm = x_offset * pixel_size
    ymm = y_offset * pixel_size

    bl.sample_x.move_by( -xmm )
    bl.sample_y.move_by( -ymm * sin_w  )
    bl.sample_z.move_by( ymm * cos_w  )
        
    bl.log('Loop centering cleaning up ...')
    for angle,img in imglist:
        os.remove(img)
    os.remove(outfile_name)
    os.remove(infile_name)
    bl.log('Loop centering complete in %d seconds.' % (time.time() - tst))
    return True

