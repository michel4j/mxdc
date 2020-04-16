import copy
import itertools
import os
import glob
import re
import pytz
from datetime import datetime
from collections import defaultdict
from datetime import date

import numpy
from mxio import read_header

from mxdc.conf import settings
from mxdc.utils import misc

FRAME_NUMBER_DIGITS = 4
OUTLIER_DEVIATION = 50


class StrategyType(object):
    SINGLE, FULL, SCREEN_2, SCREEN_3, SCREEN_4, POWDER = range(6)


Strategy = {
    StrategyType.SINGLE: {
        'range': 1.0, 'delta': 1.0, 'start': 0.0, 'inverse': False,
        'desc': 'Single Frame',
        'activity': 'test',
    },
    StrategyType.FULL: {
        'range': 180,
        'desc': 'Full Dataset',
        'activity': 'data',
    },
    StrategyType.SCREEN_4: {
        'delta': 1.0, 'range': 2, 'start': 0.0, 'inverse': False,
        'desc': 'Screen 0°, 90°, 180°, 270°',
        'activity': 'screen'
    },
    StrategyType.SCREEN_3: {
        'delta': 1.0, 'range': 2, 'start': 0.0, 'inverse': False,
        'desc': 'Screen 0°, 45°, 90°',
        'activity': 'screen'
    },
    StrategyType.SCREEN_2: {
        'delta': 1.0, 'range': 2, 'start': 0.0, 'inverse': False,
        'desc': 'Screen 0°, 90°',
        'activity': 'screen'
    },
    StrategyType.POWDER: {
        'delta': 180.0, 'exposure': 30.0, 'range': 360.0, 'inverse': False,
        'desc': 'Powder',
        'activity': 'data'
    }
}

StrategyDataType = {
    StrategyType.SINGLE: 'SCREEN',
    StrategyType.FULL: 'DATA',
    StrategyType.SCREEN_4: 'SCREEN',
    StrategyType.SCREEN_3: 'SCREEN',
    StrategyType.SCREEN_2: 'SCREEN',
    StrategyType.POWDER: 'XRD'
}

StrategyProcType = {
    StrategyType.SINGLE: '',
    StrategyType.FULL: 'proc-native',
    StrategyType.SCREEN_4: 'proc-screen',
    StrategyType.SCREEN_3: 'proc-screen',
    StrategyType.SCREEN_2: 'proc-screen',
    StrategyType.POWDER: 'proc-powder'
}

ScreeningRange = {
    StrategyType.SCREEN_4: 270,
    StrategyType.SCREEN_3: 90,
    StrategyType.SCREEN_2: 90,
}


class AnalysisType:
    MX_NATIVE, MX_ANOM, MX_SCREEN, RASTER, XRD = range(5)


def update_for_sample(info, sample=None, overwrite=True):
    # Add directory and related auxillary information to dictionary
    # provides values for {session} {sample}, {group}, {container}, {port}, {date}, {activity}

    sample = {} if not sample else sample
    params = copy.deepcopy(info)

    params.update({
        'session': settings.get_session(),
        'sample': sample.get('name', ''),
        'group': misc.slugify(sample.get('group', '')),
        'container': misc.slugify(sample.get('container', '')),
        'port': sample.get('port', ''),
        'position': '' if not sample.get('location', '') else sample['location'].zfill(2),
        'date': date.today().strftime('%Y%m%d'),
        'activity': params.get('activity', ''),
        'sample_id': sample.get('id'),
    })

    template = settings.get_string('directory-template')
    activity_template = template[1:] if template[0] == os.sep else template
    activity_template = activity_template[:-1] if activity_template[-1] == os.sep else activity_template
    dir_template = os.path.join(misc.get_project_home(), '{session}', activity_template)
    params['directory'] = dir_template.format(**params).replace('//', '/').replace('//', '/')
    if not overwrite and os.path.exists(params['directory']):
        for i in range(99):
            new_directory = '{}-{}'.format(params['directory'], i + 1)
            if not os.path.exists(new_directory):
                params['directory'] = new_directory
                break
    params['sample'] = sample
    return params

class NameManager(object):
    """
    An object which keeps track of dataset names in a run list and makes sure
    unique names are generated
    """

    def __init__(self):
        self.names = set()
        self.history = defaultdict(int)

    def fix(self, name):
        new_name = name
        m = re.match(r'(.+)(\d+)', name)
        if m:
            root = m.group(1)
            index = int(m.group(2))
            if name in self.names:
                new_name = "{}{}".format(root, self.history[root])
            self.history[root] += 1
        elif name in self.names:
            new_name = "{}{}".format(name, self.history[name])
            self.history[name] += 1
        else:
            self.history[name] += 1
            new_name = name
        return new_name

    def __call__(self, name):
        new_name = self.fix(name)
        self.names.add(new_name)
        return new_name


