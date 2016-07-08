import math
import struct
import numpy
from PIL import Image
from utils import calc_gamma

class RAXISImageFile(object):
    def __init__(self, filename, header_only=False):
        self.filename = filename
        self._read_header()
        if not header_only:
            self._read_image()

    def _read_header(self):
        header = {}

        # Read RAXIS header
        header = [
             '10s10s20s12s6f12s1f80s84x',
            '12s20s4s1f20s1f20s4s1f1f1f12s80s1l1f56x',
            '4s4s3f1l1f2f4f205x',
            '2l2f4l3f10s10s3l2f2l15f5f5f5f1l40s',
            '16s20s20s9l20l20l1i768s',
        ]


        myfile = open(self.filename, 'rb')

        params = [
            struct.unpack(fmt, myfile.read(struct.calcsize(fmt)))
            for fmt in header
        ]
        import json
        print json.dumps(params[3], indent=4)
        myfile.close()
        import sys
        sys.exit()
        # extract some values from the header
        # use image center if detector origin is (0,0)
        if params[1] / 1e3 + goniostat_pars[2] / 1e3 < 0.1:
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

        det_mm = int(round(header['pixel_size'] * header['detector_size'][0]))
        header['detector_type'] = 'mar%d' % det_mm
        header['file_format'] = 'TIFF'
        self.header = header

    def _read_image(self):
        raw_img = Image.open(self.filename)
        self.raw_data = raw_img.load()

        # recalculate average intensity if not present within file
        if self.header['average_intensity'] < 0.01:
            self.header['average_intensity'] = numpy.mean(numpy.fromstring(raw_img.tostring(), 'H'))
        self.header['gamma'] = calc_gamma(self.header['average_intensity'])
        self.image = raw_img.convert('I')


__all__ = ['RAXISImageFile']
