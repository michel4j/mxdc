import time
from dataclasses import dataclass

import cv2
import numpy

from threading import Thread


TIME_OFFSET = 0.1       # Time offset for the spindle position, equiv. to inference duration


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


def find_axis_offset(angles, y_coords):
    """
    Calculates the vertical offset of a horizontal rotation axis.
    :param angles: angles corresponding to coordinates
    :param y_coords:  y pixel coordinates
    Returns:
        float: The vertical y-offset of the axis of rotation.
    """
    angles = numpy.radians(angles)
    y = numpy.array(y_coords)

    # Build the design matrix: [cos(theta), sin(theta), 1]
    X = numpy.column_stack((numpy.cos(angles), numpy.sin(angles), numpy.ones_like(angles)))

    # Solve least squares problem: X * [a, b, offset]^T = y
    coefficients, _, _, _ = numpy.linalg.lstsq(X, y, rcond=None)

    # The offset is the constant term (c)
    offset = coefficients[2]

    return offset


def clean_mean(values, threshold=2):
    """
    Calculate the mean of an array, taking into account outliers, rejection
    :param values: value array
    :param threshold: maximum number of standard deviations
    :return: float
    """
    mean = numpy.mean(values)
    std_dev = numpy.std(values)
    filtered_data = values[numpy.abs(values - mean) < (threshold * std_dev)]
    return numpy.mean(filtered_data)


class LoopRecorder:
    """
    An Object that records the loop width and height from the sample video feed
    """
    def __init__(self, spindle, total, device=None):
        """
        Initialize the loop recorder
        :param spindle: sample spindle motor
        :param total: total angle range
        :param device: Centering device
        """
        super().__init__()
        self.objects = {
            'loops': [],
            'crystals': [],
        }
        self.angles = []
        self.running = False
        self.stopped = False
        self.device = device
        self.spindle = spindle
        self.total_angle = total
        self.stats = {}
        self.crystal_info = []

    def run(self):
        """
        Run the loop recorder and record the loop width and height
        """
        self.running = True
        self.stopped = False
        self.objects = {
            'loops': [],
            'crystals': [],
        }
        self.angles = []
        cb_id = self.spindle.connect('changed', self.save_angle)

        while self.running:
            obj = self.device.get_object(label='loop')
            xtal = self.device.get_object(label='crystal')
            if obj:
                self.objects['loops'].append(obj)
            if xtal:
                self.objects['crystals'].append(xtal)
            time.sleep(0.05)

        self.spindle.disconnect(cb_id)

        self.calc_stats()
        self.stopped = True

    def save_angle(self, obj, position):
        self.angles.append([time.time(), position])

    def has_objects(self):
        """
        Check if there are any objects recorded
        :return: True if there are objects, False otherwise
        """
        return len(self.objects['loops']) > 2

    def has_crystal(self):
        return len(self.objects['crystals']) > 0

    def calc_stats(self, label='loops'):
        """
        Calculate some information for scoring the recorded loops
        """

        total = len(self.objects[label])
        valid = [obj for obj in self.objects[label] if obj is not None]
        if valid:
            self.stats = {
                'total': total,
                'valid': len(valid) / total,
                'time': Stats.create([obj.time for obj in valid]),
                'x': Stats.create([obj.x for obj in valid]),
                'y': Stats.create([obj.y for obj in valid]),
                'w': Stats.create([obj.w for obj in valid]),
                'h': Stats.create([obj.h for obj in valid]),
                'score': Stats.create([obj.score for obj in valid]),
            }
        else:
            self.stats = {}

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

        angles = numpy.array(self.angles)
        face_angle = self.spindle.get_position()
        if self.objects['loops']:
            loops = self.objects['loops']
            loop_times = numpy.array([obj.time for obj in loops if obj is not None])
            loop_heights = numpy.array([obj.h for obj in loops if obj is not None])
            loop_angles = numpy.interp(loop_times, angles[:, 0], angles[:, 1], left=0, right=0)
            face_angle = (loop_angles[numpy.argmin(loop_heights)] + 90.0) % 360

        if self.objects['crystals']:
            crystals = self.objects['crystals']
            xtal_x = numpy.array([obj.x for obj in crystals if obj is not None])
            xtal_y = numpy.array([obj.y for obj in crystals if obj is not None])
            xtal_times = numpy.array([obj.time for obj in crystals if obj is not None])
            xtal_scores = numpy.array([obj.score for obj in crystals if obj is not None])
            xtal_angles = numpy.interp(xtal_times, angles[:, 0], angles[:, 1], left=0, right=0)

            self.crystal_info = [
                {
                    'x': int(xtal_x[i]),
                    'y': int(xtal_y[i]),
                    'score': float(xtal_scores[i]),
                    'angle': float(xtal_angles[i])
                }
                for i in range(len(xtal_x))
            ]
        else:
            self.crystal_info = []

        return face_angle

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

    def stop(self):
        self.running = False
        self.stopped = True

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

