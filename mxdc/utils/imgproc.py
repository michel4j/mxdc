import cv2
import numpy


def get_loop_features(orig, offset=10, scale=0.5, orientation='left'):
    raw = cv2.flip(orig, 1) if orientation != 'left' else orig
    y_max, x_max = orig.shape[:2]
    frame = cv2.resize(raw, (0, 0), fx=scale, fy=scale)

    clean = cv2.fastNlMeansDenoisingColored(frame, None, 10, 10, 11, 11)
    gray = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 3)
    edges = cv2.bitwise_not(cv2.dilate(thresh, None, 10))
    avg, stdev = cv2.meanStdDev(gray)

    edges[:offset, :] = 0
    edges[-offset:, :] = 0
    edges[:, -offset:] = 0
    height, width = edges.shape
    tip_x, tip_y = width // 2, height // 2

    info = {
        'mean': avg,
        'std': stdev,
        'signal': avg / stdev,
        'found': 0,                 # 0 = nothing found, 1 = tip found, 2 = ellipse fitted.
        'center-x': tip_x / scale,
        'center-y': tip_y / scale,
        'score': 0.0,
    }

    if edges.max() > 10:
        info['found'] = 1
        prof = numpy.argwhere(edges.T > 128)
        cols, indices = numpy.unique(prof[:, 0], return_index=True)
        data = numpy.split(prof[:, 1], indices[1:])
        profiles = numpy.zeros((len(cols), 5), int)
        for i, arr in enumerate(data):
            mini, maxi = arr.min(), arr.max()
            profiles[i, :] = (cols[i], mini, maxi, maxi - mini, (maxi + mini) // 2)
            cv2.line(edges, (cols[i], mini), (cols[i], maxi), (128, 0, 255), 1)

        search_width = width / 5
        idx = 3
        valid = (
            (numpy.abs(profiles[:, idx] - profiles[:, idx].mean()) < 2 * profiles[:, idx].std())
            & (profiles[:, idx] < 0.8 * height)
        )
        if valid.sum() > 5:
            profiles = profiles[valid]

        tip_x = profiles[:, 0].max()
        tip_y = profiles[profiles[:, 0].argmax(), 4]

        info['x'] = tip_x / scale
        info['y'] = tip_y / scale
        valid = (profiles[:, 0] >= tip_x - search_width)

        vertices = numpy.concatenate((
            profiles[:, (0, 1)][valid],
            profiles[:, (0, 2)][valid][::-1]
        )).astype(int)
        sizes = profiles[:, 3][valid]

        if len(vertices) > 5:
            center, size, angle = cv2.fitEllipse(vertices)
            c_x, c_y = center
            s_x, s_y = size
            if abs(c_y - tip_y) > height // 2 or s_x >= width or s_y >= height:
                center, size, angle = cv2.minAreaRect(vertices)
            info['found'] = 2
            info['ellipse'] = (
                tuple([int(x / scale) for x in center]),
                tuple([int(x / scale) for x in size]),
                angle,
            )

            ellipse_x, ellipse_y = info['ellipse'][0]
            ellipse_w, ellipse_h = max(info['ellipse'][1]), min(info['ellipse'][1])

            info['loop-x'] = int(ellipse_x)
            info['loop-y'] = int(ellipse_y)
            info['loop-width'] = ellipse_w
            info['loop-height'] = ellipse_h
            info['loop-angle'] = angle

            info['loop-start'] = ellipse_x + info['loop-width']/2
            info['loop-end'] = ellipse_x - info['loop-width']/2
            info['score'] = 100*(1 - abs(info['loop-start'] - info['x'])/info['loop-width'])

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

