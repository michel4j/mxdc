#!/usr/bin/env python

import sys, time, os
import gtk, gobject
import threading
from bcm.protocols import ca

class DataCollector(threading.Thread, gobject.GObject):
    __gsignals__ = {}
    __gsignals__['new-image'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_INT,gobject.TYPE_STRING))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,))
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['log'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    
    def __init__(self, run_list, beamline, skip_collected=True):
        threading.Thread.__init__(self)
        gobject.GObject.__init__(self)
        self.run_list = run_list
        self.paused = False
        self.stopped = False
        self.beamline = beamline
        self.skip_collected = skip_collected
        
    def setup(self, run_list, skip_collected=True):
        self.run_list = run_list
        self.skip_collected = skip_collected
        return
    
    def run(self, widget=None):
        ca.thread_init()
        
        self.detector = self.beamline.imaging_detector
        self.gonio = self.beamline.goniometer
        self.shutter = self.beamline.exposure_shutter
        
        self.shutter.close()
        time.sleep(0.1)  # small delay to make sure shutter is closed
        self.detector.initialize()
        self.pos = 0
        header = {}
        while self.pos < len(self.run_list) :
                
            if self.paused:
                gobject.idle_add(self.emit, 'paused', True)
                while self.paused and not self.stopped:
                    time.sleep(0.1)
                gobject.idle_add(self.emit, 'paused', False)
            if self.stopped:
                gobject.idle_add(self.emit, 'stopped')
                return

            frame = self.run_list[self.pos]
            self.pos += 1
            if frame['saved'] and self.skip_collected:
                self._log( 'Skipping %s' % frame['file_name'])
                continue
            velo = frame['delta'] / float(frame['time'])
            
            
            # Prepare image header
            header['delta'] = frame['delta']
            header['filename'] = frame['file_name']
            header['directory'] = frame['remote_directory']
            header['distance'] = frame['distance'] 
            header['time'] = frame['time']
            header['frame_number'] = frame['frame_number']
            header['wavelength'] = keVToA(frame['energy'])
            header['energy'] = frame['energy']
            header['prefix'] = frame['prefix']
            header['start_angle'] = frame['start_angle']
            
            # Check and prepare beamline
            if abs(self.beamline.detector_distance.get_position() - frame['distance']) > 1e-2:
                self.beamline.detector_distance.move_to(frame['distance'])
            if abs(self.beamline.energy.get_position() - frame['energy']) > 1e-4:
                self.beamline.energy.move_to(frame['energy'])
            
            #wait for energy and distance to stop moving
            self.beamline.detector_distance.wait()
            self.beamline.energy.wait()
            gonio_data = {
                'time': frame['time'],
                'delta' : frame['delta'],
                'start_angle': frame['start_angle'],                
            }
            self.gonio.set_params(gonio_data)
            self.detector.start()            
            self.detector.set_parameters(header)
            self.gonio.scan()
            self.detector.save()

            self._log("Image Collected: %s" % frame['file_name'])
            gobject.idle_add(self.emit, 'new-image', frame['index'], "%s/%s" % (frame['directory'],frame['file_name']))
            
            # Notify progress
            fraction = float(self.pos) / len(self.run_list)
            gobject.idle_add(self.emit, 'progress', fraction)
            
            
        gobject.idle_add(self.emit, 'done')
        gobject.idle_add(self.emit, 'progress', 1.0)

    def set_position(self,pos):
        self.pos = pos
        
    def pause(self):
        self.paused = True
        
    def resume(self):
        self.paused = False
    
    def stop(self):
        self.stopped = True
    
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)
                
gobject.type_register(DataCollector)
