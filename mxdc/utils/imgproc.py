import time
from dataclasses import dataclass

import cv2
import numpy
import pprint
from threading import Thread


@dataclass
class Stats:
    avg: float
    std: float
    min: float
    max: float
    range: float
    values: list

    @staticmethod
    def create(data):
        """
        Create a stats object from the data
        :param data: array of values
        :return: Stats object
        """

        return Stats(
            avg=float(numpy.mean(data)),
            std=float(numpy.std(data)),
            min=float(numpy.min(data)),
            max=float(numpy.max(data)),
            range=float(numpy.ptp(data)),
            values=data
        )


class LoopRecorder:
    """
    An Object that records the loop width and height from the sample video feed
    """
    def __init__(self, start, total, device=None):
        """
        Initialize the loop recorder
        :param start: start angle
        :param total: total angle range
        :param device: Centering device
        """
        super().__init__()
        self.objects = []
        self.running = False
        self.stopped = False
        self.device = device
        self.start_angle = start
        self.total_angle = total
        self.stats = {}

    def run(self):
        """
        Run the loop recorder and record the loop width and height
        """
        self.running = True
        self.stopped = False
        self.objects = []    # Clear the previous data
        while self.running:
            self.objects.append(self.device.get_object())
            time.sleep(0.001)
        self.calc_stats()
        self.stopped = True

    def has_objects(self):
        """
        Check if there are any objects recorded
        :return: True if there are objects, False otherwise
        """
        return len(self.objects) > 2

    def calc_stats(self):
        """
        Calculate some information for scoring the recorded loops
        """

        total = len(self.objects)
        valid = [obj for obj in self.objects if obj is not None]
        self.stats = {
            'total': total,
            'valid': len(valid) / total,
            'x': Stats.create([obj.x for obj in valid]),
            'y': Stats.create([obj.y for obj in valid]),
            'w': Stats.create([obj.w for obj in valid]),
            'h': Stats.create([obj.h for obj in valid]),
            'score': Stats.create([obj.score for obj in valid]),
        }

    def get_stats(self) -> dict:
        """
        Get the stats for the recorded loops
        :return: stats dictionary
        """
        return self.stats

    def get_face_angle(self):
        """
        Get the face angle for the recorded loops
        """
        if not self.stats:
            return self.start_angle

        angles = numpy.linspace(self.start_angle, self.start_angle + self.total_angle, self.stats['total'])
        return angles[numpy.argmax(self.stats['h'].values)]

    def get_edge_angle(self):
        """
        Get the edge angle for the recorded loops
        """
        return (self.get_face_angle() - 90) % 360

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
        while not self.stopped:
            time.sleep(0.1)

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
            info['score'] = 0.0 if not info['loop-width'] else 100*(1 - abs(info['loop-start'] - info['x'])/info['loop-width'])

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

