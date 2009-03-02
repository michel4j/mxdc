import threading
import logging
import gobject
import time

from zope.interface import Interface, Attribute
from zope.interface import implements
from zope.component import globalSiteManager as gsm
from bcm.protocol import ca
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger
from bcm.utils.misc import generate_run_list
from bcm.utils.converter import energy_to_wavelength

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

class DataCollector(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['new-image'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_INT,gobject.TYPE_STRING))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,gobject.TYPE_INT))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,))
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    
    def __init__(self):
        gobject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.skip_collected = False
        
        #associate beamline devices
        try:
            self.beamline = gsm.getUtility(IBeamline, 'bcm.beamline')
        except:
            self.beamline = None
            _logger.warning('No registered beamline found.')
            
    def configure(self, run_data=None, run_list=None, skip_collected=True):
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
    
    
    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.start()

    
    def run(self):
        self.paused = False
        self.stopped = False
        if self.beamline is None:
            _logger.error('No Beamline found. Aborting data collection.')
            return
        ca.threads_init() 
        self.beamline.lock.acquire()
        try:          
            self.beamline.exposure_shutter.close()
            self.beamline.detector.initialize()
            self.pos = 0
            header = {}
            while self.pos < len(self.run_list) :
                if self.paused:
                    gobject.idle_add(self.emit, 'paused', True)
                    while self.paused and not self.stopped:
                        time.sleep(0.05)
                    gobject.idle_add(self.emit, 'paused', False)
                if self.stopped:
                    gobject.idle_add(self.emit, 'stopped')
                    break
    
                frame = self.run_list[self.pos]   
                if frame['saved'] and self.skip_collected:
                    self.log( 'Skipping %s' % frame['file_name'])
                    continue                               
                self.beamline.monochromator.energy.move_to(frame['energy'])
                self.beamline.diffractometer.distance.move_to(frame['distance'])
                self.beamline.diffractometer.distance.wait()
                self.beamline.diffractometer.two_theta.move_to(frame['two_theta'])
                self.beamline.diffractometer.two_theta.wait()
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
                self.beamline.detector.start()            
                self.beamline.goniometer.scan()
                self.beamline.detector.save(header)
    
                _logger.info("Image Collected: %s" % frame['file_name'])
                gobject.idle_add(self.emit, 'new-image', self.pos, "%s/%s" % (frame['directory'],frame['file_name']))
                
                # Notify progress
                fraction = float(self.pos) / len(self.run_list)
                gobject.idle_add(self.emit, 'progress', fraction, self.pos+1)          
                self.pos += 1
            
            gobject.idle_add(self.emit, 'done')
            if not self.stopped:
                gobject.idle_add(self.emit, 'progress', 1.0, 0)
            self.stopped = True
        finally:
            self.beamline.exposure_shutter.close()
            self.beamline.lock.release()

    def set_position(self,pos):
        self.pos = pos
        
    def pause(self):
        self.paused = True
        
    def resume(self):
        self.paused = False
    
    def stop(self):
        self.stopped = True
    
                
gobject.type_register(DataCollector)