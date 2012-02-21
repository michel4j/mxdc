from bcm.beamline.interfaces import IBeamline
from bcm.engine import centering, snapshot
from bcm.engine.interfaces import IDataCollector
from bcm.protocol import ca
from bcm.utils.converter import energy_to_wavelength, dist_to_resol
from bcm.utils.log import get_module_logger
from bcm.utils.misc import get_project_name
from bcm.utils import json, runlists

from twisted.python.components import globalRegistry
from zope.interface import implements

    

import gobject
import os
import threading
import time
import pwd


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


DEFAULT_PARAMETERS = {
    'name': 'test',
    'directory': '/tmp',
    'distance': 250.0,
    'delta_angle': 1.0,
    'exposure_time': 1.0,
    'start_angle': 0,
    'total_angle': 1.0,
    'first_frame': 1,
    'num_frames': 1,
    'inverse_beam': False,
    'wedge': 360.0,
    'energy': [ 12.658 ],
    'energy_label': ['E0'],
    'number': 1,
    'two_theta': 0.0,
    'jump': 0.0
}

class DataCollector(gobject.GObject):
    implements(IDataCollector)
    __gsignals__ = {}
    __gsignals__['new-image'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_INT, gobject.TYPE_STRING))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT, gobject.TYPE_INT, gobject.TYPE_INT))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN, gobject.TYPE_PYOBJECT))
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    
    STATE_PENDING, STATE_RUNNING, STATE_DONE, STATE_SKIPPED = range(4)
    def __init__(self):
        gobject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.skip_existing = False
        self.run_list = []
        self.runs = []
        self.results = {}        
        self._last_initialized = 0
        
            
    def configure(self, run_data, skip_existing=True):
        #associate beamline devices
        
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
            _logger.warning('No registered beamline found.')
            raise
        try:
            self.beamline.storage_ring.disconnect(self.beam_connect)
        except:
            pass
        self.beam_connect = self.beamline.storage_ring.connect('beam', self._on_beam_change)
         
        self.collect_parameters = {}
        self.collect_parameters['skip_existing'] = skip_existing

        if not isinstance(run_data, list):
            self.collect_parameters['runs'] = [run_data]
        else:
            self.collect_parameters['runs'] = run_data[:]
        data_sets, run_list = runlists.generate_data_and_list(self.collect_parameters['runs'])
        self.collect_parameters['data_sets'] = data_sets
        self.collect_parameters['run_list'] = run_list
        
        for run in self.collect_parameters['runs']:        
            self.beamline.image_server.setup_folder(run['directory'])
        for frame in self.collect_parameters['run_list']:
            if os.path.exists(os.path.join(frame['directory'], frame['file_name'])):
                frame['saved'] = True
        self.collect_parameters['user_properties'] = (pwd.getpwuid(os.geteuid())[0]  , os.geteuid(), os.getegid())
                
        return

    def _on_beam_change(self, obj, beam_available):
        if not beam_available and (not self.paused) and (not self.stopped):
            self.pause()
            pause_dict = { 'type': Screener.PAUSE_BEAM, 
                           'collector': True,
                           'position': self.pos - 1 }
            gobject.idle_add(self.emit, 'paused', True, pause_dict)
        return True

    def _notify_progress(self, status):
        # Notify progress
        fraction = float(self.pos) / self.total_items
        gobject.idle_add(self.emit, 'progress', fraction, self.pos, status)                
    
    def get_dataset_info(self, data_list):
        results = []
        for d in data_list[:]:
            data = d.copy()
            
            if len(data['frame_sets']) == 0:
                continue
            if len(data['frame_sets'][0]) < 4:
                continue
            # Remove frames from the list that were not collected
            #FIXME
            data['id'] = None
            data['frame_sets'], data['num_frames'] = runlists.get_disk_frameset(data)
            data['wavelength'] = energy_to_wavelength(data['energy'])
            data['resolution'] = dist_to_resol(data['distance'], 
                                self.beamline.detector.resolution,
                                self.beamline.detector.size,
                                data['energy'])
            data['beamline_name'] = self.beamline.name
            data['detector_size'] = self.beamline.detector.size
            data['pixel_size'] = self.beamline.detector.resolution
            data['beam_x'],  data['beam_y'] = self.beamline.detector.get_origin()
            data['detector'] = self.beamline.detector.detector_type
            filename = os.path.join(data['directory'], '%s.SUMMARY' % data['name'])
            if os.path.exists(filename):
                old_data = json.load(file(filename))
                if old_data.get('id', None) is not None:
                    data['id'] = old_data['id']
                if data.get('crystal_id') is None:
                    data['crystal_id'] = old_data.get('crystal_id', None)
                if data.get('experiment_id') is None:
                    data['experiment_id'] = old_data.get('experiment_id', None)
            
            fh = open(filename,'w')
            json.dump(data, fh, indent=4)
            fh.close()
            results.append(data)
        return results
            
    def get_state(self):
        state = {
            'paused': self.paused,
            'stopped': self.stopped,
            'skip_collected': self.skip_collected,
            'run_list': self.run_list,
            'pos': self.pos }
        return state
    
    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Data Collector')
        worker_thread.start()
    
    def run(self):
        if self.beamline is None:
            _logger.error('No Beamline found. Aborting data collection.')
            return False
        ca.threads_init()
        self.beamline.lock.acquire()
        # Obtain configured parameters
        self.skip_existing = self.collect_parameters['skip_existing']
        self.runs = self.collect_parameters['runs']
        self.data_sets = self.collect_parameters['data_sets']
        self.run_list = self.collect_parameters['run_list']
        self._user_properties = self.collect_parameters['user_properties']
        
        
        self.beamline.image_server.set_user(*self._user_properties)
        self.paused = False
        self.stopped = False           
        # Take snapshots before beginning collection
        if len(self.run_list) >= 4:
            prefix = '%s-pic' % (self.run_list[0]['name'])
            a1 = self.run_list[0]['start_angle']
            a2 = a1 < 270 and a1 + 90 or a1 - 270
            if not os.path.exists(os.path.join(self.run_list[0]['directory'], '%s_%0.1f.png' % (prefix, a1))):
                _logger.info('Taking snapshots of crystal at %0.1f and %0.1f' %(a1, a2))
                snapshot.take_sample_snapshots(prefix, os.path.join(self.run_list[0]['directory']), [a2, a1], decorate=True)
        self.beamline.goniometer.set_mode('COLLECT', wait=True) # move goniometer to collect mode
        gobject.idle_add(self.emit, 'started')
        _current_attenuation = self.beamline.attenuator.get()
        try:
                   
            self.beamline.exposure_shutter.close()

            self.pos = 0
            header = {}
            pause_dict = {}
            _first = True
            self.total_items = len(self.run_list)
            while self.pos < self.total_items :
                if self.paused:
                    gobject.idle_add(self.emit, 'paused', True, pause_dict)
                    while self.paused and not self.stopped:
                        time.sleep(0.05)
                    self.beamline.goniometer.set_mode('COLLECT', wait=True)   
                    gobject.idle_add(self.emit, 'paused', False, {})
                if self.stopped:
                    gobject.idle_add(self.emit, 'stopped')
                    break
    
                frame = self.run_list[self.pos]   
                if frame['saved']:
                    if self.skip_existing:
                        _logger.info('Skipping %s' % frame['file_name'])
                        self._notify_progress(self.STATE_SKIPPED)
                        self.pos += 1
                        continue
                    else:
                        _logger.info('Overwriting %s' % frame['file_name'])
                        os.remove("%s/%s" % (frame['directory'], frame['file_name']))
                
                self._notify_progress(self.STATE_RUNNING)
                _cur_energy = self.beamline.energy.get_position()
                self.beamline.energy.move_to(frame['energy'], wait=True)
                
                # if energy changes by more than 5 eV, Optimize
                if  abs(frame['energy'] - _cur_energy) >= 0.005:                                    
                    self.beamline.mostab.start()
                    self.beamline.mostab.wait()

                self.beamline.diffractometer.distance.move_to(frame['distance'], wait=True)
                self.beamline.attenuator.set(frame['attenuation'], wait=True)               
                
                # Prepare image header
                header['delta_angle'] = frame['delta_angle']
                header['filename'] = frame['file_name']
                dir_parts = frame['directory'].split('/')
                if dir_parts[1] == 'users':
                    dir_parts[1] = 'data'
                    header['directory'] = '/'.join(dir_parts)
                else:
                    header['directory'] = frame['directory']
                header['distance'] = frame['distance'] 
                header['exposure_time'] = frame['exposure_time']
                header['frame_number'] = frame['frame_number']
                header['wavelength'] = energy_to_wavelength(frame['energy'])
                header['energy'] = frame['energy']
                header['name'] = frame['name']
                header['start_angle'] = frame['start_angle']
                header['comments'] = 'BEAMLINE: %s %s' % ('CLS', self.beamline.name)
                
                #prepare goniometer for scan   
                self.beamline.goniometer.configure(time=frame['exposure_time'],
                                                   delta=frame['delta_angle'],
                                                   angle=frame['start_angle'])

                self.beamline.detector.start(first=_first)
                self.beamline.detector.set_parameters(header)
                self.beamline.goniometer.scan()
                self.beamline.detector.save()
                
                #frame['saved'] = True
                _first = False
                    
                _logger.info("Image Collected: %s" % (frame['file_name']))
                gobject.idle_add(self.emit, 'new-image', self.pos, "%s/%s" % (frame['directory'], frame['file_name']))
                
                self._notify_progress(self.STATE_DONE)
                self.pos = self.pos + 1
            
            # Wait for Last image to be transfered
            time.sleep(5.0)
            
            self.results = self.get_dataset_info(self.data_sets.values())
            if not self.stopped:
                gobject.idle_add(self.emit, 'done')
            self.stopped = True
        finally:
            self.beamline.exposure_shutter.close()
            # Restore attenuation
            self.beamline.attenuator.set(_current_attenuation)
            self.beamline.lock.release()
        return self.results

    def set_position(self, pos):
        for i, frame in enumerate(self.run_list):
            if i < pos and len(self.run_list) > pos:
                frame['saved'] = True
            else:
                frame['saved'] = False
        self.pos = pos
        
    def pause(self):
        self.paused = True
        
    def resume(self):
        self.paused = False
    
    def stop(self):
        self.stopped = True
        
        
        