def fix_name(name, names, index):

    if not names:
        new_name = name
    elif name in names:
        m = re.match(r'(.+)(\d+)', name)
        if m:
            new_name = "{}{}".format(m.group(1), int(m.group(2))+1)
        else:
            new_name = "{}{}".format(name, 1)
    else:
        new_name = name

    return new_name


def add_framsets(run):
    info = copy.deepcopy(run)
    info['frame_sets'] = generate_frame_sets(info)
    return info


def summarize_list(full_frame_set):
    # takes a list of integers such as [1,2,3,4,6,7,8]
    # and reduces it to the string "1-4,6-8"
    sum_list = []
    tmp_pairs = []
    full_set = list(set(full_frame_set))

    if len(full_set) == 0:
        return ""
    full_set.sort()
    cur = full_set.pop(0)
    tmp_pairs.append([cur, cur])
    while len(full_set) > 0:
        cur = full_set.pop(0)
        last_pair = tmp_pairs[-1]
        if (cur - last_pair[-1]) == 1:
            last_pair[-1] = cur
        else:
            tmp_pairs.append([cur, cur])

    for st, en in tmp_pairs:
        if st == en:
            sum_list.append('{}'.format(st, ))
        else:
            sum_list.append('{}-{}'.format(st, en))
    return ','.join(sum_list)


def summarize_gaps(frame_list):
    # takes a list of integers such as [1,2,3,4,7,8]
    # and reduces it to the string of skipped regions such as "5-6"

    complete_set = set(range(1, max(frame_list) + 1))
    frame_set = set(frame_list)
    full_set = list(complete_set.difference(frame_set))
    return summarize_list(full_set)


def generate_frames(wedge):
    frame_list = []
    # initialize general parameters
    for i in range(wedge['num_frames']):
        # generate frame info
        frame = {
            'dataset': wedge['name'],
            'uuid': wedge.get('uuid'),
            'saved': False,
            'first': i + wedge['first'],
            'frame_name': wedge['frame_template'].format(i + wedge['first']),
            'start': wedge['start'] + i * wedge['delta'],
            'delta': wedge['delta'],
            'exposure': wedge['exposure'],
            'energy': wedge['energy'],
            'distance': wedge['distance'],
            'two_theta': wedge.get('two_theta', 0.0),
            'attenuation': wedge.get('attenuation', 0.0),
            'directory': wedge['directory'],
        }
        frame_list.append(frame)

    return frame_list


def generate_collection_list(run, frame_set):
    collection_list = []

    # generate frame info
    first_frame, start_angle = frame_set[0]
    data_set = {
        'uuid': run.get('uuid'),
        'dataset': run['name'],
        'name': run['name'],
        'frame_template': make_file_template(run['name']),
        'start': start_angle,
        'first': first_frame,
        'num_frames': len(frame_set),
        'delta': run['delta'],
        'exposure': run.get('exposure', 1.0),
        'energy': run.get('energy', 12.658),
        'distance': run['distance'],
        'two_theta': run.get('two_theta', 0.0),
        'attenuation': run.get('attenuation', 0.0),
        'directory': run['directory'],
        'point': run.get('point', None)
    }
    collection_list.append(data_set)
    return collection_list


def calc_range(run):
    """
    Calculate the total range for the given strategy. For normal runs simply return the defined range. For
    screening runs, the defined range is used just for a given slice of data, the full range for the dataset
    is calculated from this by adding the slice in degrees to the total range spanning the frames, defined
    in the the ScreeningRange dictionary.
    :param run: Run parameters (dict)
    :return: a floating point angle in degrees
    """
    if run.get('strategy') in [StrategyType.SCREEN_2, StrategyType.SCREEN_3, StrategyType.SCREEN_4]:
        size = max(1, int(float(run['range']) / run['delta']))
        return ScreeningRange.get(run['strategy'], run.get('range', 180.)) + size * run['delta']
    else:
        return run['range']


def get_frame_numbers(run):
    """
    Generate the set of frame numbers for a given run.
    :param run: Run parameters (dict)
    :return: a set of integers
    """
    total_range = calc_range(run)
    num_frames = max(1, int(total_range / run.get('delta', 1.0)))
    first = run.get('first', 1)
    frame_numbers = set(range(first, num_frames + first))
    excluded = set(frameset_to_list(merge_framesets(run.get('skip', ''), run.get('existing', ''))))
    return frame_numbers - excluded


