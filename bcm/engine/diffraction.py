from bcm.beamline.interfaces import IBeamline
from bcm.engine import centering, snapshot
from bcm.engine.interfaces import IDataCollector
from bcm.protocol import ca
from bcm.utils.converter import energy_to_wavelength
from bcm.utils.log import get_module_logger
from bcm.utils import runlists
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
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT, gobject.TYPE_INT))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN, gobject.TYPE_STRING))
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    
    def __init__(self):
        gobject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.skip_collected = False
        self.run_list = []
        self.runs = []
        self.results = {}        
        self._last_initialized = 0
            
    def configure(self, runs, skip_collected=True):
        #associate beamline devices
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
            _logger.warning('No registered beamline found.')
            raise
        
        self.skip_collected = skip_collected
        self.runs = runs.deepcopy()
        max_sets = 1   
        for run in self.runs:        
            self.beamline.image_server.setup_folder(run['directory'])
            max_sets = max(max_sets, len(run['frame_sets']))

        for i in range(max_sets):
            for run in self.runs:
                if i < len(run['frame_sets']):
                    self.run_list.extend(runlists.generate_frame_list(run, run['frame_sets'][i]))            
        self._user_properties = (pwd.getpwuid(os.geteuid())[0]  , os.geteuid(), os.getegid())
        self.beamline.image_server.set_user(*self._user_properties)

            
        return
    
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
        self.paused = False
        self.stopped = False
        if self.beamline is None:
            _logger.error('No Beamline found. Aborting data collection.')
            return False
        ca.threads_init()
        self.beamline.lock.acquire()
        self.beamline.goniometer.set_mode('COLLECT', wait=True) # move goniometer to collect mode
        gobject.idle_add(self.emit, 'started')
        try:
                   
            self.beamline.exposure_shutter.close()

            self.pos = 0
            header = {}
            pause_msg = ''
            _first = True
            while self.pos < len(self.run_list) :
                if self.paused:
                    gobject.idle_add(self.emit, 'paused', True, pause_msg)
                    pause_msg = ''
                    while self.paused and not self.stopped:
                        time.sleep(0.05)
                    gobject.idle_add(self.emit, 'paused', False, '')
                if self.stopped:
                    gobject.idle_add(self.emit, 'stopped')
                    break
    
                frame = self.run_list[self.pos]   
                if frame['saved'] and self.skip_collected:
                    _logger.info('Skipping %s' % frame['file_name'])
                    self.pos += 1
                    continue                               
                self.beamline.monochromator.energy.move_to(frame['energy'])
                self.beamline.diffractometer.distance.move_to(frame['distance'], wait=True)
                #self.beamline.diffractometer.two_theta.move_to(frame['two_theta'], wait=True)
                self.beamline.monochromator.energy.wait()                
                
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
                
                #prepare goniometer for scan   
                self.beamline.goniometer.configure(time=frame['exposure_time'],
                                                   delta=frame['delta_angle'],
                                                   angle=frame['start_angle'])

                self.beamline.detector.start(first=_first)
                self.beamline.detector.set_parameters(header)
                self.beamline.goniometer.scan()
                self.beamline.detector.save()
                
                frame['saved'] = True
                _first = False
                    
    
                _logger.info("Image Collected: %s" % frame['file_name'])
                gobject.idle_add(self.emit, 'new-image', self.pos, "%s/%s" % (frame['directory'], frame['file_name']))
                self.collected_frames.append((frame['file_name'], frame['start_angle']))
                
                # Notify progress
                fraction = float(self.pos) / len(self.run_list)
                gobject.idle_add(self.emit, 'progress', fraction, self.pos + 1)          
                self.pos += 1
            
            gobject.idle_add(self.emit, 'done')
            if not self.stopped:
                gobject.idle_add(self.emit, 'progress', 1.0, 0)
            self.stopped = True
        finally:
            self.beamline.exposure_shutter.close()
            #self.beamline.goniometer.set_mode('MOUNTING') # return goniometer to mount position
            self.beamline.lock.release()        
        self.results = {'parameters': self.run_data, 'frame_list': self.collected_frames}
        return self.results

    def set_position(self, pos):
        self.pos = pos
        
    def pause(self):
        self.paused = True
        
    def resume(self):
        self.paused = False
    
    def stop(self):
        self.stopped = True
        
        
        
