"""
Overview
========

    This module provides an object oriented interface to CBFlib.
"""

from bcm.utils import parse_tools
from bcm.utils.imageio import common
from bcm.utils.imageio.utils import calc_gamma
from bcm.utils.log import get_module_logger
from ctypes import c_size_t, c_char_p, cdll, c_double, c_int, c_uint, c_long, sizeof
from ctypes import c_uint16, c_uint32, POINTER, c_int32, c_int16, c_void_p, byref
import Image
import ctypes
import numpy
import re

# Configure Logging
_logger = get_module_logger('imageio.cbf')

# Define CBF Error Code constants
CBF_FORMAT         = 0x00000001  #      1
CBF_ALLOC          = 0x00000002  #      2
CBF_ARGUMENT       = 0x00000004  #      4
CBF_ASCII          = 0x00000008  #      8
CBF_BINARY         = 0x00000010  #     16
CBF_BITCOUNT       = 0x00000020  #     32
CBF_ENDOFDATA      = 0x00000040  #     64
CBF_FILECLOSE      = 0x00000080  #    128
CBF_FILEOPEN       = 0x00000100  #    256
CBF_FILEREAD       = 0x00000200  #    512
CBF_FILESEEK       = 0x00000400  #   1024
CBF_FILETELL       = 0x00000800  #   2048
CBF_FILEWRITE      = 0x00001000  #   4096
CBF_IDENTICAL      = 0x00002000  #   8192
CBF_NOTFOUND       = 0x00004000  #  16384
CBF_OVERFLOW       = 0x00008000  #  32768
CBF_UNDEFINED      = 0x00010000  #  65536
CBF_NOTIMPLEMENTED = 0x00020000  # 131072
CBF_NOCOMPRESSION  = 0x00040000  # 262144

PLAIN_HEADERS  = 0x0001  # Use plain ASCII headers           
MIME_HEADERS   = 0x0002  # Use MIME headers                  
MSG_NODIGEST   = 0x0004  # Do not check message digests      
MSG_DIGEST     = 0x0008  # Check message digests             
MSG_DIGESTNOW  = 0x0010  # Check message digests immediately 
MSG_DIGESTWARN = 0x0020  # Warn on message digests immediately
PAD_1K         = 0x0020  # Pad binaries with 1023 0's        
PAD_2K         = 0x0040  # Pad binaries with 2047 0's        
PAD_4K         = 0x0080  # Pad binaries with 4095 0's        

CBF_ERROR_MESSAGES = {
    CBF_FORMAT         : 'Invalid File Format',
    CBF_ALLOC          : 'Memory Allocation Error',
    CBF_ARGUMENT       : 'Invalid function arguments',
    CBF_ASCII          : 'Value is ASCII (not binary)',
    CBF_BINARY         : 'Value is binary (not ASCII)',
    CBF_BITCOUNT       : 'Expected number of bits does not match actual number written',
    CBF_ENDOFDATA      : 'End of data was reached before end of array',
    CBF_FILECLOSE      : 'File close error',
    CBF_FILEOPEN       : 'File open error',
    CBF_FILEREAD       : 'File read error',
    CBF_FILESEEK       : 'File seek error',
    CBF_FILETELL       : 'File tell error',
    CBF_FILEWRITE      : 'File write error',
    CBF_IDENTICAL      : 'Data block with identical name already exists',
    CBF_NOTFOUND       : 'Data block/category/column/row does not exist',
    CBF_OVERFLOW       : 'Value overflow error. The value has been truncated',
    CBF_UNDEFINED      : 'Requested number is undefined',
    CBF_NOTIMPLEMENTED : 'Requested functionality is not implemented',
    CBF_NOCOMPRESSION  : 'No compression',
}


DECODER_DICT = {
    "unsigned 16-bit integer": (c_uint16, 'F;16','F;16B'),
    "unsigned 32-bit integer": (c_uint32, 'F;32','F;32B'),
    "signed 16-bit integer": (c_int16, 'F;16S','F;16BS'),
    "signed 32-bit integer": (c_int32, 'F;32S','F;32BS'),
}

ELEMENT_TYPES = {
    "signed 32-bit integer":c_int32,
    }

def _format_error(code):
    errors = []
    for k, v in CBF_ERROR_MESSAGES.items():
        if (code | k) == code:
            errors.append(v)
    return ', '.join(errors)
        
             
