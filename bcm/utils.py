import os
import math, time
import gtk

# Physical Constats
h = 4.13566733e-15 # eV.s
c = 299792458e10   # A/s
S111_a_rt   = 5.4310209 # A at RT
S111_a_ln2  = 5.4297575 # A at LN2 

def energy_to_wavelength(energy): #Angstroms
	return (h*c)/(energy*1000.0)

def wavelength_to_energy(wavelength): #eV
	return (h*c)/(wavelength*1000.0)

def radians(angle):
    return math.pi * angle / 180.0

def degrees(angle):
    return 180 * angle / math.pi
    

def bragg_to_energy(bragg):
    d = S111_a_ln2 / math.sqrt(3.0)
    wavelength = 2.0 * d * math.sin( radians(bragg) )
    return wavelength_to_energy(wavelength)

def energy_to_bragg(energy):
    d = S111_a_ln2 / math.sqrt(3.0)
    bragg = math.asin( energy_to_wavelength(energy)/(2.0*d) )
    return degrees(bragg)

def dec_to_bin(x):
    return x and (dec_to_bin(x/2) + str(x%2)) or '0'
    
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

def dist_to_resol(*args, **kwargs):
	pixel_size = kwargs['pixel_size']
	detector_size = kwargs['detector_size']
	detector_distance = kwargs['detector_distance']
	energy = kwargs['energy']
	#two_theta = kwargs['two_theta']
	
	theta = 0.5 * math.atan( 0.5 * pixel_size * detector_size / detector_distance)
	#theta = theta+two_theta
	return 0.5 * energy_to_wavelength(energy) / math.sin(theta)
	
def resol_to_dist(*args, **kwargs):
	
	pixel_size = kwargs['pixel_size']
	detector_size = kwargs['detector_size']
	resolution = kwargs['resolution']
	energy = kwargs['energy']
	#two_theta = kwargs['two_theta']
	
	theta = math.asin(0.5 * energy_to_wavelength(energy) / resolution)
	#theta = max(0, (theta-two_theta))
	return 0.5 * pixel_size * detector_size / math.tan( 2 * theta )

def generate_run_list(run_data):
    run_list = []
    run_keys = run_data.keys()
    index = 0
    for pos in run_keys:
        run = run_data[pos]
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
                        if len(run_keys) > 1:
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

