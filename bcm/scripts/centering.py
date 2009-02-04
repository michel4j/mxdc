import math
import os
import time
from bcm.engine.scripting import Script


class CenterSample(Script):
    def run(self, crystal=False):
        prefix = tempfile.mktemp()
        
        count = 0
        imglist = []
        tst = time.time()
        
        # determine direction based on current omega
        angle = self.beamline.goniometer.omega.get_position()
        if angle >  270:
            direction = -1.0
        else:
            direction = 1.0
    
        # get images
        while count < 6:
            count += 1
            self.beamline.goniometer.omega.move_to(angle, wait=True)
            imgname = '%s_%03d.png' % (prefix, count)
            img = self.beamline.sample_video.get_frame()
            img.save(imgname)
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
        try:
            os.system('xrec %s %s' % (infile_name, outfile_name) )       
            #read results and analyze it
            outfile = open(outfile_name)
            data = outfile.readlines()
            outfile.close()
        except:
            self.beamline.logger.error('XREC cound not be executed')
            return False
        
        results = {}
        
        for line in data:
            vals = line.split()
            results[vals[0]] = int(vals[1])
        if results['RELIABILITY'] >= 70:
            self.beamline.logger.info('Loop centering reliability is %d%%.')
    
        else:
            self.beamline.logger.info('Loop centering was not reliable enough.')
            
        # calculate motor positions and move
        x = results['Y_CENTRE']
        y = results['X_CENTRE'] - results['RADIUS']
        tmp_omega = results['TARGET_ANGLE']
        sin_w = math.sin(tmp_omega * numpy.pi / 180)
        cos_w = math.cos(tmp_omega * numpy.pi / 180)
        pixel_size = 5.34e-3 * math.exp( -0.18 * bl.sample_zoom.get_position())
        x_offset = self.beamline.devices['camera_center_x'].get() - x
        y_offset = self.beamline.devices['camera_center_y'].get() - y
        xmm = x_offset * pixel_size
        ymm = y_offset * pixel_size
    
        self.beamline.sample_stage.x.move_by( -xmm )
        self.beamline.sample_stage.y.move_by( -ymm * sin_w  )
        self.beamline.sample_stage.z.move_by( ymm * cos_w  )
            
        self.beamline.logger.info('Loop centering cleaning up ...')
        for angle,img in imglist:
            os.remove(img)
        os.remove(outfile_name)
        os.remove(infile_name)
        self.beamline.logger.info('Loop centering complete in %d seconds.' % (time.time() - tst))
        return True


script1 = CenterSample()