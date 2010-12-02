"""
Overview
========

    This module provides an object oriented interface to CBFlib.
"""

import sys
from ctypes import *
import numpy
import Image
import os

from bcm.libs.imageio.utils import calc_gamma
from bcm.utils.log import get_module_logger
from bcm.libs.imageio.common import *

# Configure Logging
_logger = get_module_logger('imageio.pck')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data') 


try:
    pcklib = cdll.LoadLibrary(os.path.join(DATA_DIR, 'libpck.so'))
except:
    _logger.error("PCK shared library 'libpck.so' could not be loaded!")
    raise FormatNotAvailable

pcklib.openfile.argtypes = [c_char_p, c_void_p]

class PCKImageFile(object):
    def __init__(self, filename, header_only=False):
        self.filename = filename
        self._read_header()
        if not header_only:
            self._read_image()
            
    def _read_header(self):
        self.header = {}
        #header_format = '70s' # 40 bytes
        myfile = open(self.filename,'rb')
        header = myfile.readline()
        while header[0:17] != 'CCP4 packed image':
            header = myfile.readline()
        tokens = header.strip().split(',')
        self.header['detector_size'] = (int((tokens[1].split(':'))[1]), 
                                        int((tokens[2].split(':'))[1]))
        self.header['beam_center'] = (self.header['detector_size'][0]/2, 
                                      self.header['detector_size'][1]/2)
        
        myfile.close()
        self.header['distance'] = 999.9
        self.header['wavelength'] = 0.99
        self.header['delta'] = 0.99
        self.header['pixel_size'] = 0.99
        self.header['start_angle'] = 99.99
        self.header['exposure_time'] = 0.99
        self.header['two_theta'] = 0
        self.header['saturated_value'] = 65535
        self.header['filename'] = self.filename
        self.header['detector_type'] = 'Unknown'
        self.header['file_format'] = 'PCK'


    def _read_image(self):
        num_el = self.header['detector_size'][0] * self.header['detector_size'][1]
        el_type = c_uint16
        data = create_string_buffer( sizeof(el_type) * num_el )
        pcklib.openfile(self.filename, byref(data))

        self.image = Image.fromstring('F', self.header['detector_size'], data, 'raw', 'F;16')
        self.image = self.image.convert('I')
        arr = numpy.fromstring(data, dtype=el_type)

        self.header['average_intensity'] = arr.mean()    
        self.header['min_intensity'], self.header['max_intensity'] = arr.min(), arr.max()
        self.header['gamma'] = calc_gamma(self.header['average_intensity'])
        self.header['overloads'] = len(numpy.where(arr >= self.header['saturated_value'])[0])

                   

__all__ = ['PCKImageFile']
