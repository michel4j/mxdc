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
from Dialogs import messagedialog

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
        self.beam_status = beamline['variables']['ring_status'].get_position()
        self.beam_current = beamline['detectors']['current'].get_value()
        
    def setup(self, run_list, skip_collected=True):
        self.run_list = run_list
        self.skip_collected = skip_collected
        return
    
    def beam_changed(self):
        status = beamline['variables']['ring_status'].get_position()
        current = beamline['detectors']['current'].get_value()
        if (status != self.beam_status) and self.beam_status == 4:
            return True
        else:
            if current == 0.0 and self.beam_current > 5.0:
                return True
            else:
                return False

    def run(self, widget=None):
        CA.thread_init()
        self.detector = beamline['detectors']['ccd']
        self.gonio = beamline['goniometer']
        self.shutter = beamline['shutters']['xbox_shutter']
        
        self.shutter.close()
        time.sleep(0.1) # small delay to make sure shutter is closed
        self.detector.acquire_bg()
        self.pos = 0
        header = {}
        while self.pos < len(self.run_list) :
            if self.beam_changed():
                self.paused = True
                LogServer.log("No beam: Data collection paused! Please resume when the beam is up again")
                # place holder for displaying a mesage box for the user
                #gobject.timeout_add(0, messagedialog, 
                #   gtk.MESSAGE_WARNING,
                #   'Data Collection Paused',
                #   'Data Collection has been paused because the state of the storage ring has changed. Please resume data collection once the beam is ready')
                
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
            
            
            # Prepare image header
            header['delta'] = frame['delta']
            header['filename'] = frame['file_name']
            header['directory'] = frame['remote_directory']
            header['distance'] = frame['distance'] 
            header['time'] = frame['time']
            header['frame_number'] = frame['frame_number']
            header['wavelength'] = keV_to_A(frame['energy'])
            header['energy'] = frame['energy']
            header['prefix'] = frame['prefix']
            header['start_angle'] = frame['start_angle']
            
            # Check and prepare beamline
            if abs(beamline['motors']['detector_dist'].get_position() - frame['distance']) > 1e-2:
                beamline['motors']['detector_dist'].move_to(frame['distance'])
            if abs(beamline['motors']['energy'].get_position() - frame['energy']) > 1e-4:
                beamline['motors']['energy'].set_mask([1,0,0])
                beamline['motors']['energy'].move_to(frame['energy'])
            beamline['motors']['detector_dist'].wait()
            beamline['motors']['energy'].wait()
            beamline['motors']['energy'].set_mask([1,1,1])
            gonio_data = {
                'time': frame['time'],
                'delta' : frame['delta'],
                'start_angle': frame['start_angle'],                
            }
            self.gonio.set_params(gonio_data)
            
            tf = time.time()
            tI = int(tf)
            #print '%s:%0.0f starting acquire' % ( time.strftime('%H:%M:%S', time.localtime(tf) ), 10*(tf - tI) )
            self.detector.start()            
            self.detector.set_header(header)
            #print 'starting gonio scan'
            self.gonio.scan()

            LogServer.log( "%04d ------------------------------------------" % self.pos)
            
            # Read and save image
            #print 'saving image'
            self.detector.save()

            tf = time.time()
            tI = int(tf)
            #print '%s:%0.0f image saved' % ( time.strftime('%H:%M:%S', time.localtime(tf) ), 10*(tf - tI) )
            
            # Notify new image
            LogServer.log("Image Collected: %s" % frame['file_name'])
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
            header['filename'] = frame['file_name']
            header['directory'] = frame['directory']
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
