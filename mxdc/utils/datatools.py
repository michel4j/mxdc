import copy
import glob
import os
import re

from collections import defaultdict
from datetime import date
from datetime import datetime
from enum import IntEnum, auto

import numpy
import pytz
from mxio import read_image
from mxdc.utils import misc

FRAME_NUMBER_DIGITS = 4
OUTLIER_DEVIATION = 50


class StrategyType(IntEnum):
    SINGLE = auto()
    FULL = auto()
    SCREEN_1 = auto()
    SCREEN_2 = auto()
    SCREEN_3 = auto()
    SCREEN_4 = auto()
    POWDER = auto()


class TaskType(IntEnum):
    MOUNT = auto()
    CENTER = auto()
    SCREEN = auto()
    ACQUIRE = auto()
    RASTER = auto()
    XRF = auto()
    ANALYSE = auto()


Strategy = {
    StrategyType.SINGLE: {
        'range': 1.0, 'delta': 1.0, 'start': 0.0, 'inverse': False,
        'desc': 'Single Frame',
        'activity': 'test',
        'strategy': StrategyType.SINGLE,
    },
    StrategyType.FULL: {
        'range': 360,
        'desc': 'Full Dataset',
        'activity': 'data',
        'strategy': StrategyType.FULL,
    },
    StrategyType.SCREEN_4: {
        'delta': 0.5, 'range': 2, 'start': 0.0, 'inverse': False,
        'desc': 'Screen 0°, 90°, 180°, 270°',
        'activity': 'screen',
        'strategy': StrategyType.SCREEN_4,
    },
    StrategyType.SCREEN_3: {
        'delta': 0.5, 'range': 2, 'start': 0.0, 'inverse': False,
        'desc': 'Screen 0°, 45°, 90°',
        'activity': 'screen',
        'strategy': StrategyType.SCREEN_3,
    },
    StrategyType.SCREEN_2: {
        'delta': 0.5, 'range': 2, 'start': 0.0, 'inverse': False,
        'desc': 'Screen 0°, 90°',
        'activity': 'screen',
        'strategy': StrategyType.SCREEN_2,
    },
    StrategyType.SCREEN_1: {
        'delta': 0.5, 'range': 2, 'start': 0.0, 'inverse': False,
        'desc': 'Screen 0°',
        'activity': 'screen',
        'strategy': StrategyType.SCREEN_1,
    },
    StrategyType.POWDER: {
        'delta': 180.0, 'exposure': 30.0, 'range': 360.0, 'inverse': False,
        'desc': 'Powder',
        'activity': 'data',
        'strategy': StrategyType.POWDER,
    }
}

StrategyDataType = {
    StrategyType.SINGLE: 'SCREEN',
    StrategyType.FULL: 'DATA',
    StrategyType.SCREEN_4: 'SCREEN',
    StrategyType.SCREEN_3: 'SCREEN',
    StrategyType.SCREEN_2: 'SCREEN',
    StrategyType.SCREEN_1: 'SCREEN',
    StrategyType.POWDER: 'XRD'
}

ScreeningRange = {
    StrategyType.SCREEN_4: 315,
    StrategyType.SCREEN_3: 135,
    StrategyType.SCREEN_2: 135,
    StrategyType.SCREEN_1: 45,
}

ScreeningAngles = {
    StrategyType.SCREEN_4: (0, 90, 180, 270),
    StrategyType.SCREEN_3: (0, 45, 90),
    StrategyType.SCREEN_2: (0, 90),
    StrategyType.SCREEN_1: (0,),
}


class AnalysisType(IntEnum):
    MX_NATIVE = auto()
    MX_ANOM = auto()
    MX_SCREEN = auto()
    RASTER = auto()
    XRD = auto()


