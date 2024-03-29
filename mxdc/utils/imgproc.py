import time
import cv2
import numpy
from threading import Thread


class LoopRecorder:
    """
    An Object that records the loop width and height from the sample video feed
    """
    def __init__(self, beamline):
        super().__init__()
        self.beamline = beamline
        self.widths = []
        self.heights = []
        self.running = False

    def run(self):
        """
        Run the loop recorder and record the loop width and height
        """
        self.running = True
        self.widths = []    # Clear the previous data
        self.heights = []
        while self.running:
            self.beamline.sample_video.fetch_frame()
            raw = self.beamline.sample_video.get_frame()
            frame = cv2.cvtColor(numpy.asarray(raw), cv2.COLOR_RGB2BGR)
            info = get_loop_features(frame, orientation=self.beamline.config.orientation)
            self.widths.append(info['loop-width'])
            self.heights.append(info['loop-height'])
            time.sleep(0.0)

    def get_widths(self):
        """
        Get the recorded loop widths
        """
        return numpy.array(self.widths)

    def get_heights(self):
        """
        Get the recorded loop heights
        """
        return numpy.array(self.heights)

    def start(self):
        """
        Start the loop recorder in a separate thread
        """
        if not self.running:
            worker_thread = Thread(target=self.run, daemon=True, name=self.__class__.__name__)
            worker_thread.start()

    def stop(self):
        """
        Stop the loop recorder
        """
        self.running = False

    def is_running(self):
        return self.running

    def __del__(self):
        self.stop()


def get_loop_features(orig, offset=10, scale=0.5, orientation='left'):
    raw = cv2.flip(orig, 1) if orientation != 'left' else orig
    y_max, x_max = orig.shape[:2]
    frame = cv2.resize(raw, (0, 0), fx=scale, fy=scale)

    clean = cv2.fastNlMeansDenoisingColored(frame, None, 10, 10, 11, 11)
    gray = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 3)
    edges = cv2.bitwise_not(cv2.dilate(thresh, None, 10))
    avg, stddev = cv2.meanStdDev(gray)

    edges[:offset, :] = 0
    edges[-offset:, :] = 0
    edges[:, -offset:] = 0
    height, width = edges.shape
    tip_x, tip_y = width // 2, height // 2

    info = {
        'mean': avg,
        'std': stddev,
        'signal': avg / stddev,
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

        size = profiles[:, 3].max()
        cap_tips = numpy.argwhere(profiles[:, 3] <= size / 2)

        info['capillary-y'] = profiles[:, 4].mean() / scale
        info['capillary-size'] = size / scale
        if cap_tips.size > 0:
           info['capillary-x'] = (cap_tips[0][0] - width) / scale
        else:
            info['capillary-x'] = (width // 2) / scale

        valid = (
            (numpy.abs(profiles[:, 3] - profiles[:, 3].mean()) < 2 * profiles[:, 3].std())
            & (profiles[:, 3] < 0.8 * height)
        )
        if valid.sum() > 5:
            profiles = profiles[valid]

        tip_x = profiles[:, 0].max()
        tip_y = profiles[profiles[:, 0].argmax(), 4]

        info['x'] = tip_x / scale
        info['y'] = tip_y / scale
        search_width = width / 5
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

