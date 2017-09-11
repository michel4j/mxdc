import copy
import fnmatch
import glob
import itertools
import os
import re
from collections import defaultdict
from datetime import date
import numpy
from mxdc.libs.imageio import read_header
from mxdc.utils import config, misc


FRAME_NUMBER_DIGITS = 4
OUTLIER_DEVIATION = 50


def update_for_sample(info, sample=None):
    # Add directory and related auxillary information to dictionary
    # provides values for {session} {sample}, {group}, {container}, {port}, {date}, {activity}

    sample = {} if not sample else sample
    params = copy.deepcopy(info)

    params.update({
        'session': config.get_session(),
        'sample': sample.get('name', 'unknown'),
        'group': misc.slugify(sample.get('group', '')),
        'container': misc.slugify(sample.get('container', '')),
        'port': sample.get('port', ''),
        'date': date.today().strftime('%Y%m%d'),
        'activity': params.get('activity', 'unknown'),
        'sample_id': sample.get('id'),
    })

    dir_template = '{}/{}'.format(os.environ['HOME'], config.settings.get_string('directory-template'))
    params['directory'] = dir_template.format(**params).replace('//', '/')
    return params


def fix_name(name, names, index=0):
    test_name = name if not index else '{}{}'.format(name, index)
    if not test_name in names:
        return test_name
    else:
        return fix_name(name, names, index=index+1)


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


def generate_frame_names(run):
    if not 'frame_sets' in run:
        run = add_framsets(run)
    template = '{}_{}'.format(run['name'], '{{:0{}d}}'.format(FRAME_NUMBER_DIGITS))
    return [
        template.format(index) for frameset in run['frame_sets'] for index, angle in frameset
    ]


class FrameChecker(object):
    def __init__(self, ext, detect_bad=False):
        self.ext = ext
        self.detect_bad = detect_bad

    def __call__(self, frame):
        frame_name = frame['frame_name']
        filename = "{}/{}.{}".format(frame['directory'], frame_name, self.ext)
        if os.path.exists(filename):
            if self.detect_bad:
                header = read_header(filename, full=True)
                value = header.get('average_intensity')
            else:
                value = 10
            return frame['dataset'], frame['first'], True, value
        return frame['dataset'], frame['first'], False, 0


def check_frame_list(frames, ext='img', detect_bad=False):
    intensities = defaultdict(list)
    check_frame = FrameChecker(ext, detect_bad)
    # pool = Pool(cpu_count())
    results = map(check_frame, frames)
    existing_frames = defaultdict(list)
    for dataset, frame_number, exists, value in results:
        if exists:
            intensities[dataset].append((frame_number, value))
            existing_frames[dataset].append(frame_number)
    existing = {
        k: summarize_list(v)
        for k, v in existing_frames.items()
    }
    bad_frames = {}
    if detect_bad:
        for dataset, values in intensities.items():
            frame_info = numpy.array(values)
            data = frame_info[:, 1]
            devs = numpy.abs(data - numpy.median(data))
            mdev = numpy.median(devs)
            s = devs / mdev if mdev else 0.0
            bad_frames['dataset'] = frame_info[s > OUTLIER_DEVIATION]
    bad = {
        k: summarize_list(v)
        for k, v in bad_frames.items()
    }
    return existing, bad


def generate_collection_list(run, frame_set):
    collection_list = []

    # generate frame info
    first_frame, start_angle = frame_set[0]
    data_set = {
        'uuid': run.get('uuid'),
        'dataset': run['name'],
        'name': run['name'],
        'frame_template': '{}_{}'.format(run['name'], '{{:0{}d}}'.format(FRAME_NUMBER_DIGITS)),
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
    }
    collection_list.append(data_set)
    return collection_list


def generate_frame_sets(run, show_number=True):
    frame_sets = []

    # initialize general parameters
    delta_angle = run.get('delta', 1.0)
    total_angle = run.get('range', 180.0)
    first_frame = run.get('first', 1)
    start_angle = run.get('start', 0.0)
    wedge = run.get('wedge', 360.0)

    # make sure wedge is good
    if wedge < total_angle:
        wedge = delta_angle * round(wedge / delta_angle)

    skip = run.get('skip', '')

    # generate list of frames to exclude from skip
    excluded_frames = []
    for w in skip.split(','):
        if w:
            try:
                v = map(int, w.split('-'))
                if len(v) == 2:
                    excluded_frames.extend(range(v[0], v[1] + 1))
                elif len(v) == 1:
                    excluded_frames.extend(v)
            except:
                pass

    n_wedge = int(round(wedge / delta_angle))  # number of frames in a wedge

    # inverse beam
    if run.get('inverse_beam', False):
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


class Chunker(object):
    """Produce lists of framesets for specified wedge at a time until consumed"""

    def __init__(self, dataset):
        self.dataset = dataset
        self.wedge = dataset['wedge']
        self.framesets = dataset['frame_sets']
        self.end = dataset['start'] + self.wedge

    def has_items(self):
        return bool(self.framesets)

    def fetch(self):
        stride = []
        for i, frameset in enumerate(self.framesets):
            if frameset[0][1] < self.end:
                stride.append(frameset)
                self.framesets = self.framesets[1:]
            else:
                self.end = frameset[0][1] + self.wedge
                break
        return stride


def generate_wedges(runs):
    wedges = []
    datasets = [add_framsets(r) for r in runs]
    chunkers = [Chunker(d) for d in datasets]
    num_sets = len(datasets)
    items_exist = any(ch.has_items() for ch in chunkers)
    pos = 0
    while items_exist:
        chunk = chunkers[pos].fetch()
        dataset = datasets[pos]
        for frameset in chunk:
            wedges.extend(generate_collection_list(dataset, frameset))
        items_exist = any(ch.has_items() for ch in chunkers)
        pos = (pos + 1) % num_sets

    return datasets, wedges


def _all_files(root, patterns='*'):
    """ 
    Return a list of all the files in a directory matching the pattern
    
    """
    patterns = patterns.split(';')
    path, subdirs, files = os.walk(root).next()
    sfiles = []
    for name in files:
        for pattern in patterns:
            if fnmatch.fnmatch(name, pattern):
                sfiles.append(name)
    sfiles.sort()
    return sfiles


def get_disk_frameset(directory, file_glob):
    # Given a glob and pattern, determine the collected frame set and number of frames based on images on disk

    file_pattern = file_glob.replace('*', '(\d{{{}}})'.format(FRAME_NUMBER_DIGITS))
    text = ' '.join(_all_files(directory, file_glob))
    full_set = map(int, re.findall(file_pattern, text))

    return summarize_list(full_set), len(full_set)


def get_disk_dataset(directory, name):
    # Given a name and directory, determine the collected frames based on images on disk
    file_pattern = r'^({}/{}_\d{{3,}}\.[^.]+)$'.format(directory, name)
    file_glob = os.path.join(directory, '{}_*.*'.format(name))
    text = '\n'.join(glob.glob(file_glob))
    patt = re.compile(file_pattern, re.MULTILINE)
    return sorted(patt.findall(text))


def frameset_to_list(frame_set):
    frame_numbers = []
    ranges = filter(None, frame_set.split(','))
    wlist = [map(int, filter(None, w.split('-'))) for w in ranges]
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

def generate_grid_frames(grid, params):
    pass