class Screener(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['message'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT, gobject.TYPE_INT))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN, gobject.TYPE_STRING))
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['sync'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN, gobject.TYPE_STRING))
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['analyse-request'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,))
   
    TASK_MOUNT, TASK_ALIGN, TASK_PAUSE, TASK_COLLECT, TASK_ANALYSE = range(5)
      
    def __init__(self):
        gobject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.skip_collected = False
        self.data_collector = None
        self._collect_results = None
        
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
        self.run_list = run_list
        self.total_items = len(self.run_list)
        return
    
    
    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Screener')
        worker_thread.start()
            
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
            pause_msg = ''

            while self.pos < len(self.run_list) :
                if self.paused:
                    gobject.idle_add(self.emit, 'paused', True, pause_msg)
                    pause_msg = ''
                    while self.paused and not self.stopped:
                        time.sleep(0.05)
                    gobject.idle_add(self.emit, 'paused', False, '')
                if self.stopped:
                    gobject.idle_add(self.emit, 'stopped')
                    break
    
                # Perform the screening task here
                task = self.run_list[self.pos]
                if task.task_type == Screener.TASK_PAUSE:
                    self.pause()
                    pause_msg = 'Screening paused automatically, as requested, after completing '
                    pause_msg += 'task <b>"%s"</b> ' % self.run_list[self.pos - 1].name
                    pause_msg += 'on sample <b>"%s(%s)</b>"' % (self.run_list[self.pos]['sample']['name'],
                                                                self.run_list[self.pos]['sample']['name'])
                    
                      
                elif task.task_type == Screener.TASK_MOUNT:
                    _logger.warn('TASK: Mount "%s"' % task['sample']['port'])
                    if self.beamline.automounter.is_mounted(task['sample']['port']):
                        # Do nothing here
                        pass
                    elif self.beamline.automounter.is_mountable(task['sample']['port']):
                        self.beamline.goniometer.set_mode('MOUNTING', wait=True)
                        success = self.beamline.automounter.mount(task['sample']['port'], wait=True)
                        mounted_info = self.beamline.automounter.mounted_state
                        if not success or mounted_info is None:
                            self.pause()
                            self.stop()
                            pause_msg = 'Screening stopped, because automounting failed:  '
                            pause_msg += 'task <b>"%s"</b> ' % self.run_list[self.pos - 1].name
                            pause_msg += 'on sample <b>"%s(%s)</b>"' % (self.run_list[self.pos]['sample']['name'],
                                                                        self.run_list[self.pos]['sample']['port'])
                        else:
                            port, barcode = mounted_info
                            if port != self.run_list[self.pos]['sample']['port']:
                                gobject.idle_add(self.emit, 'sync', False, 'Port mismatch. Expected %s.' % self.run_list[self.pos]['sample']['port'])
                            elif barcode != self.run_list[self.pos]['sample']['barcode']:
                                gobject.idle_add(self.emit, 'sync', False, 'Barcode mismatch. Expected %s.' % self.run_list[self.pos]['sample']['barcode'])
                            else:
                                gobject.idle_add(self.emit, 'sync', True, '')                          
                    else:
                        #"skip mounting"
                        _logger.warn('Skipping sample: "%s @ %s". Sample port is not mountable!' % (task['sample']['name'], task['sample']['port']))
                                                                                                            
                elif task.task_type == Screener.TASK_ALIGN:
                    _logger.warn('TASK: Align sample "%s"' % task['sample']['name'])
                    
                    if self.beamline.automounter.is_mounted(task['sample']['port']):
                        self.beamline.goniometer.set_mode('CENTERING', wait=True)
                        _out = centering.auto_center_loop()
                        if _out is None:
                            _logger.error('Error attempting auto loop centering "%s"' % task['sample']['name'])
                            pause_msg = 'Screening paused automatically, due to centering error '
                            pause_msg += 'task <b>"%s"</b> ' % self.run_list[self.pos - 1].name
                            pause_msg += 'on sample <b>"%s(%s)</b>"' % (self.run_list[self.pos]['sample']['name'],
                                                                    self.run_list[self.pos]['sample']['port'])
                            self.pause()
                        elif _out.get('RELIABILITY') < 70:
                            pause_msg = 'Screening paused automatically, due to unreliable auto-centering '
                            pause_msg += 'task <b>"%s"</b> ' % self.run_list[self.pos - 1].name
                            pause_msg += 'on sample <b>"%s(%s)</b>"' % (self.run_list[self.pos]['sample']['name'],
                                                                    self.run_list[self.pos]['sample']['port'])
                            self.pause()
                        directory = os.path.join(task['directory'], task['sample']['name'], 'test')
                        if not os.path.exists(directory):
                            os.makedirs(directory) # make sure directories exist
                        snapshot.take_sample_snapshots('snapshot', directory, [0, 90, 180], True)
                    else:
                        _logger.warn('Skipping task because given sample is not mounted')
                        
                elif task.task_type == Screener.TASK_COLLECT:
                    _logger.warn('TASK: Collect frames for "%s"' % task['sample']['name'])
                    if self.beamline.automounter.is_mounted(task['sample']['port']):
                        run_params = DEFAULT_PARAMETERS.copy()
                        run_params['distance'] = self.beamline.diffractometer.distance.get_position()
                        run_params['two_theta'] = self.beamline.diffractometer.two_theta.get_position()
                        run_params['energy'] = [ self.beamline.monochromator.energy.get_position() ]
                        run_params['energy_label'] = ['E0']
                        run_params.update({'prefix': task['sample']['name'],
                                      'directory': os.path.join(task['directory'], task['sample']['name'], 'test'),
                                      'start_angle': task['angle'],
                                      'first_frame': task['start_frame'],
                                      'total_angle': task['delta'] * task['frames'],
                                      'delta_angle': task['delta'],
                                      'exposure_time': task['time'], })
                        if not os.path.exists(run_params['directory']):
                            os.makedirs(run_params['directory']) # make sure directories exist
                        self.data_collector.configure(run_params)
                        self._collect_results = self.data_collector.run()
                    else:
                        self._collect_results = None
                        _logger.warn('Skipping task because given sample is not mounted')
                        
                elif task.task_type == Screener.TASK_ANALYSE:
                    if self._collect_results is not None:
                        _first_frame = os.path.join(self._collect_results['parameters']['directory'],
                                                    self._collect_results['frame_list'][0][0])
                        _a_params = {'directory': os.path.join(task['directory'], task['sample']['name'], 'scrn'),
                                     'uname': os.getlogin(),
                                     'info': {'anomalous': False,
                                              'file_names': [_first_frame,]                                             
                                              },
                                     'crystal': task.options['sample'] }

                        if not os.path.exists(_a_params['directory']):
                            os.makedirs(_a_params['directory']) # make sure directories exist
                        gobject.idle_add(self.emit, 'analyse-request', _a_params)   
                        _logger.warn('Requesting analysis')
                    else:
                        _logger.warn('Skipping task because frames were not collected')
                                                  
                # Notify progress
                fraction = float(self.pos) / self.total_items
                gobject.idle_add(self.emit, 'progress', fraction, self.pos)          
                self.pos += 1
            
            gobject.idle_add(self.emit, 'done')
            if not self.stopped:
                gobject.idle_add(self.emit, 'progress', 1.0, 0)
            self.stopped = True
        finally:
            self.beamline.exposure_shutter.close()
            #self.beamline.lock.release()
        

    def set_position(self, pos):
        self.pos = pos
        
    def pause(self):
        self.paused = True
        
    def resume(self):
        self.paused = False
    
    def stop(self):
        self.stopped = True



    
