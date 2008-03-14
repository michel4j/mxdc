#!/usr/bin/env python

import sys, time
import gtk, gobject
from pylab import load
from Motors import *
from Utils import *
import numpy
from numpy import sin, cos, tan, arcsin, arccos, arctan

class PseudoMotor(AbstractMotor):
    def __init__(self, motors=[],timeout=1.):
    	AbstractMotor.__init__(self, name='Pseudo Motor')
        if len(motors) < 1:
            raise self.MotorException, " list of motors must be specified"
        self.motors = motors
        self._setup()
        self.mask = []
        for i in range(len(self.motors)):
            self.mask.append(1)
        gobject.timeout_add(150, self._queue_check)
        
    def get_position(self):
        return self._calc_position()                

    def move_to(self, val, wait=False):
        if self.get_position() == val:
            return
        if not self.is_valid():
            LogServer.log ( "%s is not calibrated. Move cancelled!" % (self.get_name()) )
            gobject.idle_add(self.emit,"valid", False)
            return False
        LogServer.log( "%s moving to %f %s" % (self.get_name(), val, self.units))
        self._calc_targets( val )
        for motor, movable, target in zip( self.motors, self.mask, self.targets):
            if movable == 1:
                motor.move_to(target)
        if wait:
            self.wait(start=True,stop=True)
        
    def move_by(self,val, wait=False):
        val += self.get_position()
        self.move_to(val, wait)
        
    def set_mask(self, mask=[]):
        if len(mask) != len(self.motors):
            raise self.MotorException, "The mask must be the same length as number of motors"
        self.mask = mask
        
    def is_moving(self):
        moving = False
        for motor in self.motors:
            if motor.is_moving():
                moving = True
        return moving

    def is_valid(self):
        invalid = False
        for motor, movable in zip( self.motors, self.mask):
            if (not motor.is_valid()) and movable==1:
                invalid =True
        return not invalid
        
    def stop(self):
        for motor, movable in zip( self.motors, self.mask):
            if movable == 1 and motor.is_moving():
                motor.stop()

    # The following methods must be overwritten in the derived class        
    def _setup(self):
        self.units = ''
        
    def _calc_targets(self, theta):
        raise self.MotorException, " You must implement the target calculation for derived classes"
    
    def _calc_position(self):
        raise self.MotorException, " You must implement the target calculation for derived classes"              

    def copy(self):
	    raise self.MotorException, " You must implement the copy operation for derived classes"
		
    

class DCMEnergy(PseudoMotor):
    def __init__(self, motors=[], timeout=1.):
        PseudoMotor.__init__(self, motors=motors)
                
    def _setup(self):
        self.units = 'keV'
        self.name = 'DCM Energy'
        
    def _calc_targets(self, val):
        theta = keVToBragg(val)
        offset = 30.0
        bragg_target = theta
        t1_target = offset / (2.0 * numpy.sin( radians(theta) ))
        t2_target = offset / (2.0 * numpy.cos( radians(theta) ))
        self.targets = [bragg_target, t1_target, t2_target]
             
    def _calc_position(self):
        bragg = self.motors[0].get_position()
        if bragg:
            return braggToKeV( bragg )
        else:
            return -99

    def copy(self):
        motors = []
        for motor in self.motors:
            motors.append( motor.copy() )
        tmp = DCMEnergy(motors)
        tmp.set_mask(self.mask)
        return tmp
        
