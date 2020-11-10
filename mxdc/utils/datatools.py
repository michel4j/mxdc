import copy
import glob
import os
import re
from collections import defaultdict
from datetime import date
from datetime import datetime

import numpy
import pytz
from mxio import read_header
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
        'delta': 0.5, 'range': 2, 'start': 0.0, 'inverse': False,
        'desc': 'Screen 0°, 90°, 180°, 270°',
        'activity': 'screen'
    },
    StrategyType.SCREEN_3: {
        'delta': 0.5, 'range': 2, 'start': 0.0, 'inverse': False,
        'desc': 'Screen 0°, 45°, 90°',
        'activity': 'screen'
    },
    StrategyType.SCREEN_2: {
        'delta': 0.5, 'range': 2, 'start': 0.0, 'inverse': False,
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

    from mxdc.conf import settings

    sample = {} if not sample else sample
    params = copy.deepcopy(info)

    params.update({
        'session': settings.get_session(),
        'sample': misc.slugify(sample.get('name', '')),
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

    def __init__(self, sample):
        self.sample = sample
        self.names = set()
        self.history = defaultdict(int)

    def fix(self, name):
        new_name = name
        m = re.match(rf'({self.sample}.+)(\d+)', name)
        if m:
            root = m.group(1)
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


def summarize_list(values):
    """
    Takes a list of integers such as [1,2,3,4,6,7,8] and summarises it as a string "1-4,6-8"
    
    :param values: 
    :return: string
    """

    sorted_values = numpy.array(sorted(values))
    summaries = [
        (f'{chunk[0]}-{chunk[-1]}' if len(chunk) > 1 else f'{chunk[0]}')
        for chunk in  numpy.split(sorted_values, numpy.where(numpy.diff(sorted_values) > 1)[0] + 1)
        if len(chunk)
    ]
    return ','.join(summaries)


def summarize_gaps(values):
    """
    Takes a list of integers such as [1,2,3,4,7,8] and reduces it to the string of skipped regions such as "5-6"
    
    :param values: 
    :return: string summary
    """

    complete_set = set(range(1, max(values) + 1))
    frame_set = set(values)
    full_set = list(complete_set.difference(frame_set))
    return summarize_list(full_set)


def generate_frames(wedge: dict):
    """
    Generate individual frames for the given wedge

    :param wedge: wedge information
    :return: A generator of frame parameter dicts
    """

    return ({
            'name': wedge['name'],
            'uuid': wedge.get('uuid'),
            'saved': False,
            'first': i + wedge['first'],
            'start': wedge['start'] + i * wedge['delta'],
            'delta': wedge['delta'],
            'exposure': wedge['exposure'],
            'energy': wedge['energy'],
            'distance': wedge['distance'],
            'two_theta': wedge.get('two_theta', 0.0),
            'attenuation': wedge.get('attenuation', 0.0),
            'directory': wedge['directory'],
        }
        for i in range(wedge['num_frames'])
    )


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
    num_frames = max(1, int(total_range / run['delta']))
    first = run.get('first', 1)
    frame_numbers = set(range(first, num_frames + first))

    if run.get("inverse"):
        first = first + int(180. / run['delta'])
        frame_numbers |= set(range(first, num_frames + first))

    excluded = set(frameset_to_list(merge_framesets(run.get('skip', ''), run.get('existing', ''))))
    return frame_numbers - excluded


def calc_num_frames(strategy, delta, range, skip=''):
    """
    Count the number of frames in a dataset

    :param strategy: run strategy
    :param delta: delta angle
    :param range: angle range
    :param skip: frames to skip
    """

    if strategy in [StrategyType.SCREEN_2, StrategyType.SCREEN_3, StrategyType.SCREEN_4]:
        size = max(1, range / delta)
        total_range = ScreeningRange.get(strategy, range) + size * delta
    else:
        total_range = range

    num_frames = max(1, int(total_range / delta))

    excluded = len(frameset_to_list(skip))
    return num_frames - excluded


def count_frames(run):
    if not (run.get('delta') and run.get('range')):
        return 1
    else:
        return len(get_frame_numbers(run))


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

    full_set = [int(m.group(1)) for f in data_files for m in [file_pattern.search(f)] if m]
    return {
        'start_time': start_time,
        'frames': summarize_list(full_set),
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


def grid_frames(params: dict):
    """
    Generate frame parameters for individual grid data frames when performed in step mode.

    :param params: run parameters
    :return: list of dictionaries representing a frame each
    """
    return (
        {
            'name': params['name'],
            'uuid': params['uuid'],
            'saved': False,
            'first': i + 1,
            'start': params['angle'],
            'delta': params['delta'],
            'exposure': params['exposure'],
            'energy': params['energy'],
            'distance': params['distance'],
            'two_theta': params.get('two_theta', 0.0),
            'attenuation': params.get('attenuation', 0.0),
            'directory': params['directory'],
            'p0': point,
        }
        for i, point in enumerate(params['grid'])
    )


def wedge_points(start, end, steps):
    """
    Split the given starting and ending point into the given number of steps

    :param start: start point coordinates (tuple of values) or None
    :param end: end point coordinates (tuple of values) or None
    :param steps: number of steps
    :return: array of point pairs corresponding to the start and end of each sub section
    """

    if not start:
        points = numpy.array([None] * (steps + 1))
    elif not end:
        points = numpy.array([start] + [None] * (steps))
    else:
        points = numpy.linspace(start, end, steps + 1)
    return numpy.take(points, [[i, i + 1] for i in range(points.shape[0] - 1)], axis=0)


def make_wedges(run: dict):
    """
    Given run parameters, generate all wedges required to implement the experiment except for inverse beam
    which is handled much later after interleaving. This includes calculating the starting point for multi-point/vector
    data collection.

    :param run: dictionary of run parameters.
    :return: list of dictionaries each representing a wedge.
    """
    delta = run.get('delta', 1.0)
    total = calc_range(run)
    first = run.get('first', 1)

    # reconcile vector_size with requested wedge size. vector_size should be 1 for 4D helical scans
    vector_slice = total // run['vector_size'] if run.get('vector_size') > 1 and run.get('p1') else total
    slice = min(vector_slice, run.get('wedge', 180), total)

    # determine start point,  end point and list of frames for each wedge
    num_wedges = int(total / slice)
    positions = wedge_points(run.get('p0'), run.get('p1'), num_wedges)
    wedge_frames = int(slice / delta)
    wedge_numbers = numpy.arange(wedge_frames)

    frames_points = [
        (positions[i][0], positions[i][1], (first + i * wedge_frames + wedge_numbers).tolist())
        for i in range(num_wedges)
    ]

    # remove skipped or existing frames.
    excluded = frameset_to_list(merge_framesets(run.get('skip', ''), run.get('existing', '')))
    wedge_info = [
        (start_pos, end_pos, numpy.array(sorted(set(frames) - set(excluded))))
        for start_pos, end_pos, frames in frames_points
    ]

    # split discontinuous sections into independent wedges
    wedges = [
        (start_pos, end_pos, chunk)
        for start_pos, end_pos, frames in wedge_info
        for chunk in numpy.split(frames, numpy.where(numpy.diff(frames) > 1)[0] + 1)
        if frames.shape[0]
    ]

    return [
        {
            'uuid': run.get('uuid'),
            'name': run['name'],
            'directory': run['directory'],
            'start': run['start'] + (frames[0] - run['first']) * run['delta'],
            'first': frames[0],
            'num_frames': len(frames),
            'delta': run['delta'],
            'exposure': run['exposure'],
            'distance': run['distance'],
            'energy': run.get('energy', 12.658),
            'two_theta': run.get('two_theta', 0.0),
            'attenuation': run.get('attenuation', 0.0),
            'p0': start_pos if start_pos is None else tuple(start_pos),
            'p1': end_pos if end_pos is None else tuple(end_pos),
            'inverse': run.get('inverse', False),
            'weight': run['exposure'] * len(frames)
        }
        for start_pos, end_pos, frames in wedges
    ]


class WedgeDispenser(object):
    """
    Given a data run, generate sequences of wedges to be interleaved. Typically the sequences
    will contain a single wedge but when inverse beam is used, pairs are generated each time

    :param run: run parameters
    """

    def __init__(self, run: dict):
        self.details = run
        self.sample = run.get('sample', {})

        # generate main wedges
        self.wedges = make_wedges(self.details)
        self.num_wedges = len(self.wedges)
        self.pos = 0

        # total weights for progress
        self.weight = sum(wedge['weight'] for wedge in self.wedges)
        self.weight *= 2 if self.details.get('inverse') else 1  # inverse beam takes twice as long

        # progress housekeeping
        self.complete = 0
        self.pending = 0
        self.progress = 0.0
        self.factor = 1

    def set_progress(self, fraction):
        """
        Set the percentage of the current wedge that has been completed

        :param fraction: fraction of current pending workload that is complete set to 1 if complete.
        """

        self.progress = (self.complete + (fraction * self.pending) / self.factor) / self.weight
        if fraction == 1.0:
            self.complete += (fraction * self.pending)/self.factor

    def has_items(self):
        """
        Check if wedges remain
        """
        return self.pos < self.num_wedges

    def fetch(self):
        """
        Produce collections of one or more two
        """
        if self.pos >= self.num_wedges:
            return ()

        wedge = self.wedges[self.pos]
        self.pos += 1
        self.pending = wedge['weight']

        # prepare inverse beam
        if wedge['inverse']:
            inv_wedge = copy.deepcopy(wedge)
            inv_wedge['first'] += int(180. / wedge['delta'])
            inv_wedge['start'] += 180.
            self.factor = 2
            return (wedge, inv_wedge)
        else:
            self.factor = 1
            return (wedge,)


def interleave(*datasets):
    """
    For the provided Wedge dispensers, yield one wedge at a time in the right order

    :param datasets: WedgeDispenser objects
    :return: generator of wedge parameters
    """

    while any(dataset.has_items() for dataset in datasets):
        for dataset in datasets:
            if dataset.has_items():
                for wedge in dataset.fetch():
                    yield wedge