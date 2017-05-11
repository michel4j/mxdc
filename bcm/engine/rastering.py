from bcm.beamline.interfaces import IBeamline
from bcm.engine import centering, snapshot
from bcm.engine.interfaces import IDataCollector
from bcm.protocol import ca
from bcm.utils.converter import energy_to_wavelength, dist_to_resol
from bcm.utils.log import get_module_logger
from bcm.utils.misc import get_project_name

from twisted.python.components import globalRegistry

import gobject
import os
import threading
import time


# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class RasterCollector(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['new-image'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,))
    __gsignals__['new-fluor'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT, gobject.TYPE_PYOBJECT))
    __gsignals__['new-result'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT, gobject.TYPE_PYOBJECT))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,))
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    STATE_PENDING, STATE_RUNNING, STATE_DONE, STATE_SKIPPED = range(4)
    PAUSE_TASK, PAUSE_BEAM, PAUSE_ALIGN, PAUSE_MOUNT, PAUSE_UNRELIABLE = range(5)
    
    def __init__(self):
        gobject.GObject.__init__(self)
        self.paused = False
        self.stopped = True
        self.run_list = []
        self.runs = []
        self.results = {}
        self.image_cells = {}
        self._last_initialized = 0
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.new_image_handler_id = self.beamline.detector.connect('new-image', self.on_new_image)
        self.beamline.detector.handler_block(self.new_image_handler_id)
        
            
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
         
        self.raster_parameters = {}
        self.raster_parameters.update(run_data)
        self.beamline.image_server.setup_folder(self.raster_parameters['directory'])
        self.raster_parameters['user_properties'] = (get_project_name(), os.geteuid(), os.getegid())


    def _notify_progress(self, status):
        # Notify progress
        fraction = float(self.pos) / self.total_items
        gobject.idle_add(self.emit, 'progress', fraction)                
    
            
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
        self.beamline.detector_cover.open(wait=True)
        self.beamline.detector.handler_unblock(self.new_image_handler_id)
        # Obtain configured parameters
        self.grid_parameters = self.raster_parameters
        self.grid_cells = self.raster_parameters['cells']
        self._user_properties = self.raster_parameters['user_properties']
              
        self.beamline.image_server.set_user(*self._user_properties)
        self.paused = False
        self.stopped = False
                   
        self.beamline.goniometer.set_mode('COLLECT', wait=True) # move goniometer to collect mode
        gobject.idle_add(self.emit, 'started')
        try:
            self.beamline.exposure_shutter.close()
            self.pos = 0
            header = {}
            self._first = True
            self.total_items = len(self.grid_cells)
            self.image_queue = []
            self.pending_results = []
            self.image_cells = {}
            
            self.beamline.image_server.setup_folder(self.grid_parameters['directory'])
            for cell, cell_loc in self.grid_cells.items():
                if self.paused:
                    gobject.idle_add(self.emit, 'paused', True)
                    while self.paused and not self.stopped:
                        time.sleep(0.05)
                    self.beamline.goniometer.set_mode('COLLECT', wait=True)   
                    gobject.idle_add(self.emit, 'paused', False)
                if self.stopped:
                    _logger.info("Stopping Rastering...")
                    break
    
                frame = {
                    'directory': self.grid_parameters['directory'],
                    'distance': self.grid_parameters['distance'],
                    'delta_angle': self.grid_parameters['delta'],
                    'exposure_time': self.grid_parameters['time'],
                    'start_angle': self.grid_parameters['angle']-0.5,
                    'start_frame': 1,
                    'two_theta': round(self.beamline.two_theta.get_position(), 1),
                    'energy': self.beamline.energy.get_position(),
                    'file_prefix': '%s_%dx%d' % (self.grid_parameters['prefix'], cell[0], cell[1]),
                    'frame_name':   '%s_%dx%d' % (self.grid_parameters['prefix'], cell[0], cell[1])
                }

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
                header = {
                    'file_prefix': frame['file_prefix'],
                    'delta_angle': frame['delta_angle'],
                    'directory': frame['directory'],
                    'distance': frame['distance'],
                    'exposure_time': frame['exposure_time'],
                    'start_frame': frame['start_frame'],
                    'wavelength': energy_to_wavelength(frame['energy']),
                    'energy': frame['energy'],
                    'frame_name': frame['frame_name'],
                    'num_frames': 1,
                    'two_theta': frame['two_theta'],
                    'start_angle': frame['start_angle'],
                    'comments': 'BEAMLINE: {} {}'.format('CLS', self.beamline.name),
                }

                # prepare goniometer for scan
                self.beamline.goniometer.configure(
                    time=frame['exposure_time'], delta=frame['delta_angle'], angle=frame['start_angle']
                )

                self.beamline.detector.set_parameters(header)
                self.beamline.detector.start(first=self._first)
                self.beamline.goniometer.scan(wait=True, timeout=frame['exposure_time'] * 4)
                self.beamline.detector.save()

                self._first = False
                self.pos = self.pos + 1
                    
                _logger.info("Image Collected: %s" % (frame['frame_name']))
                gobject.idle_add(self.emit, 'progress', self.pos/float(self.total_items))
                self.image_cells[os.path.join(frame['directory'], frame['frame_name'])] = cell

            # finish off analysing the images after everything is copied over
            while not self.analyse_image() or len(self.pending_results) > 0:
                time.sleep(0.1)
                
            if not self.stopped:
                gobject.idle_add(self.emit, 'done')
                gobject.idle_add(self.emit, 'progress', 1.0)
            else:
                gobject.idle_add(self.emit, 'stopped')
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
            self.beamline.detector.handler_block(self.new_image_handler_id)
            self.beamline.detector_cover.close()
            self.beamline.exposure_shutter.close()
            self.beamline.lock.release()

    def on_new_image(self, obj, file_path):
        gobject.idle_add(self.emit, 'new-image', file_path)
        for frame, cell in self.image_cells.items():
            if file_path.startswith(frame):
                self.analyse_image((cell, file_path))

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
        gobject.idle_add(self.emit, 'new-result', cell, results)
        self.pending_results.remove(cell)
        
    def _result_fail(self, results, cell):
        _logger.error("Unable to process data")
        gobject.idle_add(self.emit, 'new-result', cell, results)
        self.pending_results.remove(cell)

                    
    def pause(self):
        self.paused = True
        
    def resume(self):
        self.paused = False
    
    def stop(self):
        self.stopped = True
        
        