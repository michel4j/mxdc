#!/usr/bin/env python

import sys, time, os
import gtk, gobject
import threading
import numpy
from Beamline import beamline
from MarCCD import MarCCD2
from Utils import *
import EPICS as CA
from LogServer import LogServer

gobject.threads_init()

class DataCollector(threading.Thread, gobject.GObject):
    __gsignals__ = {}
    __gsignals__['new-image'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_INT,gobject.TYPE_STRING))
    __gsignals__['progress'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,))
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    
    def __init__(self, run_list=None, skip_collected=True):
        threading.Thread.__init__(self)
        gobject.GObject.__init__(self)
        self.run_list = run_list
        self.paused = False
        self.stopped = False
        self.skip_collected = skip_collected
        
    def setup(self, run_list, skip_collected=True):
        self.run_list = run_list
        self.skip_collected = skip_collected
        return
        
    def run(self, widget=None):
        CA.thread_init()
        self.detector = beamline['detectors']['ccd'].copy()
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
                LogServer.log( 'Skipping %s' % frame['file_name'])
                continue
            velo = frame['delta'] / float(frame['time'])
            start_pos = frame['start_angle']
            end_pos = start_pos + frame['delta']
            
            # prepare image header
            header['delta'] = frame['delta']
            header['directory'], header['filename'] = os.path.split(frame['file_name'])
            header['directory'] = header['directory']+'\0'
            header['filename'] = header['filename']+'\0'
            header['distance'] = frame['distance']
            header['time'] = frame['time']
            header['wavelength'] = keV_to_A(frame['energy'])
            
            self.detector.start()
            self.detector.set_header(header)
            
            # Place holder for gonio scan and shutter opening
            time.sleep(frame['time'])
            LogServer.log( "%04d ------------------------------------------" % self.pos)
            LogServer.log( "Energy   : %8.3f   keV:" % frame['energy'])
            LogServer.log( "Distance : %8.3f    mm:" % frame['distance'])
            LogServer.log("Osc start: %8.3f   deg:" % start_pos)
            LogServer.log("Osc   end: %8.3f   deg:" % end_pos)
            LogServer.log("Osc  velo: %8.3f deg/s:" % velo)
            
            # Read and save image
            self.detector.set_header(header)
            self.detector.save()
            LogServer.log("File name: %s" % frame['file_name'])
            gobject.idle_add(self.emit, 'new-image', frame['index'], frame['file_name'])
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
        
class SNLDataCollector(DataCollector):
    def __init__(self, run_list=None, skip_collected=True):
        DataCollector.__init__(self, run_list, skip_collected)
        self.last_run = 0
        #self.distance = beamline['motors']['detector_dist']              
    def run(self, widget=None):
        self.detector = MarCCD2('BL08ID1:CCD')
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
                return
            frame = self.run_list[self.pos]
            self.pos += 1
            if frame['saved'] and self.skip_collected:
                LogServer.log( 'Skipping %s' % frame['file_name'])
                continue
            velo = frame['delta'] / float(frame['time'])
            start_pos = frame['start_angle']
            end_pos = start_pos + frame['delta']
            
            # prepare image header
            header['delta'] = frame['delta']
            header['directory'], header['filename'] = os.path.split(frame['file_name'])
            header['directory'] = header['directory']+'\0'
            header['filename'] = header['filename']+'\0'
            header['distance'] = frame['distance'] 
            header['time'] = frame['time']
            header['frame_number'] = frame['frame_number']
            header['wavelength'] = keV_to_A(frame['energy'])
            header['energy'] = frame['energy']
            header['prefix'] = frame['prefix']
            header['start_angle'] = frame['start_angle']
            
            self.detector.set_header(header)
            self.detector.start()
            
            # Place holder for gonio scan and shutter opening            
            LogServer.log("Image Collected: %s" % frame['file_name'])
            gobject.idle_add(self.emit, 'new-image', frame['index'], frame['file_name'])
            
            # Notify progress
            fraction = float(self.pos) / len(self.run_list)
            gobject.idle_add(self.emit, 'progress', fraction)
            
        # Wrap things up    
        gobject.idle_add(self.emit, 'done')
        gobject.idle_add(self.emit, 'progress', 1.0)
        
gobject.type_register(DataCollector)
