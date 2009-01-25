import os
import math, time
import gtk

    
def read_periodic_table():
    filename = os.environ['BCM_DATA_PATH'] + '/periodic_table.dat'
    data_file = open(filename)
    table_data = {}
    data = data_file.readlines()
    data_file.close()
    keys = data[0].split()
    for line in data[1:] :
        vals = line.split()
        table_data[vals[1]] = {}
        for (key,val) in zip(keys,vals):
            table_data[vals[1]][key] = val
    return table_data
   
def gtk_idle(sleep=None):
    while gtk.events_pending():
        gtk.main_iteration()


def generate_run_list(run, show_number=False):
    run_list = []
    index = 0
    offsets = run['inverse_beam'] and [0, 180] or [0,]
    
    angle_range = run['angle_range']
    wedge = run['wedge'] < angle_range and run['wedge'] or angle_range
    wedge_size = int( (wedge) / run['delta'])
    total_size = run['num_frames']
    passes = int ( round( 0.5 + (angle_range-run['delta']) / wedge) ) # take the roof (round_up) of the number
    remaining_frames = total_size
    current_slice = wedge_size
    for i in range(passes):
        if current_slice > remaining_frames:
            current_slice = remaining_frames
        for (energy,energy_label) in zip(run['energy'],run['energy_label']):
            if len(run['energy']) > 1:
                energy_tag = "_%s" % energy_label
            else:
                energy_tag = ""
            for offset in offsets:                        
                for j in range(current_slice):
                    angle = run['start_angle'] + (j * run['delta']) + (i * wedge) + offset
                    frame_number =  i * wedge_size + j + int(offset/run['delta']) + run['start_frame']
                    if show_number:
                        frame_name = "%s_%d%s_%03d" % (run['prefix'], run['number'], energy_tag, frame_number)
                    else:
                        frame_name = "%s%s_%03d" % (run['prefix'], energy_tag, frame_number)
                    file_name = "%s.img" % (frame_name)
                    list_item = {
                        'index': index,
                        'saved': False, 
                        'frame_number': frame_number,
                        'run_number': run['number'], 
                        'frame_name': frame_name, 
                        'file_name': file_name,
                        'start_angle': angle,
                        'delta': run['delta'],
                        'time': run['time'],
                        'energy': energy,
                        'distance': run['distance'],
                        'prefix': run['prefix'],
                        'two_theta': run['two_theta'],
                        'directory': run['directory']
                    }
                    run_list.append(list_item)
                    index += 1
        remaining_frames -= current_slice
    return run_list

