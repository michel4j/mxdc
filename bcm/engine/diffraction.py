import threading
import logging
import gobject
import time
import os

from zope.interface import Interface, Attribute
from zope.interface import implements
from twisted.python.components import globalRegistry
from bcm.protocol import ca
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger
from bcm.utils.misc import generate_run_list
from bcm.utils.converter import energy_to_wavelength


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


DEFAULT_PARAMETERS = {
    'prefix': 'test',
    'directory': os.environ['HOME'],
    'distance': 250.0,
    'delta': 1.0,
    'time': 1.0,
    'start_angle': 0,
    'total_angle': 1.0,
    'start_frame': 1,
    'total_frames': 1,
    'inverse_beam': False,
    'wedge': 360.0,
    'energy': [ 12.658 ],
    'energy_label': ['E0'],
    'number': 1,
    'two_theta': 0.0,
}

class Screener(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['message'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT, gobject.TYPE_INT))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN, gobject.TYPE_STRING))
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    
    TASK_MOUNT, TASK_ALIGN, TASK_PAUSE, TASK_COLLECT, TASK_ANALYSE = range(5)
      
    def __init__(self):
        gobject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.skip_collected = False

    def configure(self, run_list):
        #associate beamline devices
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
            _logger.warning('No registered beamline found.')
            raise
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
        self.beamline.lock.acquire()
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
                _logger.debug('-----------------------------------------------------')
                if task.task_type == Screener.TASK_PAUSE:
                    self.pause()
                    pause_msg = 'Screening paused automatically, as requested, after completing '
                    pause_msg += 'task <b>"%s"</b> ' % self.run_list[self.pos - 1].name
                    pause_msg += 'on sample <b>"%s(%s)</b>"' % (self.run_list[self.pos]['sample']['name'], 
                                                                self.run_list[self.pos]['sample']['id'])
                    
                    
                elif task.task_type == Screener.TASK_MOUNT:
                    _logger.debug('Mount "%s"' % task['sample']['port'])
                    time.sleep(1.0)
                elif task.task_type == Screener.TASK_ALIGN:
                    _logger.debug('Align sample "%s"' % task['sample']['id'])
                    time.sleep(1.0)
                elif task.task_type == Screener.TASK_COLLECT:
                    run_params = DEFAULT_PARAMETERS
                    run_params['distance'] = self.beamline.diffractometer.distance.get_position()
                    run_params['two_theta'] = self.beamline.diffractometer.two_theta.get_position()
                    run_params['energy'] = [ self.beamline.monochromator.energy.get_position() ]
                    run_params['energy_label'] = ['E0']
                    run_params.update({'prefix': task['sample']['id'],
                                  'directory': os.path.join(task['directory'], task['sample']['id']),
                                  'total_frames': task['frames'],
                                  'start_angle': task['angle'],
                                  'start_frame': 1,
                                  'number': 0,
                                  'total_angle': task['delta'] * task['frames'],
                                  'delta': task['delta'],
                                  'time': task['time'],})
                    run_list = generate_run_list(run_params, show_number=True)
                    _logger.debug('Collect frames for "%s"' % task['sample']['id'])
                    import pprint
                    pprint.pprint(run_list)
                    time.sleep(1.0)
                elif task.task_type == Screener.TASK_ANALYSE:
                    time.sleep(1.0)
                           
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
            self.beamline.lock.release()

    def set_position(self, pos):
        self.pos = pos
        
    def pause(self):
        self.paused = True
        
    def resume(self):
        self.paused = False
    
    def stop(self):
        self.stopped = True


class DataCollector(gobject.GObject):
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
        
            
    def configure(self, run_data=None, run_list=None, skip_collected=True):
        #associate beamline devices
        try:
            self.beamline = globalRegistry.lookup([], IBeamline)
        except:
            self.beamline = None
            _logger.warning('No registered beamline found.')
            raise
        if run_data is None and run_list is None:
            self.run_list = []
            _logger.warning('Run is empty')
        elif run_data is not None:  # run_data supersedes run_list if specified
            self.run_list = generate_run_list(run_data)
            self.beamline.image_server.create_folder(run_data['directory'])
        else: # run_list is not empty
            self.run_list = run_list
        self.total_frames = len(self.run_list)
        self.skip_collected = skip_collected
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
            return
        ca.threads_init() 
        self.beamline.lock.acquire()
        self.beamline.goniometer.set_mode('collect', wait=True) # move goniometer to collect mode
        gobject.idle_add(self.emit, 'started')
        try:          
            self.beamline.exposure_shutter.close()
            self.beamline.detector.initialize()
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
                header['delta'] = frame['delta']
                header['filename'] = frame['file_name']
                dir_parts = frame['directory'].split('/')
                if dir_parts[1] == 'users':
                    dir_parts[1] = 'data'
                    header['directory'] = '/'.join(dir_parts)
                else:
                    header['directory'] = frame['directory']
                header['distance'] = frame['distance'] 
                header['time'] = frame['time']
                header['frame_number'] = frame['frame_number']
                header['wavelength'] = energy_to_wavelength(frame['energy'])
                header['energy'] = frame['energy']
                header['prefix'] = frame['prefix']
                header['start_angle'] = frame['start_angle']            
                
                #prepare goniometer for scan   
                self.beamline.goniometer.configure(time=frame['time'],
                                                   delta=frame['delta'],
                                                   angle=frame['start_angle'])
                self.beamline.detector.start(first=_first)
                self.beamline.detector.set_parameters(header)
                self.beamline.goniometer.scan()
                self.beamline.detector.save()
                frame['saved'] = True
                _first = False
                    
    
                _logger.info("Image Collected: %s" % frame['file_name'])
                gobject.idle_add(self.emit, 'new-image', self.pos, "%s/%s" % (frame['directory'], frame['file_name']))
                
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
            self.beamline.goniometer.set_mode('mount') # return goniometer to mount position
            self.beamline.lock.release()

    def set_position(self, pos):
        self.pos = pos
        
    def pause(self):
        self.paused = True
        
    def resume(self):
        self.paused = False
    
    def stop(self):
        self.stopped = True


from bcm.service.utils import *
    
gobject.type_register(DataCollector)
gobject.type_register(Screener)
