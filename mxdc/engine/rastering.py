from mxdc.interface.beamlines import IBeamline
from mxdc.engine import centering, snapshot
from mxdc.interface.engines import IDataCollector
from mxdc.com import ca
from mxdc.utils.converter import energy_to_wavelength, dist_to_resol
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import get_project_name

from twisted.python.components import globalRegistry

from gi.repository import GObject
import os
import threading
import time


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class RasterCollector(GObject.GObject):
    __gsignals__ = {}
    __gsignals__['new-image'] = (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT))
    __gsignals__['new-fluor'] = (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT))
    __gsignals__['new-result'] = (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT))
    __gsignals__['progress'] = (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_FLOAT,))
    __gsignals__['done'] = (GObject.SignalFlags.RUN_LAST, None, [])
    __gsignals__['paused'] = (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_BOOLEAN,))
    __gsignals__['started'] = (GObject.SignalFlags.RUN_LAST, None, [])
    __gsignals__['stopped'] = (GObject.SignalFlags.RUN_LAST, None, [])
    
    STATE_PENDING, STATE_RUNNING, STATE_DONE, STATE_SKIPPED = range(4)
    PAUSE_TASK, PAUSE_BEAM, PAUSE_ALIGN, PAUSE_MOUNT, PAUSE_UNRELIABLE = range(5)
    
    def __init__(self):
        GObject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.run_list = []
        self.runs = []
        self.results = {}        
        self._last_initialized = 0
        
            
    def configure(self, run_data):
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
         
        self.raster_parameters = {}
        self.raster_parameters.update(run_data)
        self.beamline.image_server.setup_folder(self.raster_parameters['directory'])
        self.raster_parameters['user_properties'] = (get_project_name(), os.geteuid(), os.getegid())


    def _on_beam_change(self, obj, beam_available):
        if not beam_available and (not self.paused) and (not self.stopped):
            self.pause()
            GObject.idle_add(self.emit, 'paused', True)

    def _notify_progress(self, status):
        # Notify progress
        fraction = float(self.pos) / self.total_items
        GObject.idle_add(self.emit, 'progress', fraction)                
    
            
    def get_state(self):
        state = {
            'paused': self.paused,
            'stopped': self.stopped,
            'parameters': self.raster_parameters,
            'pos': self.pos }
        return state
    
    def start(self):
        worker_thread = threading.Thread(target=self.run)
        worker_thread.setDaemon(True)
        worker_thread.setName('Raster Collector')
        worker_thread.start()
    
    def run(self):
        if self.beamline is None:
            _logger.error('No Beamline found. Aborting Raster Screening.')
            return False
        ca.threads_init()
        self.beamline.lock.acquire()
        
        # Obtain configured parameters
        self.grid_parameters = self.raster_parameters
        self.grid_cells = self.raster_parameters['cells']
        self._user_properties = self.raster_parameters['user_properties']
              
        self.beamline.image_server.set_user(*self._user_properties)
        self.paused = False
        self.stopped = False
                   
        self.beamline.goniometer.set_mode('COLLECT', wait=True) # move goniometer to collect mode
        GObject.idle_add(self.emit, 'started')
        try:
            self.beamline.exposure_shutter.close()
            self.pos = 0
            header = {}
            self._first = True
            self.total_items = len(self.grid_cells)
            self.image_queue = []
            self.pending_results = []
            import pprint
            pprint.pprint(self.grid_parameters)
            
            self.beamline.image_server.setup_folder(self.grid_parameters['directory'])
            for cell, cell_loc in self.grid_cells.items():
                if self.paused:
                    GObject.idle_add(self.emit, 'paused', True)
                    while self.paused and not self.stopped:
                        time.sleep(0.05)
                    self.beamline.goniometer.set_mode('COLLECT', wait=True)   
                    GObject.idle_add(self.emit, 'paused', False)
                if self.stopped:
                    _logger.info("Stopping Rastering")
                    break
    
                frame = {
                    'directory': self.grid_parameters['directory'],
                    'distance': self.grid_parameters['distance'],
                    'delta_angle': self.grid_parameters['delta'],
                    'exposure_time': self.grid_parameters['time'],
                    'start_angle': self.grid_parameters['angle']-0.5,
                    'energy':self.beamline.energy.get_position(),
                    'name':   '%s_%dx%d_001' % (self.grid_parameters['prefix'], cell[0], cell[1])
                }
                frame['file_name'] = "%s.img" % (frame['name'])
                _full_file =  os.path.join(frame['directory'], frame['file_name']) 
                
                if os.path.exists(_full_file):
                    os.remove(_full_file)

                ox, oy = self.grid_parameters['origin']
                cell_x = ox - cell_loc[2]
                cell_y = oy - cell_loc[3]
                self.beamline.omega.move_to(self.grid_parameters['angle'], wait=True)
                if not self.beamline.sample_stage.x.is_busy():
                    self.beamline.sample_stage.x.move_to(cell_x, wait=True)
                if not self.beamline.sample_stage.y.is_busy():
                    self.beamline.sample_stage.y.move_to(cell_y, wait=True)
                                
                self.beamline.diffractometer.distance.move_to(frame['distance'], wait=True)              
                
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
                header['frame_number'] = 1
                header['wavelength'] = energy_to_wavelength(frame['energy'])
                header['energy'] = frame['energy']
                header['name'] = frame['name']
                header['start_angle'] = frame['start_angle']
                header['comments'] = 'BEAMLINE: %s %s' % ('CLS', self.beamline.name)
                
                #prepare goniometer for scan   
                self.beamline.goniometer.configure(time=frame['exposure_time'],
                                                   delta=frame['delta_angle'],
                                                   angle=frame['start_angle'])

                self.beamline.detector.start(first=self._first)
                self.beamline.detector.set_parameters(header)
                self.beamline.goniometer.scan()
                self.beamline.detector.save()

                self._first = False
                self.pos = self.pos + 1
                    
                _logger.info("Image Collected: %s" % (frame['file_name']))
                GObject.idle_add(self.emit, 'new-image', cell, os.path.join(frame['directory'], frame['file_name']))
                GObject.idle_add(self.emit, 'progress', self.pos/float(self.total_items))
                self.analyse_image((cell, os.path.join(frame['directory'], frame['file_name'])))
               
            # finish off analysing the images after everything is copied over
            while not self.analyse_image() or len(self.pending_results) > 0:
                time.sleep(0.1)
                
            if not self.stopped:
                GObject.idle_add(self.emit, 'done')
                GObject.idle_add(self.emit, 'progress', 1.0)
            else:
                GObject.idle_add(self.emit, 'stopped')
            self.stopped = True
            
            # return to starting position
            _logger.info("Returning to the center of the grid ...")
            self.beamline.omega.move_to(self.grid_parameters['angle'], wait=True)
            ox, oy = self.grid_parameters['origin']
            if not self.beamline.sample_stage.x.is_busy():
                self.beamline.sample_stage.x.move_to(ox, wait=True)
            if not self.beamline.sample_stage.y.is_busy():
                self.beamline.sample_stage.y.move_to(oy, wait=True)
            
        finally:
            self.beamline.exposure_shutter.close()
            self.beamline.lock.release()

    def analyse_image(self, cell_params=None):
        if cell_params is not None: 
            cell, filename = cell_params          
            self.image_queue.append((cell, filename))
        elif len(self.image_queue) == 0:
            return True
        
        cell, filename = self.image_queue[0]
        if os.path.exists(filename):
            self.image_queue.pop(0)
        else:
            return False
        try:
            self.pending_results.append(cell)
            _logger.info("Analyzing image: %s" % (filename))
            self.beamline.dpm.service.callRemote('analyseImage',
                                filename, 
                                self.grid_parameters['directory'],
                                self._user_properties[0],
                                ).addCallbacks(self._result_ready, callbackArgs=[cell],
                                               errback=self._result_fail, errbackArgs=[cell])
        except:
            self._result_fail(None, cell)
        
    def _result_ready(self, results, cell):
        GObject.idle_add(self.emit, 'new-result', cell, results)
        self.pending_results.remove(cell)
        
    def _result_fail(self, results, cell):
        _logger.error("Unable to process data")
        GObject.idle_add(self.emit, 'new-result', cell, results)
        self.pending_results.remove(cell)

                    
    def pause(self):
        self.paused = True
        
    def resume(self):
        self.paused = False
    
    def stop(self):
        self.stopped = True
        
        