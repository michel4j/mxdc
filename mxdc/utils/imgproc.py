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
    raw_edges = cv2.Canny(frame, 50, 150)
    edges = numpy.zeros_like(raw_edges)
    edges[offset:-offset, offset:-offset] = raw_edges[offset:-offset, offset:-offset]

    contours, hierarchy = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2:]
    cv2.drawContours(edges, contours, -1, (255, 255, 255), int(10 * scale))
    avg = frame.mean()
    std = frame.std()
    y_size, x_size = edges.shape
    tip_x, tip_y = x_size // 2, y_size // 2

    info = {
        'mean': avg,
        'std': std,
        'signal': avg / std,
        'score': 0.0,
        'center-x': tip_x / scale,
        'center-y': tip_y / scale,
    }

    if contours:
        info['score'] += 0.5
        top_vertices = []
        bottom_vertices = []
        vertical_spans = []
        vertical_midpoints = []

        for i in range(x_size):
            column = numpy.where(edges[:, i] > 128)[0]
            if numpy.any(column):
                top_vertices.append((i, column[0]))
                bottom_vertices.append((i, column[-1]))
                vertical_spans.append((i, column[-1] - column[0]))
                vertical_midpoints.append((i, (column[-1] + column[0]) // 2))
                tip_x = i
                tip_y = (column[0] + column[-1]) // 2
                if i == x_size // 2:
                    info['capillary-y'] = tip_y/scale
            else:
                vertical_spans.append((i, 0))
                vertical_midpoints.append((i, y_size // 2))

        info['x'] = tip_x / scale - 10
        info['y'] = tip_y / scale

        if len(vertical_spans):
            info['score'] += 0.5
            sizes = numpy.array(vertical_spans)
            sizes[:, 1] = signal.savgol_filter(sizes[:, 1], 15, 1)
            peaks = find_peaks(sizes[:, 0], sizes[:, 1], width=15)

            x_center = int(peaks[-1][0]) if peaks else (tip_x - x_size // 16)
            y_center = vertical_midpoints[x_center][1]
            search_width = tip_x - x_center
            search_start = x_center - search_width
            search_end = tip_x

            vertices = [v for i, v in enumerate(top_vertices[search_start:search_end])]
            vertices += [v for i, v in enumerate(bottom_vertices[search_start:search_end])][::-1]
            ellipse_vertices = [v for v in vertices if v[0] > x_center + search_width // 3]

            info['loop-size'] = int(sizes[x_center][1] / scale)
            info['loop-x'] = int(x_center / scale)
            info['loop-y'] = int(y_center / scale)

            points = (numpy.array(vertices[::5])).astype(int)
            if len(ellipse_vertices) > 10:
                ellipse = cv2.fitEllipse(numpy.array(ellipse_vertices).astype(int))
                info['ellipse'] = (
                    tuple([int(x / scale) for x in ellipse[0]]),
                    tuple([int(0.75 * x / scale) for x in ellipse[1]]),
                    ellipse[2],
                )
                ellipse_x, ellipse_y = info['ellipse'][0]
                info['loop-x'] = int(ellipse_x)
                info['loop-y'] = int(ellipse_y)
                info['loop-size'] = max(ellipse[1])
                info['loop-angle'] = 90 - ellipse[2]

            info['loop-start'] = search_start / scale
            info['loop-end'] = search_end / scale
            info['peaks'] = peaks
            info['sizes'] = (sizes / scale).astype(int)
            info['points'] = [(int(x / scale), int(y / scale)) for x, y in points]

    else:
        info['x'] = 0
        info['y'] = info['center-x']

    if orientation == 'right':
        for k in ['loop-x', 'loop-start', 'loop-end', 'x']:
            if k in info:
                info[k] = x_max - info[k]
        if 'points' in info:
            info['points'] = [(x_max - x, y) for x,y in info['points']]
        if 'peaks' in info:
            info['peaks'] = [(x_max - x, y) for x, y in info['peaks']]
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
