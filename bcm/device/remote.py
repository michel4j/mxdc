'''
Created on Nov 10, 2009

@author: michel
'''
from motor import *
from misc import *
from counter import *
from bcm.service.remote_device import *

remote_registry.register([IMotor], IDeviceServer, '', MotorServer)
remote_registry.register([interfaces.IJellyable], IDeviceClient, 'MotorServer', MotorClient)