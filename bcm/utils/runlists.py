'''
Created on Nov 10, 2010

@author: michel
'''
import os
import fnmatch
import re

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
    'energy_label': ['peak','infl','remo'],
    'number': 1,
    'two_theta': 0.0,
    'jump': 0.0,
}

def prepare_run(run_data):
    runs = []
    run_data = run_data.copy()
    e_values = run_data.pop('energy')
    e_names = run_data.pop('energy_label')
    if isinstance(e_values, list):
        energies = zip(e_values, e_names)
        for e_v, e_n in energies:
            param = run_data.copy()
            param['energy'] = e_v
            if len(e_values) > 1:
                param['name'] = '%s_%s' % (param['name'], e_n)                
            param['two_theta'] = run_data.get('two_theta', 0.0)
            param['frame_sets'] = generate_frame_sets(param)
            runs.append(param)
    else:
        param = run_data
        param['energy'] = e_values
        param['frame_sets'] = generate_frame_sets(param)
        runs.append(param)
    
        
    return runs
            

def _summarize_frame_set(full_set):
    # takes a list of integers such as [1,2,3,4,6,7,8]
    # and reduces it to the string "1-4,6-8"
    sum_list = []

    full_set.sort()
    
    first = True
    for n in full_set:
        if first:
            st = n
            en = n
            first = False
            continue
        if n == full_set[-1]: #last item
            en = n
            if st == en:
                sum_list.append('%d' % (st,))
            else:
                sum_list.append('%d-%d' % (st, en))
        elif n - en > 1: # an edge 
            if st == en:
                sum_list.append('%d' % (st,))
            else:
                sum_list.append('%d-%d' % (st, en))
            st = n
            en = n
        else:
            en += 1
               
    return ','.join(sum_list)
    
def summarize_sets(run_data):
    
    full_set = []
    for frame_set in run_data['frame_sets']:
        full_set.extend(frame_set)
    full_set = [n for n,_ in full_set]
    return _summarize_frame_set(full_set)
    
def generate_frame_list(run, frame_set):
    frame_list = []
    
    # initialize general parameters
    delta_angle = run.get('delta_angle', 1.0)
    
    for frame_number, angle in frame_set:               
        # generate frame info
        frame_name = "%s_%03d" % (run['name'], frame_number)
        file_name = "%s.img" % (frame_name)
        frame = {
            'saved': False,
            'frame_number': frame_number,
            'number': run.get('number',1),
            'frame_name': frame_name,
            'file_name': file_name,
            'start_angle': angle,
            'delta_angle': delta_angle,
            'exposure_time': run.get('exposure_time', 1.0),
            'energy': run.get('energy', 12.658),
            'distance': run['distance'],
            'name': run['name'],
            'two_theta': run.get('two_theta', 0.0),
            'directory': run['directory'],
        }
        frame_list.append(frame)           

    return frame_list


def generate_frame_sets(run, show_number=True):
    frame_sets = []
    
    # initialize general parameters
    delta_angle = run.get('delta_angle', 1.0)
    total_angle = run.get('total_angle', 180.0)
    first_frame = run.get('first_frame', 1)
    start_angle =  run.get('start_angle', 0.0)
    wedge = run.get('wedge', 360.0)
    # make sure wedge is good
    if wedge < total_angle:
        wedge = delta_angle * round(wedge/delta_angle)
    jump = run.get('jump', 0.0)
    skip = run.get('skip','')
    
    # generate list of frames to exclude from skip
    excluded_frames = []
    if skip != '':
        ws =  skip.split(',')
        for w in ws:
            try:
                v = map(int, w.split('-'))
                if len(v) == 2:
                    excluded_frames.extend(range(v[0],v[1]+1))
                elif len(v) == 1:
                    excluded_frames.extend(v)
            except:
                pass

    # jump must be greater than wedge to be meaningful
    if jump < wedge:
        jump = 0.0
        
    n_wedge = int(round(wedge/delta_angle))  # number of frames in a wedge
    
    #inverse beam
    if run.get('inverse_beam', False):
        offsets = [0.0, 180.0]
    else:
        offsets = [0.0,]
            
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
                
                frame_number = int(round(first_frame + (angle - start_angle)/delta_angle))
                if frame_number not in excluded_frames:
                    wedge_list.append((frame_number, angle))
        if len(wedge_list) > 0:
            frame_sets.append(wedge_list)
            
        if jump > 0.0:
            wedge_start += jump
        else:
            wedge_start += wedge
  
    return frame_sets

def generate_run_list(run_info_list):
    runs = []
    for r in run_info_list:
        runs.extend(prepare_run(r))

    run_list = []
    max_sets = 1   
    for run in runs:       
        max_sets = max(max_sets, len(run['frame_sets']))

    for i in range(max_sets):
        for run in runs:
            if i < len(run['frame_sets']):
                run_list.extend(generate_frame_list(run, run['frame_sets'][i]))
    return run_list     

def generate_data_and_list(run_info_list):
    runs = {}
    run_list = []
    max_sets = 1   
    for r in run_info_list:
        for run in prepare_run(r):
            runs[r['name']] = run
            max_sets = max(max_sets, len(run['frame_sets']))

    for i in range(max_sets):
        for run in runs.values():
            if i < len(run['frame_sets']):
                run_list.extend(generate_frame_list(run, run['frame_sets'][i]))
    return runs, run_list     
        
def _all_files(root, patterns='*'):
    """ 
    Return a list of all the files in a directory matching the pattern
    
    """
    patterns = patterns.split(';')
    path, subdirs, files = os.walk(root).next()
    sfiles = []
    for name in files:
        for pattern in patterns:
            if fnmatch.fnmatch(name,pattern):
                sfiles.append(name)
    sfiles.sort()
    return sfiles

def get_disk_frameset(run):
    # Given a run, determine the collected frame set and number of frames based on images on disk
    file_wcard = "%s_???.img" % (run['name'])
    file_pattern = '%s_(\d{3}).img' % (run['name'])
    filetxt = ' '.join(_all_files(run['directory'], file_wcard))
    full_set = map(int, re.findall(file_pattern, filetxt))
    
    return _summarize_frame_set(full_set), len(full_set)
    
    
    
    
    