class TwoThetaMotor(PseudoMotor):
    def __init__(self, motors=[], timeout=1.):
        PseudoMotor.__init__(self, motors=motors)

    def _setup(self):
        self.units = 'deg'
        self.name = 'Two Theta Motor'
        self.A = 270
        self.B = 370.11
        self.C = 176.29
        self.safety_margin = 400.0 #The current limit 
                
    def _calc_targets(self, val):
        theta = radians(val)
        ccdz = self.motors[0].get_position()
        ccdy1 = self.motors[1].get_position()
        ccdy2 = self.motors[2].get_position()
        
        cur_theta = radians( self._calc_position() )
        D = (ccdy1 - self.B)*sin(cur_theta) + (ccdz + self.C)*cos(cur_theta)-self.C
        L = (-ccdz-self.C)*sin(cur_theta)+(ccdy1-self.B)*cos(cur_theta)+self.B
        
        ccdz_target = (self.B - L)*sin(theta) + (self.C + D)*cos(theta) - self.C
        ccdy1_target = (self.C + D)*sin(theta) + (L-self.B)*cos(theta) + self.B
        ccdy2_target = (self.C + D)*sin(theta) + (L-self.B)*cos(theta) + self.B + self.A*tan(theta)

        if self._check_limits(val):
            self.targets = [ccdz_target, ccdy1_target, ccdy2_target]
        else:
            self.targets = [ccdz, ccdy1, ccdy2]

    def _check_limits(self, val):
        ccdz = self.motors[0].get_position()
        cur_theta = radians( self._calc_position() )
        approach = - ((self.B+225/2.0)*sin(cur_theta) + self.C * cos(cur_theta) - ccdz - self.C)
        if approach < self.safety_margin:
            return False
        else:
            return True 
                   
    def _calc_position(self):
        ccdz = self.motors[0].get_position()
        ccdy1 = self.motors[1].get_position()
        ccdy2 = self.motors[2].get_position()
        val = arctan( (ccdy2 - ccdy1)/self.A)
        return degrees( val )

    def copy(self):
        motors = []
        for motor in self.motors:
            motors.append( motor.copy() )
        tmp = TwoThetaMotor(motors)
        tmp.set_mask(self.mask)
        return tmp

class DistanceMotor(PseudoMotor):
    def __init__(self, motors=[], timeout=1.):
        PseudoMotor.__init__(self, motors=motors)

    def _setup(self):
        self.units = 'mm'
        self.name = 'Detector Distance Motor'
        self.A = 270
        self.B = 370.11
        self.C = 176.29
        self.safety_margin = 400.0 #The current limit 
                
    def _check_limits(self, val):
        cur_theta = arctan( (self.targets[1] - self.targets[2])/self.A )
        approach = - ((self.B+225/2.0)*sin(cur_theta) + self.C * cos(cur_theta) - self.targets[0] - self.C)
        if approach < self.safety_margin:
            return False
        else:
            return True 
    
    def _calc_targets(self, val):
        ccdz = self.motors[0].get_position()
        ccdy1 = self.motors[1].get_position()
        ccdy2 = self.motors[2].get_position()
        
        cur_theta = arctan( (ccdy2 - ccdy1)/self.A )
        D = val
        L = (-ccdz-self.C)*sin(cur_theta)+(ccdy1-self.B)*cos(cur_theta)+self.B
        
        ccdz_target = (self.B - L)*sin(cur_theta) + (self.C + D)*cos(cur_theta) - self.C
        ccdy1_target = (self.C + D)*sin(cur_theta) + (L-self.B)*cos(cur_theta) + self.B
        ccdy2_target = (self.C + D)*sin(cur_theta) + (L-self.B)*cos(cur_theta) + self.B + self.A*tan(cur_theta)
        self.targets = [ccdz_target, ccdy1_target, ccdy2_target]
        if not self._check_limits(val):
            self.targets = [ccdz, ccdy1, ccdy2]
           
    def _calc_position(self):
        ccdz = self.motors[0].get_position()
        ccdy1 = self.motors[1].get_position()
        ccdy2 = self.motors[2].get_position()
        cur_theta = arctan( (ccdy2 - ccdy1)/self.A )
        val = (ccdy1 - self.B)*sin(cur_theta) + (ccdz + self.C)*cos(cur_theta)-self.C
        return val

    def copy(self):
        motors = []
        for motor in self.motors:
            motors.append( motor.copy() )
        tmp = DistanceMotor(motors)
        tmp.set_mask(self.mask)
        return tmp
           

               