class Screener(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT, gobject.TYPE_INT, gobject.TYPE_INT))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN, gobject.TYPE_PYOBJECT))
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['sync'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN, gobject.TYPE_STRING))
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['analyse-request'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,))
    __gsignals__['new-datasets'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,))
   
    TASK_MOUNT, TASK_ALIGN, TASK_PAUSE, TASK_COLLECT, TASK_ANALYSE, TASK_DISMOUNT = range(6)
    TASK_STATE_PENDING, TASK_STATE_RUNNING, TASK_STATE_DONE, TASK_STATE_ERROR, TASK_STATE_SKIPPED = range(5)
    
    PAUSE_TASK, PAUSE_BEAM, PAUSE_ALIGN, PAUSE_MOUNT, PAUSE_UNRELIABLE = range(5)
      
    def __init__(self):
        gobject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.skip_collected = False
        self.data_collector = None
        self._collect_results = []
        self.last_pause = None
        
    def configure(self, run_list):
        #associate beamline devices
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)

        except:
            self.beamline = None
            _logger.warning('No registered beamline found.')
            raise
        try:  
            self.data_collector = globalRegistry.lookup([], IDataCollector, 'mxdc.screening')
        except:
            if self.data_collector is None:
                self.data_collector = DataCollector()
        try: 
            self.data_collector.disconnect(self.collect_connect)
        except: 
            pass
        self.collect_connect = self.data_collector.connect('paused', self._on_collector_pause)
        self.run_list = run_list
        self.total_items = len(self.run_list)
        return
 
    def _on_collector_pause(self, obj, state, pause_dict):
        task = self.run_list[self.pos]
        if task.task_type == Screener.TASK_COLLECT and (not self.paused) and (not self.stopped) and ('collector' in pause_dict):
            self.paused = True
            gobject.idle_add(self.emit, 'paused', True, pause_dict)
        return True
    
    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Screener')
        worker_thread.start()
            
    def _notify_progress(self, status):
        # Notify progress
        fraction = float(self.pos) / self.total_items
        gobject.idle_add(self.emit, 'progress', fraction, self.pos, status)                
        
    def run(self):
        self.paused = False
        self.stopped = False
        if self.beamline is None:
            _logger.error('No Beamline found. Aborting Screening.')
            return
        ca.threads_init()
        #self.beamline.lock.acquire()
        gobject.idle_add(self.emit, 'started')
        try: 
            self.pos = 0
            pause_dict = {}

            while self.pos < len(self.run_list):
                task = self.run_list[self.pos]
                _logger.debug('TASK: "%s"' % str(task))

                # Making sure beam is available before trying to collect
                if (self.last_pause != Screener.PAUSE_BEAM) and task.task_type == Screener.TASK_COLLECT and not self.beamline.storage_ring.get_state()['beam'] and not self.paused:
                    self.pause()
                    pause_dict = { 'type': Screener.PAUSE_BEAM,
                                   'object': None }

                if self.stopped:
                    gobject.idle_add(self.emit, 'stopped')
                    break
                if self.paused:
                    gobject.idle_add(self.emit, 'paused', True, pause_dict)
                    self.last_pause = pause_dict.get('type', None)
                    pause_dict = {}
                    while self.paused and not self.stopped:
                        time.sleep(0.05)
                    gobject.idle_add(self.emit, 'paused', False, pause_dict)
                    continue
                
                # Perform the screening task here
                if task.task_type == Screener.TASK_PAUSE:
                    self._notify_progress(Screener.TASK_STATE_RUNNING)
                    self.pause()
                    pause_dict = {'type': Screener.PAUSE_TASK,
                                  'task': self.run_list[self.pos - 1].name,
                                  'sample': self.run_list[self.pos]['sample']['name'],
                                  'port': self.run_list[self.pos]['sample']['port'] }
                      
                elif task.task_type == Screener.TASK_MOUNT:
                    _logger.warn('TASK: Mount "%s"' % task['sample']['port'])
                    if self.beamline.automounter.is_mounted(task['sample']['port']):
                        # do nothing
                        self._notify_progress(Screener.TASK_STATE_SKIPPED)
                    elif self.beamline.automounter.is_mountable(task['sample']['port']):
                        self._notify_progress(Screener.TASK_STATE_RUNNING)
                        self.beamline.goniometer.set_mode('MOUNTING', wait=True)
                        self.beamline.cryojet.nozzle.open()
                        success = self.beamline.automounter.mount(task['sample']['port'], wait=True)
                        self.beamline.cryojet.nozzle.close()
                        mounted_info = self.beamline.automounter.mounted_state
                        if not success or mounted_info is None:
                            self.pause()
                            self.stop()
                            pause_dict = {'type': Screener.PAUSE_MOUNT,
                                          'task': self.run_list[self.pos - 1].name,
                                          'sample': self.run_list[self.pos]['sample']['name'],
                                          'port': self.run_list[self.pos]['sample']['port'] }
                            self._notify_progress(Screener.TASK_STATE_ERROR)
                        else:
                            port, barcode = mounted_info
                            if port != self.run_list[self.pos]['sample']['port']:
                                gobject.idle_add(self.emit, 'sync', False, 'Port mismatch. Expected %s.' % self.run_list[self.pos]['sample']['port'])
                            elif barcode != self.run_list[self.pos]['sample']['barcode']:
                                gobject.idle_add(self.emit, 'sync', False, 'Barcode mismatch. Expected %s.' % self.run_list[self.pos]['sample']['barcode'])
                            else:
                                gobject.idle_add(self.emit, 'sync', True, '')
                            self.beamline.goniometer.set_mode('CENTERING', wait=True)
                            self._notify_progress(Screener.TASK_STATE_DONE)                        
                    else:
                        #"skip mounting"
                        _logger.warn('Skipping sample: "%s @ %s". Sample port is not mountable!' % (task['sample']['name'], task['sample']['port']))
                        self._notify_progress(Screener.TASK_STATE_SKIPPED)                        
                elif task.task_type == Screener.TASK_DISMOUNT:
                    _logger.warn('TASK: Dismounting Last Sample')
                    if self.beamline.automounter.is_mounted(): # only attempt if any sample is mounted
                        self._notify_progress(Screener.TASK_STATE_RUNNING)                        
                        self.beamline.goniometer.set_mode('MOUNTING', wait=True)
                        self.beamline.cryojet.nozzle.open()
                        success = self.beamline.automounter.dismount(wait=True)
                        self._notify_progress(Screener.TASK_STATE_DONE)      
                        
                                                                                            
                elif task.task_type == Screener.TASK_ALIGN:
                    _logger.warn('TASK: Align sample "%s"' % task['sample']['name'])
                    
                    if self.beamline.automounter.is_mounted(task['sample']['port']):
                        self._notify_progress(Screener.TASK_STATE_RUNNING)            

                        _out = centering.auto_center_loop()
                        if _out is None:
                            _logger.error('Error attempting auto loop centering "%s"' % task['sample']['name'])
                            pause_dict = {'type': Screener.PAUSE_ALIGN,
                                          'task': self.run_list[self.pos - 1].name,
                                          'sample': self.run_list[self.pos]['sample']['name'],
                                          'port': self.run_list[self.pos]['sample']['port'] }
                            self.pause()
                            self._notify_progress(Screener.TASK_STATE_ERROR)            
                        elif _out.get('RELIABILITY') < 70:
                            pause_dict = {'type': Screener.PAUSE_UNRELIABLE,
                                          'task': self.run_list[self.pos - 1].name,
                                          'sample': self.run_list[self.pos]['sample']['name'],
                                          'port': self.run_list[self.pos]['sample']['port'] }
                            self.pause()
                            self._notify_progress(Screener.TASK_STATE_ERROR)
                        else:
                            self._notify_progress(Screener.TASK_STATE_DONE)
                        directory = os.path.join(task['directory'], task['sample']['name'], 'test')
                        if not os.path.exists(directory):
                            os.makedirs(directory) # make sure directories exist
                        snapshot.take_sample_snapshots('snapshot', directory, [0, 90, 180], True)
                    else:
                        self._notify_progress(Screener.TASK_STATE_SKIPPED)
                        _logger.warn('Skipping task because given sample is not mounted')
                        
                elif task.task_type == Screener.TASK_COLLECT:
                    _logger.warn('TASK: Collect frames for "%s"' % task['sample']['name'])
                    
                    if self.beamline.automounter.is_mounted(task['sample']['port']):
                        self._notify_progress(Screener.TASK_STATE_RUNNING)
                        self.beamline.cryojet.nozzle.close()
                        sample = task['sample']
                        params = DEFAULT_PARAMETERS.copy()
                        params['name'] = "%s_test" % sample['name']
                        params['two_theta'] = self.beamline.two_theta.get_position()
                        params['crystal_id'] = sample.get('id', None)
                        params['experiment_id'] = sample.get('experiment_id', None)
                        params['directory'] = os.path.join(task['directory'], sample['name'], 'test')
                        params['energy'] = [self.beamline.energy.get_position()]
                        for k in ['distance', 'delta_angle', 'exposure_time', 'start_angle', 'total_angle', 'first_frame', 'skip']:
                            params[k] = task.options[k]
                        _logger.debug('Collecting frames for crystal `%s`, in directory `%s`.' % (params['name'], params['directory']))
                        if not os.path.exists(params['directory']):
                            os.makedirs(params['directory']) # make sure directories exist
                        self.data_collector.configure(params)
                        results = self.data_collector.run()
                        task.options['results'] = results
                        gobject.idle_add(self.emit, 'new-datasets', results)                       
                        self._notify_progress(Screener.TASK_STATE_DONE)
                    else:
                        self._notify_progress(Screener.TASK_STATE_SKIPPED)
                        _logger.warn('Skipping task because given sample is not mounted')
                        
                elif task.task_type == Screener.TASK_ANALYSE:
                    collect_task = task.options.get('collect_task')
                    if collect_task is not None:
                        collect_results = collect_task.options.get('results', [])
                        if len(collect_results) > 0:
                            frame_list = runlists.frameset_to_list(collect_results[0]['frame_sets'])
                            _first_frame = os.path.join(collect_results[0]['directory'],
                                                        "%s_%03d.img" % (collect_results[0]['name'], frame_list[0]))
                            _a_params = {'directory': os.path.join(task['directory'], task['sample']['name'], 'scrn'),
                                         'info': {'anomalous': False,
                                                  'file_names': [_first_frame,]                                             
                                                  },
                                         'type': 'SCRN',
                                         'crystal': task.options['sample'],
                                         'name': collect_results[0]['name'] }

                            if not os.path.exists(_a_params['directory']):
                                os.makedirs(_a_params['directory']) # make sure directories exist
                            gobject.idle_add(self.emit, 'analyse-request', _a_params)
                            self._collect_results = []
                            _logger.warn('Requesting analysis')
                            self._notify_progress(Screener.TASK_STATE_DONE)
                        else:
                            self._notify_progress(Screener.TASK_STATE_SKIPPED)
                            _logger.warn('Skipping task because frames were not collected')
                    else:
                        self._notify_progress(Screener.TASK_STATE_SKIPPED)
                        _logger.warn('Skipping task because frames were not collected')
                                                                     
                self.pos += 1
            
                         
            gobject.idle_add(self.emit, 'done')
            self.stopped = True
        finally:
            self.beamline.exposure_shutter.close()
            #self.beamline.lock.release()
        

    def set_position(self, pos):
        self.pos = pos
        
    def pause(self):
        self.paused = True
        self.data_collector.pause()
        
    def resume(self):
        if self.last_pause is Screener.PAUSE_BEAM and self.beamline.storage_ring.get_state()['beam']:
            self.last_pause = None
        self.paused = False
        self.data_collector.resume()
    
    def stop(self):
        self.stopped = True
        self.data_collector.stop()



    
