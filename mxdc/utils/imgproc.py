import cv2
import numpy
from PIL import ImageChops
from PIL import ImageFilter
from mxdc.utils.scitools import find_peaks
from scipy import signal

THRESHOLD = 20
BORDER = 10
EDGE_TOLERANCE = 5


def image_deviation(img1, img2):
    img = ImageChops.difference(img1, img2).filter(ImageFilter.BLUR)
    ab = numpy.asarray(img.convert('L'))
    return ab.std()


def get_loop_features(orig, offset=10, scale=0.25, orientation='left'):
    raw = cv2.flip(orig, 1) if orientation != 'left' else orig
    y_max, x_max = orig.shape[:2]
    frame = cv2.resize(raw, (0, 0), fx=scale, fy=scale)

    clean = cv2.fastNlMeansDenoisingColored(frame, None, 10, 10, 11, 11)
    gray = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 3)
    edges = cv2.bitwise_not(cv2.erode(thresh, None, 10))
    edges[:offset, :] = 0
    edges[-offset:, :] = 0
    edges[:, -offset:] = 0

    avg, std = cv2.meanStdDev(gray)
    avg, std = avg.ravel()[0], std.ravel()[0]
    height, width = edges.shape
    tip_x, tip_y = width // 2, height // 2

    info = {
        'mean': avg,
        'std': std,
        'signal': avg / std,
        'score': 0.0,
        'center-x': tip_x / scale,
        'center-y': tip_y / scale,
    }

    if edges.max() > 128:
        info['score'] += 0.5

        prof = numpy.argwhere(edges.T > 128)
        cols, indices = numpy.unique(prof[:, 0], return_index=True)
        data = numpy.split(prof[:, 1], indices[1:])
        profiles = numpy.zeros((len(cols), 5), numpy.uint8)
        for i, arr in enumerate(data):
            mini, maxi = arr.min(), arr.max()
            profiles[i, :] = (cols[i], mini, maxi, maxi - mini, (maxi + mini) // 2)
            cv2.line(edges, (cols[i], mini), (cols[i], maxi), (128, 0, 255), 1)

        tip_x = profiles[:, 0].max()
        tip_y = profiles[profiles[:, 0].argmax(), 4]

        search_width = width / 6
        info['x'] = tip_x / scale
        info['y'] = tip_y / scale

        valid = (
            (numpy.abs(profiles[:, 4] - profiles[:, 4].mean()) < 2 * profiles[:, 4].std()) &
            (tip_x - profiles[:, 0] <= search_width)
        )  # reject outliers

        vertices = numpy.concatenate((
            profiles[:, (0, 1)][valid],
            profiles[:, (0, 2)][valid][::-1]
        )).astype(int)
        sizes = profiles[:, 3][valid]

        if len(vertices) > 5:
            ellipse = cv2.fitEllipse(vertices)
            info['ellipse'] = (
                tuple([int(x / scale) for x in ellipse[0]]),
                tuple([int(0.75 * x / scale) for x in ellipse[1]]),
                ellipse[2],
            )
            ellipse_x, ellipse_y = info['ellipse'][0]
            ellipse_w, ellipse_h = info['ellipse'][1]

            info['loop-x'] = int(ellipse_x)
            info['loop-y'] = int(ellipse_y)
            info['loop-size'] = max(ellipse_w, ellipse_h)
            info['loop-angle'] = 90 - ellipse[2]

            info['loop-start'] = ellipse_x + info['loop-size']/2
            info['loop-end'] = ellipse_x - info['loop-size']/2

        info['sizes'] = (sizes / scale).astype(int)
        info['points'] = [(int(x / scale), int(y / scale)) for x, y in vertices]

    else:
        info['x'] = 0
        info['y'] = info['center-x']

    if orientation == 'right':
        for k in ['loop-x', 'loop-start', 'loop-end', 'x']:
            if k in info:
                info[k] = x_max - info[k]
        if 'points' in info:
            info['points'] = [(x_max - x, y) for x, y in info['points']]

    return info


def dist(p1, p2):
    return numpy.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def find_profile(pil_img, scale=0.25, offset=2):
    # Determine the bounding polygon around the loop
    raw = numpy.asarray(pil_img.convert('L'))
    frame = cv2.resize(raw, (0, 0), fx=scale, fy=scale)
    raw_edges = cv2.Canny(frame, 50, 150)
    edges = numpy.zeros_like(raw_edges)
    edges[offset:-offset, offset:-offset] = raw_edges[offset:-offset, offset:-offset]

    contours, hierarchy = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2:]
    cv2.drawContours(edges, contours, -1, (255, 255, 255), 5)

    verts_top = []
    verts_bot = []
    verts_size = []
    nY, nX = edges.shape

    for i in range(nX):
        silhoutte = numpy.where(edges[:, i] > 128)[0]
        if numpy.any(silhoutte):
            verts_top.append((i, silhoutte[0]))
            verts_bot.append((i, silhoutte[-1] - 10))
            verts_size.append(silhoutte[-1] - silhoutte[0])

    if len(verts_size):
        sizes = numpy.abs(signal.savgol_filter(verts_size, 21, 1, deriv=0))
        hw = len(sizes) // 2
        ll = numpy.argmin(sizes[:hw])
        rr = numpy.argmin(sizes[hw:]) + hw
        verts = [v for i, v in enumerate(verts_top[ll:rr])] + [v for i, v in enumerate(verts_bot[ll:rr])][::-1]

        # simplify verts
        new_verts = [verts[0]]
        for i in range(len(verts)):
            if dist(verts[i], new_verts[-1]) > 30:
                new_verts.append(verts[i])

        points = (numpy.array(new_verts) / scale)
        return points


def mid_height(pil_img, offset=2):
    # Calculate the height of the pin at the center of the video profile
    raw = numpy.asarray(pil_img.convert('L'))
    scale = 256. / raw.shape[1]
    frame = cv2.resize(raw, (0, 0), fx=scale, fy=scale)
    raw_edges = cv2.Canny(frame, 50, 150)
    edges = numpy.zeros_like(raw_edges)
    edges[offset:-offset, offset:-offset] = raw_edges[offset:-offset, offset:-offset]

    contours, hierarchy = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2:]
    cv2.drawContours(edges, contours, -1, (255, 255, 255), int(10 * scale))

    y_size, x_size = edges.shape
    x_center = x_size // 2

    column = numpy.where(edges[:, x_center] > 128)[0]
    if numpy.any(column):
        return ((column[-1] - column[0]) / scale)
    else:
        return 0.0
