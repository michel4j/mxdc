'''
Created on Nov 10, 2009

@author: michel
'''
from motor import *
from misc import *
from counter import *
from bcm.service.remote_device import *
from bcm import registry
from twisted.spread import interfaces

# Motors
registry.register([IMotor], IDeviceServer, '', MotorServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'MotorServer', MotorClient)

# Positioners
registry.register([IPositioner], IDeviceServer, '', PositionerServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'PositionerServer', PositionerClient)