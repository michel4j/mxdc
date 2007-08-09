#!/usr/bin/env python

import sys, time, copy
import gtk, gobject
from pylab import load
import EpicsCA
from Motor import AbstractMotor
from Utils import *
import numpy

class DCMEnergy(AbstractMotor):
    def __init__(self, motors=[], timeout=1.):
        AbstractMotor.__init__(self, 'DCM')
        if len(motors)<3:
            raise self.MotorException, " bragg, T1 and T2 motors must be specified"
        self.bragg = motors[0].copy()
        self.T1 = motors[1].copy()
        self.T2 = motors[2].copy()
        self.bragg_only = True
        self.bragg.connect('changed',self._signal_change)
        self.last_moving = self.is_moving()
        self.units = 'keV'
        gobject.timeout_add(150, self._queue_check)
        

        
    def set_mask(self, mask):
        if mask[1] == 0:
            self.bragg_only = True
        
        
    def _calc_targets(self, theta, offset=30.0):
        self.t1_target = offset / (2.0 * numpy.sin( radians(theta) ))
        self.t2_target = offset / (2.0 * numpy.cos( radians(theta) ))
        self.bragg_target = theta
     
    def copy(self):
        tmp = DCMEnergy(self.bragg.copy(), self.T1.copy(), self.T2.copy())
        tmp.set_bragg_only(self.bragg_only)
        #tmp = copy.deepcopy(self)
        return tmp
        
    def _signal_change(self, widget, value):
        gobject.idle_add(self.emit,'changed', bragg_to_keV(value))
    
                    
    def _queue_check(self):
        gobject.idle_add(self._check_change)
        return True
        
    def _check_change(self):
        self.moving = self.is_moving()
        if self.moving:
            if self.last_moving != self.moving:
                gobject.idle_add(self.emit,'moving')
        elif self.last_moving != self.moving:
            gobject.idle_add(self.emit,'stopped')
            print "%s stopped at %f" % (self.name, self.get_position() )
        self.last_moving = self.moving
        return False

    def move_to(self, val, wait=False):
        print "%s moving to %f" % (self.get_name(), val)
        self._calc_targets( keV_to_bragg(val) )
        self.bragg.move_to(self.bragg_target)
        if not self.bragg_only:
            self.T1.move_to(self.t1_target)
            self.T2.move_to(self.t2_target)
        if wait:
            try:
                self.wait(start=True,stop=True)
            except  KeyboardInterrupt:
                self.stop()

    def get_position(self):
        return bragg_to_keV( self.bragg.get_position() )

    def set_position(self, val):
        pass
        
    def move_by(self,val, wait=False):
        val = float(val) + self.bragg.get_position()
        self.move_to(val, wait)
                
    def wait(self, start=False,stop=True,poll=0.01):
        if (start):
            while not self.is_moving():
                time.sleep(poll)                
        if (stop):
            while self.is_moving():
                time.sleep(poll)
                
    def is_moving(self):
        if self.bragg_only:
            if self.bragg.is_moving():
                return True
            else:
                return False
        else:
            if self.bragg.is_moving() or self.T1.is_moving() or self.T2.is_moving():
                return True
            else:
                return False
    def get_id(self):
        return "%s|%s|%s" % (self.bragg.get_id(), self.T1.get_id(), self.T2.get_id())
    
    def get_name(self):
        return 'DCM Energy'
        
    def stop(self):
        self.bragg.stop()
        if not self.bragg_only:
            self.T1.stop()
            self.T2.stop()
