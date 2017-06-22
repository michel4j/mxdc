from bcm.utils.science import find_peaks
from PIL import Image
from PIL import ImageChops
from PIL import ImageFilter
import numpy

THRESHOLD = 20
BORDER = 10


def image_deviation(img1, img2):
    img = ImageChops.difference(img1, img2).filter(ImageFilter.BLUR)
    ab = numpy.asarray(img.convert('L'))
    return ab.std()


def _centroid(a):
    if a.sum() == 0.0:
        return -1
    else:
        return int((numpy.array(range(len(a))) * a).sum() / a.sum())


def _get_object(a):
    p = list(a > THRESHOLD)
    if True in p:
        mid = _centroid(a)
        pl = p.index(True)
        pr = len(p) - p[::-1].index(True) - 1
        span = abs(pr - pl)
        mid = (pr + pl) * 0.5
    else:
        mid, span = -1, 1
    return mid, max(span, 1)


def get_loop_center(orig, bkg, orientation=2):
    img = ImageChops.difference(orig, bkg).filter(ImageFilter.BLUR)
    if orientation == 3:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    ab = numpy.asarray(img.convert('L'))

    x = numpy.max(ab, 0)
    y = numpy.max(ab, 1)[::-1]
    quality = 0
    xp = list(x > THRESHOLD)
    if True in xp:
        xtip = len(xp) - xp[::-1].index(True) - 1
    else:
        xtip = 0
        quality -= 1
    ymid = _centroid(y)

    spans = numpy.zeros(x.shape)
    mids = numpy.zeros(x.shape)
    for i in range(xtip):
        yl = ab[:, i][::-1]
        mid, span = _get_object(yl)
        spans[i] = span
        mids[i] = mid
    peaks = find_peaks(range(len(spans)), 255 - spans, sensitivity=0.05)
    if len(peaks) > 1:
        ls = peaks[-2][0]
        le = peaks[-1][0]
        loop = spans[ls:le]
        lx = 1 + numpy.array(range(len(loop)))
        xmid = le - int(numpy.exp(numpy.log(lx).mean()))
        width = loop.mean()
        if xmid > 0:
            ymid = mids[xmid]
    else:
        xmid = xtip
        width = -1

    if orientation == 3:
        xmid = len(x) - xmid

    return xmid, len(y) - ymid, width


def get_cap_center(orig, bkg, orientation=2):
    img = ImageChops.difference(orig, bkg).filter(ImageFilter.BLUR)

    if orientation == 3:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    ab = numpy.asarray(img.convert('L'))

    x = numpy.max(ab, 0)
    y = numpy.max(ab, 1)[::-1]
    quality = 0
    xp = list(x > THRESHOLD)

    if True in xp:
        xtip = len(xp) - xp[::-1].index(True) - 1
    else:
        xtip = 0
        quality -= 1

    ymid = _centroid(y)

    # get the width
    spans = numpy.zeros(x.shape)
    mids = numpy.zeros(x.shape)
    for i in range(xtip):  # for each index in True positions.
        yl = ab[:, i][::-1]  # yl is a vertical slice of ab, listed backwards. 'bottom to top'
        mid, span = _get_object(yl)
        spans[i] = span
        mids[i] = mid

    width = spans.mean()

    return xtip, (len(y) - ymid), width


def _normalize(data):
    data = data - data.min()
    return (100.0 * data) / data.max()
