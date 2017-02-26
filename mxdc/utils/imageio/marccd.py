'''
Created on Nov 25, 2010

@author: michel
'''
import math
import struct
from PIL import Image 
import numpy
from mxdc.utils.imageio.utils import calc_gamma
from mxdc.utils.log import get_module_logger
from mxdc.utils.imageio.common import *

# Configure Logging
_logger = get_module_logger('imageio.marccd')


class MarCCDImageFile(object):
    def __init__(self, filename, header_only=False):
        self.filename = filename
        self._read_header()
        if not header_only:
            self._read_image()

    def _read_header(self):
        header = {}
        
        # Read MarCCD header
        header_format = 'I16s39I80x' # 256 bytes
        statistics_format = '3Q7I9I40x128H' #128 + 256 bytes
        goniostat_format = '28i16x' #128 bytes
        detector_format = '5i9i9i9i' #128 bytes
        source_format = '10i16x10i32x' #128 bytes
        file_format = '128s128s64s32s32s32s512s96x' # 1024 bytes
        dataset_format = '512s' # 512 bytes
        #image_format = '9437184H'
        
        marccd_header_format = header_format + statistics_format 
        marccd_header_format += goniostat_format + detector_format + source_format 
        marccd_header_format += file_format + dataset_format + '512x'
        myfile = open(self.filename, 'rb')
        
        tiff_header = myfile.read(1024)
        del tiff_header
        header_pars = struct.unpack(header_format, myfile.read(256))
        statistics_pars = struct.unpack(statistics_format, myfile.read(128 + 256))
        goniostat_pars = struct.unpack(goniostat_format, myfile.read(128))
        detector_pars = struct.unpack(detector_format, myfile.read(128))
        source_pars = struct.unpack(source_format, myfile.read(128))
        #file_pars = struct.unpack(file_format, myfile.read(1024))
        #dataset_pars = struct.unpack(dataset_format, myfile.read(512))
        myfile.close()
        
        # extract some values from the header
        # use image center if detector origin is (0,0)
        if goniostat_pars[1] / 1e3 + goniostat_pars[2] / 1e3 < 0.1:
            header['beam_center'] = header_pars[17] / 2.0, header_pars[18] / 2.0
        else:
            header['beam_center'] = goniostat_pars[1] / 1e3, goniostat_pars[2] / 1e3
    
        header['distance'] = goniostat_pars[0] / 1e3
        header['wavelength'] = source_pars[3] / 1e5
        header['pixel_size'] = detector_pars[1] / 1e6
        header['delta_angle'] = goniostat_pars[24] / 1e3
        header['start_angle'] = goniostat_pars[(7 + goniostat_pars[23])] / 1e3
        header['exposure_time'] = goniostat_pars[4] / 1e3
        header['min_intensity'] = statistics_pars[3]
        header['max_intensity'] = statistics_pars[4]
        header['rms_intensity'] = statistics_pars[6] / 1e3
        header['average_intensity'] = statistics_pars[5] / 1e3
        header['overloads'] = statistics_pars[8]
        header['saturated_value'] = header_pars[23]
        header['two_theta'] = (goniostat_pars[7] / 1e3) * math.pi / -180.0
        header['detector_size'] = (header_pars[17], header_pars[18])
        header['filename'] = self.filename

        det_mm = int(round(header['pixel_size']*header['detector_size'][0]))
        header['detector_type'] = 'mar%d' % det_mm
        header['file_format'] = 'TIFF'
        self.header = header


    def _read_image(self):
        raw_img = Image.open(self.filename)
        self.raw_data = raw_img.load()

        # recalculate average intensity if not present within file
        if self.header['average_intensity'] < 0.01:
            self.header['average_intensity'] = numpy.mean(numpy.fromstring(raw_img.tobytes(), 'H'))
        self.header['gamma'] = calc_gamma(self.header['average_intensity'])    
        self.image = raw_img.convert('I')
        

__all__ = ['MarCCDImageFile']
