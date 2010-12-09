'''
Created on Nov 10, 2010

@author: michel
'''
import os
    
FULL_PARAMETERS = {
    'name': 'test',
    'directory': os.environ['HOME'],
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
                
            param['frame_sets'] = generate_frame_sets(param)
            param['two_theta'] = run_data.get('two_theta', 0.0)
            runs.append(param)
    else:
        param = run_data
        param['energy'] = e_values
        param['frame_sets'] = generate_frame_sets(param)
        runs.append(param)
        
    return runs
            
def summarize_sets(run_data):
    sum_list = []
    
    for frame_set in run_data['frame_sets']:
        if len(frame_set) < 2:
            if len(frame_set) == 1:
                sum_list.append('%d' % (frame_set[0][0]))                 
            continue
        st = 0            
        en = st + 1
        
        while en < len(frame_set):
            if en + 1 < len(frame_set):
                en += 1
                if frame_set[en][0] - frame_set[en-1][0] > 1:
                    sum_list.append('%d-%d' % (frame_set[st][0], frame_set[en-1][0]))                
                    st = en
                    en = st + 1
            else:
                sum_list.append('%d-%d' % (frame_set[st][0], frame_set[en][0]))
                break
    return ','.join(sum_list)
    


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
    return runs, run_list     
        
