'''
Created on Nov 25, 2010

@author: michel
'''
import numpy
import re
import ctypes
import Image
from bcm.utils.imageio.utils import calc_gamma
from bcm.utils.log import get_module_logger
from bcm.utils.imageio.common import *

# Configure Logging
_logger = get_module_logger('imageio.smv')


DECODER_DICT = {
    "unsigned_short": (ctypes.c_uint16, 'F;16','F;16B'),
    "unsigned_int": (ctypes.c_uint, 'F;32','F;32B'),
    "signed_short": (ctypes.c_int16, 'F;16S','F;16BS'),
    "signed_int": (ctypes.c_int, 'F;32S','F;32BS'),
}


class SMVImageFile(object):
    def __init__(self, filename, header_only=False):
        self.filename = filename
        self._read_header()
        if not header_only:
            self._read_image()

    def _read_header(self):
        """
        Read SMV image headers
        returns a dictionary of header parameters
        
        """
        info = {}
        
        myfile = open(self.filename,'r')
        raw = myfile.read(512)
        raw_entries = raw.split('\n')
        tmp_info = {}
        epat = re.compile('^(?P<key>[\w]+)=(?P<value>.+);')
        for line in raw_entries:
            m = epat.match(line)
            if m:
                tmp_info[m.group('key').lower()] = m.group('value').strip()
        # Read remaining header if any
        self._header_size = int(tmp_info['header_bytes'])
        if self._header_size > 512:
            raw = myfile.read(self._header_size-512)
            raw_entries = raw.split('\n')
            for line in raw_entries:
                m = epat.match(line)
                if m:
                    tmp_info[m.group('key').lower()] = m.group('value').strip()
        myfile.close()
        _type =  tmp_info.get('type', "unsigned_short")
        self._el_type = DECODER_DICT[_type][0]
        # decoder suffix for endianess
        if tmp_info.get('byte_order') == 'big_endian':
            self._raw_decoder = DECODER_DICT[_type][2]
        else:
            self._raw_decoder = DECODER_DICT[_type][1]
        info['delta_angle'] = float(tmp_info['osc_range'])
        info['distance']  = float(tmp_info['distance'])
        info['wavelength']  = float(tmp_info['wavelength'])
        info['exposure_time'] = float(tmp_info['time'])
        info['pixel_size'] = float(tmp_info['pixel_size'])
        orgx = float(tmp_info['beam_center_x'])/info['pixel_size']
        orgy =float(tmp_info['beam_center_y'])/info['pixel_size']
        info['beam_center'] = (orgy, orgx)
        info['detector_size'] = (int(tmp_info['size1']), int(tmp_info['size2']))
        # use image center if detector origin is (0,0)
        if sum(info['beam_center']) <  0.1:
            info['beam_center'] = (info['detector_size'][0]/2.0, info['detector_size'][1]/2.0)
        info['start_angle'] = float(tmp_info['osc_start'])
        if tmp_info.get('twotheta') is not None:
            info['two_theta'] = float(tmp_info['twotheta'])
        else:
            info['two_theta'] = 0.0
        
        if info['detector_size'][0] == 2304:
            info['detector_type'] = 'q4'
        elif info['detector_size'][0] == 1152:
            info['detector_type'] = 'q4-2x'
        elif info['detector_size'][0] == 4096:
            info['detector_type'] = 'q210'
        elif info['detector_size'][0] == 2048:
            info['detector_type'] = 'q210-2x'
        elif info['detector_size'][0] == 6144:
            info['detector_type'] = 'q315'
        elif info['detector_size'][0] == 3072:
            info['detector_type'] = 'q315-2x'
        info['file_format'] = 'SMV'
        info['filename'] = self.filename
        
        info['saturated_value'] = 2**(8*ctypes.sizeof(self._el_type)) - 1
        self.header = info

    def _read_image(self):
        num_el = self.header['detector_size'][0] * self.header['detector_size'][1]
        el_size = ctypes.sizeof(self._el_type)
        data_size = num_el*el_size
        myfile = open(self.filename,'rb')
        myfile.read(self._header_size)
        data = myfile.read(data_size)
        myfile.close()
        
        self.image = Image.fromstring('F', self.header['detector_size'], data, 'raw', self._raw_decoder)
        arr = numpy.fromstring(data, dtype=self._el_type)
        self.image = self.image.convert('I')
        self.header['average_intensity'] = arr.mean()
        self.header['min_intensity'], self.header['max_intensity'] = arr.min(), arr.max()
        self.header['gamma'] = calc_gamma(self.header['average_intensity'])
        self.header['overloads'] = len(numpy.where(arr >= self.header['saturated_value'])[0])

__all__ = ['SMVImageFile']