try:
    cbflib = cdll.LoadLibrary('libcbf.so.0')
except:
    _logger.error("CBF shared library 'libcbf.so' could not be loaded!")
    raise common.FormatNotAvailable

try:
    libc = cdll.LoadLibrary('libc.so.6')
except:
    _logger.error("C runtime library 'libc.so.6' could not be loaded!")
    raise common.FormatNotAvailable


# define argument and return types
libc.fopen.argtypes = [c_char_p, c_char_p]
libc.fopen.restype = c_void_p

cbflib.cbf_make_handle.argtypes = [c_void_p]
cbflib.cbf_free_handle.argtypes = [c_void_p]
cbflib.cbf_read_file.argtypes = [c_void_p, c_void_p, c_int]
cbflib.cbf_read_widefile.argtypes = [c_void_p, c_void_p, c_int]
cbflib.cbf_get_wavelength.argtypes = [c_void_p, POINTER(c_double)]
cbflib.cbf_get_integration_time.argtypes = [c_void_p, c_uint, POINTER(c_double)]
cbflib.cbf_get_image_size.argtypes = [c_void_p, c_uint, c_uint, POINTER(c_size_t), POINTER(c_size_t)]
cbflib.cbf_construct_goniometer.argtypes = [c_void_p, c_void_p]
cbflib.cbf_construct_detector.argtypes = [c_void_p, c_void_p, c_uint]
cbflib.cbf_construct_reference_detector.argtypes = [c_void_p, c_void_p, c_uint]
cbflib.cbf_require_reference_detector.argtypes = [c_void_p, c_void_p, c_uint]
cbflib.cbf_read_template.argtypes = [c_void_p, c_void_p]
cbflib.cbf_get_pixel_size.argtypes = [c_void_p, c_uint, c_int, POINTER(c_double)]
cbflib.cbf_get_detector_distance.argtypes = [c_void_p, POINTER(c_double)]
cbflib.cbf_get_beam_center.argtypes = [c_void_p, POINTER(c_double), POINTER(c_double), POINTER(c_double), POINTER(c_double)]
cbflib.cbf_get_rotation_range.argtypes = [c_void_p, c_uint, POINTER(c_double), POINTER(c_double)]
cbflib.cbf_get_detector_normal.argtypes = [c_void_p, POINTER(c_double), POINTER(c_double), POINTER(c_double)]
cbflib.cbf_get_rotation_axis.argtypes = [c_void_p, c_uint, POINTER(c_double), POINTER(c_double), POINTER(c_double)]
cbflib.cbf_get_image.argtypes = [c_void_p, c_uint, c_uint, c_void_p, c_size_t, c_int, c_size_t, c_size_t]
cbflib.cbf_get_detector_id.argtypes = [c_void_p, c_uint, c_void_p]
cbflib.cbf_parse_mimeheader.argtypes = [c_void_p, POINTER(c_int), POINTER(c_size_t), POINTER(c_long),
    c_void_p, POINTER(c_uint), POINTER(c_int), POINTER(c_int), POINTER(c_int), c_void_p,
    POINTER(c_size_t), POINTER(c_size_t), POINTER(c_size_t), POINTER(c_size_t), POINTER(c_size_t)]
cbflib.cbf_get_integerarray.argtypes = [c_void_p, POINTER(c_int), c_void_p, c_size_t, c_int, c_size_t, POINTER(c_size_t)]
cbflib.cbf_select_datablock.argtypes = [c_void_p, c_uint]
cbflib.cbf_count_datablocks.argtypes = [c_void_p, POINTER(c_uint)]
cbflib.cbf_find_datablock.argtypes = [c_void_p, c_char_p]
cbflib.cbf_find_category.argtypes = [c_void_p, c_char_p]
cbflib.cbf_find_column.argtypes = [c_void_p, c_char_p]
cbflib.cbf_datablock_name.argtypes = [c_void_p, c_void_p]
cbflib.cbf_get_overload.argtypes = [c_void_p, c_uint, POINTER(c_double)]

def get_max_int(t):
    v = t(2**(8*sizeof(t))-1).value
    if v == -1: #signed
        return c_double(2**(8*sizeof(t)-1)-1)
    else:       #unsiged
        return c_double(2**(8*sizeof(t)-1))
    