def generate_frame_names(run):
    # get the list of frame names for the given run
    valid_numbers = get_frame_numbers(run)
    template = make_file_template(run['name'])
    names = [template.format(index) for index in sorted(valid_numbers)]
    if run.get('inverse', False):
        inverse_start = int(180.0 / run.get('delta', 1.0)) + run.get('first', 1)
        names += [template.format(index + inverse_start) for index in sorted(valid_numbers)]
    return names


def count_frames(run):
    if not (run.get('delta') and run.get('range')):
        return 1
    else:
        return len(get_frame_numbers(run))


def generate_frame_sets(run, show_number=True):
    make_wedges(run)
    frame_sets = []

    # initialize general parameters
    delta_angle = run.get('delta', 1.0)
    total_angle = calc_range(run)
    first_frame = run.get('first', 1)
    start_angle = run.get('start', 0.0)

    wedge = run.get('wedge', 360.0)

    # make sure wedge is good
    if wedge < total_angle:
        wedge = delta_angle * round(wedge / delta_angle)

    # generate list of frames to exclude from skip
    excluded_frames = frameset_to_list(merge_framesets(run.get('skip', ''), run.get('existing', '')))
    n_wedge = int(round(wedge / delta_angle))  # number of frames in a wedge

    # inverse beam
    if run.get('inverse', False):
        offsets = [0.0, 180.0]
    else:
        offsets = [0.0, ]

    # first wedge
    wedge_start = start_angle
    while wedge_start <= start_angle + (total_angle - delta_angle):
        wedge_list = []
        for offset in offsets:
            for i in range(n_wedge):
                angle = wedge_start + i * delta_angle
                if angle > start_angle + (total_angle - delta_angle):
                    break
                angle += offset

                frame_number = int(round(first_frame + (angle - start_angle) / delta_angle))
                if frame_number in excluded_frames:
                    # new wedge if skipping
                    if wedge_list:
                        frame_sets.append(wedge_list)
                        wedge_list = []
                else:
                    wedge_list.append((frame_number, angle))

        if wedge_list:
            frame_sets.append(wedge_list)

        wedge_start += wedge
    return frame_sets


def generate_run_list(runs):
    datasets, wedges = generate_wedges(runs)
    run_list = list(itertools.chain.from_iterable(generate_frames(wedge) for wedge in wedges))
    return run_list


class Interleaver(object):
    """Produce lists of framesets for specified wedge at a time until consumed"""

    def __init__(self, dataset):
        self.dataset = dataset
        self.wedges = make_wedges(dataset)
        self.position = 0

    def has_items(self):
        return self.position < len(self.wedges)

    def fetch(self):
        if self.has_items():
            pos = self.position
            self.position += 1
            return self.wedges[pos]


def generate_wedges(runs):
    dispensers = [Interleaver(d) for d in runs]
    items_exist = any(disp.has_items() for disp in dispensers)
    pos = 0
    wedge_list = []
    while items_exist:
        chunk = dispensers[pos].fetch()

        if chunk:
            # update wedge weight (total exposure for wedge)
            chunk['weight'] = chunk['exposure']*chunk['num_frames']
            wedge_list.append(chunk)
        items_exist = any(disp.has_items() for disp in dispensers)
        pos = (pos + 1) % len(dispensers)
    return runs, wedge_list


def dataset_from_files(directory, file_glob):
    """
    Given a file pattern and directory, read the header and dataset information for the dataset on disk

    :param directory: directory containing the dataset
    :param file_glob: pattern for matching files
    :return:  dataset dictionary. Expected fields are
        'start_time':  start time for the dataset
        'frames':  A frame list string, eg '1-5,8-10' or '1'
    """
    file_pattern = re.compile(file_glob.replace('*', r'(\d{2,6})'))
    data_files = sorted(glob.glob(os.path.join(directory, file_glob)))

    start_time = None

    if data_files:
        start_time = datetime.fromtimestamp(
            os.path.getmtime(os.path.join(directory, data_files[0])), tz=pytz.utc
        )

    full_set = [int(m.group(1)) for f in data_files for m in [file_pattern.match(f)] if m]
    return {
        'start_time': start_time,
        'frames':summarize_list(full_set),
        'num_frames': len(full_set),
    }


