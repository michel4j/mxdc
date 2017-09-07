import cv2
import numpy
from PIL import Image
from PIL import ImageChops
from PIL import ImageFilter
from mxdc.utils.science import find_peaks
from scipy import ndimage

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


EDGE_TOLERANCE = 5


def get_sample_bbox(img):
    img_arr = numpy.asarray(img.convert('L'))
    full = numpy.array([[0, 0], img_arr.shape[::-1]])
    full[1] -= EDGE_TOLERANCE
    bbox = numpy.copy(full)
    for i in range(2):
        profile = numpy.min(img_arr[EDGE_TOLERANCE:-EDGE_TOLERANCE, EDGE_TOLERANCE:-EDGE_TOLERANCE], i) * -1
        profile -= profile.min()
        envelope = numpy.where(profile > profile.max() / 2)[0]
        if len(envelope):
            bbox[0][i] = max(envelope[0], bbox[0][i])
            bbox[1][i] = min(envelope[-1], bbox[1][i])

    # check the boxes and adjust if one horizontal side on edge:
    if bbox[0][0] > 2 * EDGE_TOLERANCE and full[1][0] - bbox[1][0] < 2 * EDGE_TOLERANCE:
        bbox[1][0] = full[1][0] - bbox[0][0] // 2
    elif bbox[0][0] < 2 * EDGE_TOLERANCE and full[1][0] - bbox[1][0] > 2 * EDGE_TOLERANCE:
        bbox[0][0] = (full[1][0] - bbox[1][0]) // 2

    return bbox + EDGE_TOLERANCE


def get_sample_bbox2(img):
    img_arr = ndimage.morphological_gradient(numpy.asarray(img.convert('L')), size=(10, 10))
    full = numpy.array([[0, 0], img_arr.shape[::-1]])
    full[1] -= EDGE_TOLERANCE
    bbox = numpy.copy(full)
    for i in range(2):
        profile = numpy.max(img_arr[EDGE_TOLERANCE:-EDGE_TOLERANCE, EDGE_TOLERANCE:-EDGE_TOLERANCE], i)
        profile -= profile.min()
        envelope = numpy.where(profile > profile.max() / 2)[0]
        if len(envelope):
            bbox[0][i] = max(envelope[0], bbox[0][i])
            bbox[1][i] = min(envelope[-1], bbox[1][i])

    # check the boxes and adjust if one horizontal side on edge:
    if bbox[0][0] > 2 * EDGE_TOLERANCE and full[1][0] - bbox[1][0] < 2 * EDGE_TOLERANCE:
        bbox[1][0] = full[1][0] - bbox[0][0] // 2
    elif bbox[0][0] < 2 * EDGE_TOLERANCE and full[1][0] - bbox[1][0] > 2 * EDGE_TOLERANCE:
        bbox[0][0] = (full[1][0] - bbox[1][0]) // 2

    return bbox


def get_bbox(pil_img):
    img = cv2.cvtColor(numpy.asarray(pil_img), cv2.COLOR_RGB2BGR)
    edges = cv2.Canny(img, 100, 200)
    im2, contours, hierarchy = cv2.findContours(edges)
    return


def find_profile(pil_img, scale=20):
    from scipy import signal
    raw_img = numpy.asarray(pil_img.convert('L'))

    img = cv2.resize(raw_img, (0, 0), fx=1./scale, fy=1./scale, interpolation=cv2.INTER_LANCZOS4)
    std = img.std()
    verts_top = []
    verts_bot = []
    nX, nY = img.shape
    xcoords = numpy.arange(nX)
    for i in range(nY):
        x = img[:, i]
        xd = numpy.abs(signal.savgol_filter(x, 3, 1, deriv=1))
        if xd.std() < 0.25*std: continue
        print xd.std()
        xpin = xcoords[xd >= 0.25 * xd.max()]
        if len(xpin) > 1:
            verts_top.append((i, xpin[0]))
            verts_bot.append((i, xpin[-1]))
    return scale * numpy.array(verts_top + verts_bot[::-1])
