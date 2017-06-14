'''
Created on Nov 10, 2010

@author: michel
'''
import os
import fnmatch
import re
from bcm.utils.science import exafs_targets, exafs_time_func
from bcm.utils import converter
from bcm.libs.imageio import read_header
from multiprocessing import Pool, cpu_count
import numpy
from collections import defaultdict, OrderedDict
import itertools
import glob

FULL_PARAMETERS = {
    'name': 'test',
    'directory': os.environ.get('HOME', '/tmp'),
    'distance': 250.0,
    'delta_angle': 1.0,
    'exposure_time': 1.0,
    'start_angle': 0.0,
    'total_angle': 8.0,
    'first_frame': 1,
    'inverse_beam': False,
    'wedge': 5.0,
    'energy': [12.658, 12.66, 12.67],
    'energy_label': ['peak', 'infl', 'remo'],
    'number': 1,
    'two_theta': 0.0,
    'attenuation': 0.0,
    'jump': 0.0,
}

FRAME_NUMBER_DIGITS = 4
OUTLIER_DEVIATION = 50


def prepare_run(run_data):
    runs = []
    run_data = run_data.copy()
    if run_data.get('dafs', False):
        e_list = run_data.pop('energy')
        e_values = list(
            exafs_targets(
                e_list[0], start=-0.1, edge=-0.005, exafs=0.006, kmax=8, pe_factor=10.0, e_step=0.001, k_step=0.2
            )
        )
        e_names = ["{:0.4f}".format(e) for e in e_values]
    else:
        e_list = run_data.pop('energy')
        e_values = e_list
        e_names = run_data.pop('energy_label')
    scat_d = None
    if 'scattering_factors' in run_data:
        scat_d = run_data.pop('scattering_factors')
    if not isinstance(scat_d, list):
        scat_d = len(e_names) * [None]
    if isinstance(e_values, list):
        energies = zip(e_values, e_names, scat_d)
        for e_v, e_n, e_s in energies:
            param = run_data.copy()

            # Variable Exposure Time for DAFS
            if param.get('dafs', False):
                delta_e = e_v - e_list[0]
                param['exposure_time'] = exafs_time_func(param['exposure_time'],
                                                         round(converter.energy_to_kspace(delta_e), 2))

            param['energy'] = e_v
            param['energy_label'] = e_n
            if e_s is not None:
                param['scattering_factors'] = e_s
            if len(e_values) > 1:
                param['name'] = '{}_{}'.format(param['name'], e_n)
            param['two_theta'] = run_data.get('two_theta', 0.0)
            param['frame_sets'] = generate_frame_sets(param)
            runs.append(param)
    else:
        param = run_data
        param['energy'] = e_values
        param['frame_sets'] = generate_frame_sets(param)
        runs.append(param)
    return runs


def summarize_frame_set(full_frame_set):
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


def determine_skip(frame_list):
    # takes a list of integers such as [1,2,3,4,7,8]
    # and reduces it to the string of skipped regions such as "5-6"

    complete_set = set(range(1, max(frame_list) + 1))
    frame_set = set(frame_list)
    full_set = list(complete_set.difference(frame_set))
    return summarize_frame_set(full_set)


def summarize_sets(run_data):
    full_set = []
    for frame_set in run_data['frame_sets']:
        full_set.extend(frame_set)
    full_set = [n for n, _ in full_set]
    return summarize_frame_set(full_set)


def generate_frame_list(wedge):
    frame_list = []

    # initialize general parameters
    for i in range(wedge['num_frames']):
        # generate frame info
        frame = {
            'dataset': wedge['dataset'],
            'file_prefix': wedge['file_prefix'],
            'saved': False,
            'start_frame': i + wedge['start_frame'],
            'frame_name': wedge['frame_template'].format(i + wedge['start_frame']),
            'start_angle': wedge['start_angle'] + i * wedge['delta_angle'],
            'delta_angle': wedge['delta_angle'],
            'exposure_time': wedge['exposure_time'],
            'energy': wedge['energy'],
            'distance': wedge['distance'],
            'two_theta': wedge.get('two_theta', 0.0),
            'attenuation': wedge.get('attenuation', 0.0),
            'directory': wedge['directory'],
            'dafs': wedge.get('dafs', False),
        }
        frame_list.append(frame)

    return frame_list


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
            return frame['file_prefix'], frame['start_frame'], True, value
        return frame['file_prefix'], frame['start_frame'], False, 0


def check_frame_list(frames, ext='img', detect_bad=False):
    intensities = defaultdict(list)
    check_frame = FrameChecker(ext, detect_bad)
    #pool = Pool(cpu_count())
    results = map(check_frame, frames)
    existing_frames = defaultdict(list)
    for dataset, frame_number, exists, value in results:
        if exists:
            intensities[dataset].append((frame_number, value))
            existing_frames[dataset].append(frame_number)
    existing = {
        k: summarize_frame_set(v)
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
        k: summarize_frame_set(v)
        for k, v in bad_frames.items()
    }
    return existing, bad


def generate_collection_list(run, frame_set):
    collection_list = []

    # generate frame info
    first_frame, start_angle = frame_set[0]
    data_set = {
        'dataset': run['name'],
        'file_prefix': run['name'],
        'frame_template': '{}_{}'.format(run['name'], '{{:0{}d}}'.format(FRAME_NUMBER_DIGITS)),
        'start_angle': start_angle,
        'start_frame': first_frame,
        'num_frames': len(frame_set),
        'delta_angle': run['delta_angle'],
        'exposure_time': run.get('exposure_time', 1.0),
        'energy': run.get('energy', 12.658),
        'distance': run['distance'],
        'two_theta': run.get('two_theta', 0.0),
        'attenuation': run.get('attenuation', 0.0),
        'directory': run['directory'],
        'dafs': run.get('dafs', False),
    }
    collection_list.append(data_set)
    return collection_list


def generate_frame_sets(run, show_number=True):
    frame_sets = []

    # initialize general parameters
    delta_angle = run.get('delta_angle', 1.0)
    total_angle = run.get('total_angle', 180.0)
    first_frame = run.get('first_frame', 1)
    start_angle = run.get('start_angle', 0.0)
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


def generate_run_list(run_info_list):
    datasets, wedges = generate_wedges(run_info_list)
    run_list = list(itertools.chain.from_iterable(generate_frame_list(wedge) for wedge in wedges))
    return run_list


def generate_wedges(run_info_list):
    datasets = []
    for r in run_info_list:
        datasets.extend(prepare_run(r))

    wedges = []
    max_sets = max([len(dataset['frame_sets']) for dataset in datasets])

    for i in range(max_sets):
        for dataset in datasets:
            if i < len(dataset['frame_sets']):
                wedges.extend(generate_collection_list(dataset, dataset['frame_sets'][i]))

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

    return summarize_frame_set(full_set), len(full_set)

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
    return summarize_frame_set(sequence)