def update_for_sample(info: dict, sample: dict = None, session: str = "") -> dict:
    """
    Update the directory information with sample specific information. The directory template will
    be instantiated with values for the fields {session} {sample}, {group}, {container}, {port}, {date}, {activity}
    from the info dictionary and the sample dictionary.

    :param info: dictionary containing activity information
    :param sample:
    :param session:
    :return:
    """

    from mxdc.conf import settings

    sample = {} if not sample else sample
    params = {**info}

    params.update({
        'session': session,
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
    params['sample'] = sample
    return params


def get_activity_folder(sample: dict, activity: str, session: str = '') -> str:
    from mxdc.conf import settings
    sample = {} if not sample else sample
    params = {
        'session': session,
        'sample': misc.slugify(sample.get('name', '')),
        'group': misc.slugify(sample.get('group', '')),
        'container': misc.slugify(sample.get('container', '')),
        'port': sample.get('port', ''),
        'position': '' if not sample.get('location', '') else sample['location'].zfill(2),
        'date': date.today().strftime('%Y%m%d'),
        'activity': activity,
        'sample_id': sample.get('id'),
    }

    template = settings.get_string('directory-template')
    activity_template = template[1:] if template[0] == os.sep else template
    activity_template = activity_template[:-1] if activity_template[-1] == os.sep else activity_template
    dir_template = os.path.join(misc.get_project_home(), '{session}', activity_template)
    return dir_template.format(**params).replace('//', '/').replace('//', '/')


class NameManager(object):
    """
    An object which keeps track of dataset names in a run list and makes sure
    unique names are generated
    """

    def __init__(self, database: dict = None):
        """
        :param database: dict of sample suffixes Entry keys are samples names
        and  value is the last integer suffix
        """
        self.database = {} if database is None else database

    def set_database(self, database: dict):
         """
        :param database: dict of sample suffixes Entry keys are samples names
        and  value is the last integer suffix
        """
         self.database = database

    def get_database(self):
        """
        Return a dictionary similar to what is expected for initialization
        """
        return self.database

    @staticmethod
    def split_name(root, name):
        m = re.match(rf'^({root})(-\d*)?$', name)
        if m:
            number = 0 if m.group(2) is None else abs(int(m.group(2)))
        else:
            number = 0
            root = name
        return root, number

    def fix(self, sample, *names):
        last = self.database.get(sample, -1)
        fixed_names = []
        for name in names:
            root, number = self.split_name(sample, name)
            if root == sample:
                if last < 0:
                    last += 1
                    fixed_names.append(root)
                elif number > last:
                    last = number
                    fixed_names.append(f'{sample}-{last}')
                else:
                    last += 1
                    fixed_names.append(f'{sample}-{last}')
            else:
                fixed_names.append(name)
        return fixed_names

    def get(self, sample):
        last = self.database.get(sample)
        if last is None:
            return sample
        else:
            return f'{sample}-{last+1}'

    def update(self, sample, name):
        root, number = self.split_name(sample, name)
        last = self.database.get('sample')
        if sample == root:
            if last in [None, 0]:
                self.database[sample] = number
            elif number > last:
                self.database[sample] = number


def summarize_list(values):
    """
    Takes a list of integers such as [1,2,3,4,6,7,8] and summarises it as a string "1-4,6-8"
    
    :param values: 
    :return: string
    """

    values = numpy.array(values)
    values.sort()
    return ','.join(
        f'{chunk[0]}-{chunk[-1]}'
        for chunk in numpy.split(values, numpy.where(numpy.diff(values) > 1)[0] + 1)
        if len(chunk)
    )


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
    screening runs, the defined range in the ScreeningRange dictionary.
    :param run: Run parameters (dict)
    :return: a floating point angle in degrees
    """
    if run.get('strategy') in [StrategyType.SCREEN_1, StrategyType.SCREEN_2, StrategyType.SCREEN_3, StrategyType.SCREEN_4]:
        return ScreeningRange.get(run['strategy'], run.get('range', 180.))
    else:
        return run['range']


def calc_num_frames(strategy: StrategyType, delta: float, angle_range: float, skip: str = '') -> int:
    """
    Count the number of frames in a dataset

    :param strategy: run strategy
    :param delta: delta angle
    :param angle_range: angle range
    :param skip: frames to skip
    """

    if strategy in [StrategyType.SCREEN_1, StrategyType.SCREEN_2, StrategyType.SCREEN_3, StrategyType.SCREEN_4]:
        total_range = ScreeningRange.get(strategy, angle_range)
    else:
        total_range = angle_range

    return max(1, int(total_range / delta)) - count_frameset(skip)


def count_frames(run):
    strategy = run.get('strategy', 0)
    angle_range = run.get('range', 1)
    delta = run.get('delta', 1)
    return calc_num_frames(strategy, delta, angle_range, run.get('skip', ''))


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


def dataset_from_reference(reference_file):
    """
    Given a reference file and directory, read the header and dataset information for the dataset on disk

    :param reference_file: representative file from the dataset
    :return: dictionary. Expected fields are
        'start_time':  start time for the dataset
        'frames':  A frame list string, eg '1-5,8-10' or '1'
    """
    dset = read_image(reference_file)
    return {
        'frames': summarize_list(dset.series),
        'num_frames': dset.size
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


def count_pair(pair):
    if pair == '':
        return 0
    elif not '-' in pair:
        return 1
    else:
        lo, hi = pair.split('-')
        return int(hi) - int(lo) + 1


def count_frameset(frame_set):
    return sum(
        count_pair(pair)
        for pair in frame_set.split(',')
    )


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
            'name': misc.slugify(params['name']),
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
        points = numpy.array([start] + [None] * steps)
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
    if run.get('vector_size') and run['vector_size'] > 1 and run.get('p1') is not None:
        vector_slice = total // run['vector_size']
    else:
        vector_slice = total

    slice_ = min(vector_slice, run.get('wedge', 180), total)

    # determine start point,  end point and list of frames for each wedge
    num_wedges = int(total / slice_)
    positions = wedge_points(run.get('p0'), run.get('p1'), num_wedges)
    wedge_frames = int(slice_ / delta)
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
            "original_name": run['name'],
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
    Given a data run, generate sequences of wedges to be interleaved. Typically, the sequences
    will contain a single wedge but when inverse beam is used, pairs are generated each time

    :param run: run parameters
    :param distinct:  whether to use distinct dataset names for each wedge. If True, wedge names
        will be suffixed with upper case letters to distinguish them from other wedges. Default is False
    """

    def __init__(self, run: dict, distinct: bool = False):
        self.details = run
        self.sample = run.get('sample', {})
        self.dispensed = defaultdict(list)

        # generate main wedges
        self.wedges = make_wedges(self.details)
        self.num_wedges = len(self.wedges)
        self.pos = 0    # position in wedge list

        self.distinct = distinct and self.num_wedges > 1 and not self.details.get('inverse')

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

    def get_details(self):
        # """
        # Yield a dictionary of details for each uniquely named wedge.
        # """

        for original_name, wedges in self.dispensed.items():
            details = copy.deepcopy(self.details)
            sub_wedges = [w['name'] for w in wedges]
            details.update(combine=sub_wedges)
            yield details

    def fetch(self):
        """
        Produce collections of one or more wedges
        """
        if self.pos >= self.num_wedges:
            return ()

        wedge = self.wedges[self.pos]
        self.pending = wedge['weight']

        if self.distinct:
            name_suffix = chr(ord('A') + self.pos)
            wedge['name'] = f"{wedge['original_name']}-{name_suffix}"
            wedge['first'] = 1  # distinct wedges all start from frame 1 because they will be treated as
                                # unique datasets rather than frames from the same set.
        self.pos += 1

        # prepare inverse beam
        if wedge['inverse']:
            inv_wedge = copy.deepcopy(wedge)
            inv_wedge['first'] = 1
            inv_wedge['start'] += 180.
            self.factor = 2

            # for inverse beam treat as separate datasets with different original names
            wedge['original_name'] = wedge['name'] = f"{wedge['original_name']}_1"
            inv_wedge['original_name'] = inv_wedge['name'] = f"{wedge['original_name']}_2"

            self.dispensed[wedge['original_name']].append(wedge)
            self.dispensed[inv_wedge['original_name']].append(inv_wedge)
            return wedge, inv_wedge,
        else:
            self.factor = 1
            self.dispensed[wedge['original_name']].append(wedge)
            return wedge,


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


def calculate_skip(strategy, total_range, delta, first):
    if strategy in [StrategyType.SCREEN_1, StrategyType.SCREEN_2, StrategyType.SCREEN_3, StrategyType.SCREEN_4]:
        return skips(
            wedge=total_range,
            delta=delta,
            first=first,
            start_angles=ScreeningAngles[strategy],
            range_end=ScreeningRange[strategy]
        )
    else:
        return ''


def skips(wedge, delta, first=1, start_angles=(0,), range_end=360):
    """
    Calculate the skip ranges based on

    :param wedge: angle range for each wedge
    :param delta: angle per frame
    :param first: first frame index
    :param start_angles: tuple of start_angles
    :param range_end:  End of range
    :return: string representation of frame number ranges to skip
    """
    end_angles = numpy.array(start_angles)
    start_angles = end_angles + wedge
    end_angles[:-1] = end_angles[1:]
    end_angles[-1] = range_end
    starts = first + (start_angles / delta).astype(int)
    ends = first + (end_angles / delta).astype(int) - 1
    return ','.join((f'{lo}-{hi}' for lo, hi in zip(starts, ends)))
