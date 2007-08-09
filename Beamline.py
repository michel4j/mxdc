#!/usr/bin/env python


from Motor import *
from Detector import *
from PseudoMotor import *
from VideoSource import *

from ConfigParser import ConfigParser
import string

BEAMLINE = 'BL08ID'
beamline = {}

def initialize():
    global beamline
    parser = ConfigParser()
    parser.read("data/%s.dat" % BEAMLINE)

    mode = parser.get('config','mode')
    if mode == 'simulation':
        print "Entering Simulation Mode"
        Motor       = FakeMotor 
        OldMotor    = FakeMotor 
        EnergyMotor = DCMEnergy
        Variable    = Positioner 
        VideoCamera = FakeCamera
        MCA         = FakeMCA
        
    else:
        print "Entering Live Mode"
        Motor       = CLSMotor 
        OldMotor    = OldCLSMotor 
        EnergyMotor = DCMEnergy
        Variable    = EpicsPV 
        VideoCamera = EpicsCamera
        MCA         = EpicsMCA
        
                
    beamline['motors'] = {}
    beamline['detectors'] = {}
    print 'Setting up Motors'
    if 'motors' in parser.sections():
        for item in parser.options('motors'):
            pv = string.strip( parser.get('motors', item) )
            item = string.strip(item)
            beamline['motors'][item] = Motor(pv)
            print '...', item
    if 'old_motors' in parser.sections():
        for item in parser.options('old_motors'):
            pv = string.strip( parser.get('old_motors', item) )
            item = string.strip(item)
            beamline['motors'][item] = OldMotor(pv)
            print '...', item
    energy_motors = [beamline['motors']['bragg'],
                     beamline['motors']['c2_t1'],
                     beamline['motors']['c2_t2']]
    beamline['motors']['energy'] = EnergyMotor( energy_motors )            
    twotheta_motors = [beamline['motors']['detector_z'],
                     beamline['motors']['detector_y1'],
                     beamline['motors']['detector_y2']]
    #beamline['motors']['detector_2th'] = TwoThetaMotor( twotheta_motors )            
    #beamline['motors']['detector_dist'] = DistanceMotor( twotheta_motors )            
    print '...', 'energy'
    print 'setting up MCA and attenuator'
    if 'misc' in parser.sections():
        if 'attenuator' in parser.options('misc'):
            bits = parser.get('misc', 'attenuator').split('|')
            bit_positioners = []
            for bit in bits:
                bit_positioners.append( Variable(bit) )
            beamline['attenuator'] = Attenuator(bit_positioners, beamline['motors']['energy'])
            print '... attenuator'
        if 'mca' in parser.options('misc'):
            pv =  parser.get('misc', 'mca')
            beamline['detectors']['mca'] = MCA(pv)
            print '... mca'      
    print 'setting up Cameras'
    beamline['cameras'] = {}
    if 'cameras' in parser.sections():
        for item in parser.options('cameras'):
            pv = string.strip( parser.get('cameras', item) )            
            beamline['cameras'][item] = VideoCamera(pv)
            print '...', item           
        

    print 'setting up Other Variables'
    beamline['variables'] = {}
    if 'variables' in parser.sections():
        for item in parser.options('variables'):
            item = string.strip(item)
            pv = string.strip( parser.get('variables', item) )            
            beamline['variables'][item] = Variable(pv)
            print '...', item
    # 2theta not yet implemented so using simulator always    
    beamline['motors']['detector_2th'] = FakeMotor('2th')        

initialize()
print "Beamline Loaded"