class CBFImageFile(object):
    def __init__(self, filename, header_only=False):
        self._cbflib = cbflib # keep a reference until all objects are destroyed
        self.filename = filename
        self.handle = c_void_p()
        self.goniometer = c_void_p()
        self.detector = c_void_p()
        
        # make the handle
        res = cbflib.cbf_make_handle(byref(self.handle))
        
        # read the file
        fp = libc.fopen(self.filename, "rb")
        #res = cbflib.cbf_read_widefile(self.handle, fp, MSG_NODIGEST)
        res |= cbflib.cbf_read_template(self.handle, fp)
        res |= cbflib.cbf_construct_goniometer(self.handle, byref(self.goniometer))
        res |= cbflib.cbf_require_reference_detector(self.handle, byref(self.detector), 0)
        self._read_header()
        
        if not header_only:
            self._read_image()

    def _read_mime(self):
        hr = re.compile('^(.+):\s+(.+)$')
        bin_st = re.compile('^--CIF-BINARY-FORMAT-SECTION--')
        mime_header = {}
        parse_tokens = {
            "Content-Type": str,
            "Content-Transfer-Encoding": str,
            "Content-MD5" : str,
            "X-Binary-Size": int,
            "X-Binary-ID": int,
            "X-Binary-Element-Type": str,
            "X-Binary-Element-Byte-Order": str,
            "X-Binary-Number-of-Elements": int ,
            "X-Binary-Size-Fastest-Dimension": int,
            "X-Binary-Size-Second-Dimension": int,
            "X-Binary-Size-Third-Dimension": int,
            "X-Binary-Size-Padding": int}
    
        fh = open(self.filename)
        # find start of binary header
        i = 0
        while not bin_st.match(fh.readline()) and i < 512:
            i += 1

        if i >= 512:
            return mime_header
            
        # extract binary header
        l = fh.readline()
        while l.strip() != '':
            m = hr.match(l)
            if m:
                mime_header[m.group(1)] = parse_tokens[m.group(1)](m.group(2).replace('"', '').strip())
            l = fh.readline()                      
        fh.close()
        return mime_header
            
    def _read_header(self):
        header = {}
        
        # First parse mime-header
        self.mime_header = self._read_mime()
                               
        wvl = c_double(1.0)
        res = cbflib.cbf_get_wavelength(self.handle, byref(wvl))
        header['wavelength'] = wvl.value

        sz1 = c_size_t(self.mime_header.get('X-Binary-Size-Fastest-Dimension', 0))
        sz2 = c_size_t(self.mime_header.get('X-Binary-Size-Second-Dimension', 0))
        res |= cbflib.cbf_get_image_size(self.handle, 0, 0, byref(sz1), byref(sz2))
        header['detector_size'] = (sz1.value, sz2.value)
        
        px1 = c_double(1.0)
        res |= cbflib.cbf_get_pixel_size(self.handle, 0, 1, byref(px1))
        header['pixel_size'] = px1.value
        
        dst = c_double(999.0)
        res |= cbflib.cbf_get_detector_distance(self.detector, byref(dst))
        header['distance'] = dst.value
        
        dx, dy = c_double(0.0), c_double(0.0)
        ix, iy = c_double(sz1.value / 2.0), c_double(sz2.value / 2.0)
        res |= cbflib.cbf_get_beam_center(self.detector, byref(ix), byref(iy), byref(dx), byref(dy))
        header['beam_center'] = (ix.value, iy.value)
        
        it = c_double(0.0)
        res |= cbflib.cbf_get_integration_time(self.handle, 0, it)
        header['exposure_time'] = it.value

        st, inc = c_double(0.0), c_double(0.0)
        res |= cbflib.cbf_get_rotation_range(self.goniometer, 0, byref(st), byref(inc))
        header['start_angle'] = st.value
        header['delta_angle'] = inc.value
        
        el_type = DECODER_DICT[self.mime_header.get('X-Binary-Element-Type', 'signed 32-bit integer')][0]
        ovl = get_max_int(el_type)
        res |= cbflib.cbf_get_overload(self.handle, 0, byref(ovl))
        header['saturated_value'] = ovl.value
        
        nx, ny, nz = c_double(0.0), c_double(0.0), c_double(0.0)
        res |= cbflib.cbf_get_detector_normal(self.detector, byref(nx), byref(ny), byref(nx))
        detector_norm = numpy.array([nx.value, ny.value, nz.value])
        
        nx, ny, nz = c_double(0.0), c_double(0.0), c_double(0.0)
        res |= cbflib.cbf_get_rotation_axis(self.goniometer, 0, byref(nx), byref(ny), byref(nx))
        rot_axis = numpy.array([nx.value, ny.value, nz.value])
        
        #FIXME Calculate actual two_theta from the beam direction and detector normal
        header['two_theta'] = 0.0
        del rot_axis, detector_norm
        
        header['filename'] = self.filename
        
        det_id = c_char_p()
        res |= cbflib.cbf_get_detector_id(self.handle, 0, byref(det_id))
        header['detector_type'] = det_id.value
        if header['detector_type'] == None:
            header['detector_type'] = 'Unknown'
        header['file_format'] = 'CBF'

        if header['distance'] == 999.0 and header['delta_angle'] == 0.0 and header['exposure_time'] == 0.0:
            res = cbflib.cbf_select_datablock(self.handle, c_uint(0))
            res |= cbflib.cbf_find_category(self.handle, "array_data")
            res |= cbflib.cbf_find_column(self.handle, "header_convention")
            hdr_type = c_char_p()
            res |= cbflib.cbf_get_value(self.handle, byref(hdr_type))   
            res |= cbflib.cbf_find_column(self.handle, "header_contents")   
            hdr_contents = c_char_p()
            res |= cbflib.cbf_get_value(self.handle, byref(hdr_contents))
            if res == 0 and hdr_type.value != 'XDS special':
                _logger.info('miniCBF header type found: %s' % hdr_type.value)
                config = '%s.ini' % hdr_type.value.lower()
                info = parse_tools.parse_data(hdr_contents.value, config)
                header['detector_type'] = info['detector'].lower().strip().replace(' ', '')
                header['two_theta'] = info['two_theta']
                header['pixel_size'] = info['pixel_size'][0] * 1000
                header['exposure_time'] = info['exposure_time']
                header['wavelength'] = info['wavelength']
                header['distance'] = info['distance']*1000
                header['beam_center'] = info['beam_center']
                header['start_angle'] = info['start_angle']
                header['delta_angle'] = info['delta_angle']
                header['saturated_value'] = info['saturated_value']
                header['sensor_thickness'] = info['sensor_thickness']*1000
            else:
                _logger.warning('miniCBF with no header')
        self.header = header

        
    def _read_image(self):
        num_el = self.header['detector_size'][0] * self.header['detector_size'][1]
        el_params = DECODER_DICT[self.mime_header.get('X-Binary-Element-Type', 'signed 32-bit integer')]
        el_type = el_params[0]
        el_size = sizeof(el_type)
        data = ctypes.create_string_buffer(num_el * el_size)
        res = cbflib.cbf_get_image(self.handle, 0, 0, byref(data), el_size,
                    1, self.header['detector_size'][0], self.header['detector_size'][1])
        if res != 0:
            # MiniCBF
            res = cbflib.cbf_select_datablock(self.handle, c_uint(0))
            res |= cbflib.cbf_find_category(self.handle, "array_data")
            res |= cbflib.cbf_find_column(self.handle, "data")
            binary_id = c_int(self.mime_header.get('X-Binary-ID', 1))
            num_el_read = c_size_t()
            res |= cbflib.cbf_get_integerarray(self.handle, byref(binary_id), byref(data), el_size,
                1, c_size_t(num_el), byref(num_el_read))
            if res != 0:
                _logger.error('MiniCBF Image data error: %s' % (_format_error(res),))
                        
        self.image = Image.fromstring('F', self.header['detector_size'], data, 'raw', el_params[1])
        self.image = self.image.convert('I')
        arr = numpy.fromstring(data, dtype=el_type)
        self.header['average_intensity'] = arr.mean()    
        self.header['min_intensity'], self.header['max_intensity'] = arr.min(), arr.max()
        self.header['gamma'] = calc_gamma(self.header['average_intensity'])
        self.header['overloads'] = len(numpy.where(arr >= self.header['saturated_value'])[0])
                    
    def __del__(self):
        res = self._cbflib.cbf_free_handle(self.handle)
        res |= self._cbflib.cbf_free_goniometer(self.goniometer)
        res |= self._cbflib.cbf_free_detector(self.detector)


__all__ = ['CBFImageFile']
