#!/usr/bin/env python

from Motor import CLSMotor
mfile = open('BL08ID_motors.txt')
motordata = mfile.readlines()
mfile.close()

motors = {}
for motor in motordata:
	[name,key] = motor.split()
	motors[key] = CLSMotor(name)
	
keys = motors.keys()
keys.sort()
for key in keys:
	motors[key].show_all()
	print "---------------"
