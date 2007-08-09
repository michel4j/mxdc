#!/usr/bin/env python

import sys, time
import gtk, gobject
import threading
import numpy

class DataCollector(threading.Thread, gobject.GObject):
    __gsignals__ = {}
    __gsignals__['new-image'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_INT,gobject.TYPE_STRING))
    __gsignals__['done'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['paused'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,))
    __gsignals__['stopped'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [])
    __gsignals__['log'] = (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,))
    
    def __init__(self, run_list=None):
        threading.Thread.__init__(self)
        gobject.GObject.__init__(self)
        self.run_list = run_list
        self.paused = False
        self.stopped = False
        self.skip_collected = True
        
    def setup(self, run_list, skip=True):
        self.run_list = run_list
        self.skip_collected = skip
        return
        
    def _logtext(self,s):
        text = time.strftime('%Y/%m/%d %H:%M:%S ') + s
        print text
        gobject.idle_add(self.emit, 'log', text)
        
    def run(self, widget=None):
        self.pos = 0
        while self.pos < len(self.run_list) :
            if self.paused:
                gobject.idle_add(self.emit, 'paused', True)
                while self.paused and not self.stopped:
                    time.sleep(0.5)
                gobject.idle_add(self.emit, 'paused', False)
            if self.stopped:
                gobject.idle_add(self.emit, 'stopped')
                return
            frame = self.run_list[self.pos]
            self.pos += 1
            if frame['saved'] and self.skip_collected:
                self._logtext( 'Skipping %s' % frame['file_name'])
                continue
            velo = frame['delta'] / float(frame['time'])
            start_pos = frame['start_angle']
            end_pos = start_pos + frame['delta']
            time.sleep(frame['time'])
            self._logtext( "%04d ------------------------------------------" % self.pos)
            self._logtext( "Energy   : %8.3f   keV:" % frame['energy'])
            self._logtext( "Distance : %8.3f    mm:" % frame['distance'])
            self._logtext("Osc start: %8.3f   deg:" % start_pos)
            self._logtext("Osc   end: %8.3f   deg:" % end_pos)
            self._logtext("Osc  velo: %8.3f deg/s:" % velo)
            self._logtext("File name: %s " % frame['file_name'])
            gobject.idle_add(self.emit, 'new-image', frame['index'], frame['file_name'])
            
        gobject.idle_add(self.emit, 'done')

    def set_position(self,pos):
        self.pos = pos
        
    def pause(self):
        self.paused = True
        
    def resume(self):
        self.paused = False
    
    def stop(self):
        self.stopped = True
        
gobject.type_register(DataCollector)
