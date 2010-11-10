import os
import sys
import math, time
#import gtk
import gobject

if sys.version_info[:2] == (2,5):
    import uuid
else:
    from bcm.utils import uuid # for 2.3, 2.4

    
def get_short_uuid():
    return str(uuid.uuid1()).split('-')[0]

    
#def gtk_idle(sleep=None):
#    while gtk.events_pending():
#        gtk.main_iteration()

class SignalWatcher(object):
    def __init__(self):
        self.activated = False
        self.data = None
        
    def __call__(self, obj, *args):
        self.activated = True
        self.data = args
        
def wait_for_signal(obj, signal, timeout=10):
    sw = SignalWatcher()
    id = obj.connect(signal, sw)
    while not sw.activated and timeout > 0:
        time.sleep(0.05)
        timeout -= 0.05
    gobject.source_remove(id)
    return sw.data
    
def all(iterable):
    for element in iterable:
        if not element:
            return False
    return True
    

def generate_run_list(run, show_number=True):
    run_list = []
    index = 0
    offsets = [0.0,]
    if run.get('inverse_beam', False):
        offsets.append(180.0)
    wedge = min(run.get('wedge', 360.0), run['total_angle'])
    wedge_size = int(wedge // run['delta_angle'])
    total_size = run['num_frames']
    passes = int (round(0.5 + (run['total_angle'] - run['delta_angle']) / wedge)) 
    remaining_frames = total_size
    current_slice = wedge_size
    for i in range(passes):
        if current_slice > remaining_frames:
            current_slice = remaining_frames
        for (energy, energy_label) in zip(run['energy'], run['energy_label']):
            if len(run['energy']) > 1:
                energy_tag = "_%s" % energy_label
            else:
                energy_tag = ""
            for offset in offsets:
                for j in range(current_slice):
                    angle = run['start_angle'] + (j * run['delta_angle']) + (i * wedge) + offset
                    frame_number = i * wedge_size + j + int(offset / run['delta_angle']) + run['first_frame']
                    if show_number:
                        frame_name = "%s_%d%s_%03d" % (run['name'], run.get('number',1), energy_tag, frame_number)
                    else:
                        frame_name = "%s%s_%03d" % (run['name'], energy_tag, frame_number)
                    file_name = "%s.img" % (frame_name)
                    list_item = {
                        'index': index,
                        'saved': False,
                        'frame_number': int(frame_number),
                        'run_number': run.get('number', 1),
                        'frame_name': frame_name,
                        'file_name': file_name,
                        'start_angle': angle,
                        'delta_angle': run['delta_angle'],
                        'exposure_time': run['exposure_time'],
                        'energy': energy,
                        'distance': run['distance'],
                        'name': run['name'],
                        'two_theta': run.get('two_theta', 0.0),
                        'directory': run['directory']
                    }
                    run_list.append(list_item)
                    index += 1
        remaining_frames -= current_slice
    return run_list

