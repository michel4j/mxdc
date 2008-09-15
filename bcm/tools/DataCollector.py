#!/usr/bin/env python

import sys, time, os
import gtk, gobject
import threading
from bcm.protocols import ca
from bcm import utils

class DataCollector(gobject.GObject):
    __gsignals__ = {}
    __gsignals__['new-image'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_INT,gobject.TYPE_STRING))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,))
    __gsignals__['started'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['log'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    __gsignals__['error'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    
    def __init__(self, beamline):
        gobject.GObject.__init__(self)
        self.paused = False
        self.stopped = False
        self.skip_collected = False
        self._initialized = False
        
        #associate beamline devices
        try:
            self.beamline = beamline
            self.detector = beamline.ccd
            self.gonio = beamline.gonio
            self.shutter = beamline.shutter
            self.two_theta = beamline.det_2th
            self.distance = beamline.det_d
            self.energy = beamline.energy
            self._initialized = True
        except AttributeError:
            self._initialized = False
        
        
    def setup(self, run_list, skip_collected=True):
        self.run_list = run_list
        self.skip_collected = skip_collected
        return
    
    def start(self):
        if self._initialized:
            self.paused = False
            self.stopped = False
            self._worker = threading.Thread(target=self._collect_data)
            self._worker.start()
        else:
            gobject.idle_add(self.emit, 'stopped')
            gobject.idle_add(self.emit, 'progress', 1.0)

    
    def _collect_data(self):
        ca.thread_init()
                
        self.shutter.close()
        time.sleep(0.1)  # small delay to make sure shutter is closed
        self.detector.initialize()
        self.pos = 0
        header = {}
        
        while self.pos < len(self.run_list) :
            if not self.detector.is_healthy():
                self.stopped = True
                gobject.idle_add(self.emit, 'error', 'Connection to Detector Lost!')
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
                self.log( 'Skipping %s' % frame['file_name'])
                continue
            _motion_flag = [False,False,False]
            # Check and prepare beamline
            if abs(frame['distance'] - self.distance.get_position()) > 1e-2:
                self.distance.move_to(frame['distance'])
                self.distance.wait(start=True, stop=False)
                _motion_flag[0] = True     
            if  abs(frame['energy'] - self.energy.get_position()) > 1e-5:
                self.energy.move_to(frame['energy'])
                self.energy.wait(start=True, stop=False)
                _motion_flag[1] = True     
            if  abs(frame['two_theta'] - self.two_theta.get_position()) > 1e-3:
                self.two_theta.move_to(frame['two_theta'])
                self.two_theta.wait(start=True, stop=False)
                _motion_flag[2] = True

            for m,f in zip ([self.distance, self.energy, self.two_theta], _motion_flag):
                if f: m.wait(start=False, stop=True)


            velo = frame['delta'] / float(frame['time'])
            
            
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
            header['wavelength'] = utils.energy_to_wavelength(frame['energy'])
            header['energy'] = frame['energy']
            header['prefix'] = frame['prefix']
            header['start_angle'] = frame['start_angle']            
               
            gonio_data = {
                'time': frame['time'],
                'delta' : frame['delta'],
                'start_angle': frame['start_angle'],                
            }
            self.gonio.set_parameters(gonio_data)
            self.detector.start()            
            self.detector.set_parameters(header)
            self.gonio.scan()
            self.detector.save()

            self.log("Image Collected: %s" % frame['file_name'])
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
    
    def log(self, message):
        gobject.idle_add(self.emit, 'log', message)
                
gobject.type_register(DataCollector)