def dataset_from_reference(directory, reference_file):
    """
    Given a reference file and directory, read the header and dataset information for the dataset on disk

    :param directory: directory containing the dataset
    :param reference_file: representative file from the dataset
    :return:  dataset dictionary. Expected fields are
        'start_time':  start time for the dataset
        'frames':  A frame list string, eg '1-5,8-10' or '1'
    """

    header = read_header(os.path.join(directory, reference_file))
    sequence = header['dataset'].get('sequence', [])
    return {
        'start_time': header['dataset'].get('start_time', datetime.now(tz=pytz.utc)),
        'frames': summarize_list(sequence),
        'num_frames': len(sequence)
    }


def frameset_to_list(frame_set):
    frame_numbers = []
    ranges = filter(None, frame_set.split(','))
    wlist = [list(map(int, filter(None, w.split('-')))) for w in ranges]
    for v in wlist:
        if len(v) == 2:
            frame_numbers.extend(range(v[0], v[1] + 1))
        elif len(v) == 1:
            frame_numbers.extend(v)
    return frame_numbers


def merge_framesets(*args):
    frame_set = ','.join(filter(None, args))
    sequence = frameset_to_list(frame_set)
    return summarize_list(sequence)


def make_file_template(name):
    return '{}_{}'.format(name, '{{:0{}d}}'.format(FRAME_NUMBER_DIGITS))


def template_to_glob(template):
    return re.sub(r'{[^{}]*}', '*', template)


def generate_grid_frames(grid, params):
    frame_template = make_file_template(params['name'])
    return [
        {
            'dataset': params['name'],
            'uuid': params['uuid'],
            'saved': False,
            'first': i,
            'frame_name': frame_template.format(i),
            'start': params['angle'],
            'delta': params['delta'],
            'exposure': params['exposure'],
            'energy': params['energy'],
            'distance': params['distance'],
            'two_theta': params.get('two_theta', 0.0),
            'attenuation': params.get('attenuation', 0.0),
            'directory': params['directory'],
            'point': point,
        }
        for i, point in enumerate(grid)
    ]


def _split_wedge(a):
    return numpy.split(a, numpy.where(numpy.diff(a) > 1)[0] + 1)


def _calc_points(start, end, steps):
    if not start:
        return numpy.array([None] * steps)
    elif not end:
        end = start
    points = numpy.zeros((steps, 3))
    for i in range(3):
        points[:, i] = numpy.linspace(start[i], end[i], steps)
    return points


def make_wedges(run):
    delta = run.get('delta', 1.0)
    total = calc_range(run)
    first = run.get('first', 1)
    if run.get('vector_size') and run.get('end_point'):
        wedge = total // run['vector_size']
    else:
        wedge = min(run.get('wedge', 180), total)

    num_wedges = int(total / wedge)
    points = _calc_points(run.get('point'), run.get('end_point'), num_wedges)

    wedge_frames = int(wedge / delta)
    wedge_numbers = numpy.arange(wedge_frames)

    full_wedges = [
        (points[i], (first + i * wedge_frames + wedge_numbers).tolist())
        for i in range(num_wedges)
    ]
    excluded = frameset_to_list(merge_framesets(run.get('skip', ''), run.get('existing', '')))
    raw_wedges = [
        (point, numpy.array(sorted(set(wedge) - set(excluded))))
        for point, wedge in full_wedges
    ]
    wedges = [
        (point, w)
        for point, wedge in raw_wedges
        for w in _split_wedge(wedge) if wedge.shape[0]
    ]

    return [
        {
            'uuid': run.get('uuid'),
            'dataset': run['name'],
            'name': run['name'],
            'frame_template': make_file_template(run['name']),
            'start': run['start'] + (frames[0] - run['first']) * run['delta'],
            'first': frames[0],
            'num_frames': len(frames),
            'delta': run['delta'],
            'exposure': run.get('exposure', 1.0),
            'energy': run.get('energy', 12.658),
            'distance': run['distance'],
            'two_theta': run.get('two_theta', 0.0),
            'attenuation': run.get('attenuation', 0.0),
            'directory': run['directory'],
            'point': point
        }
        for point, frames in wedges
    ]


class Validator(object):
    class Clip(object):
        def __init__(self, dtype, lo, hi):
            self.dtype = dtype
            self.lo = lo
            self.hi = hi

        def __call__(self, val):
            return min(max(self.lo, self.dtype(val)), self.hi)

    class Length(object):
        def __init__(self, dtype, max_length):
            self.dtype = dtype
            self.max_length = max_length

        def __call__(self, val):
            return val[:self.max_length]
