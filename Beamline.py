#!/usr/bin/env python


from Motor import *
from Detector import *
from PseudoMotor import *
from VideoSource import *
from Shutter import *

from ConfigParser import ConfigParser
import string

BEAMLINE = 'bl08id'
beamline = {}

def initialize():
    global beamline
    parser = ConfigParser()
    filename =sys.path[0] + "/data/%s.dat" % BEAMLINE
    parser.read(filename)

    mode = parser.get('config','mode')
    if mode == 'simulation':
        print "Entering Simulation Mode"
        Motor       = FakeMotor 
        OldMotor    = FakeMotor 
        EnergyMotor = DCMEnergy
        Variable    = Positioner 
        VideoCamera = FakeCamera
        MCA         = FakeMCA
        Shutter     = FakeShutter
        
    else:
        print "Entering Live Mode"
        Motor       = CLSMotor 
        OldMotor    = FakeMotor #OldCLSMotor 
        EnergyMotor = DCMEnergy
        Variable    = EpicsPV 
        VideoCamera = EpicsCamera
        MCA         = EpicsMCA
        Shutter     = FakeShutter
        
                
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

    print 'setting up Shutters'
    beamline['shutters'] = {}
    if 'shutters'  in parser.sections():
        for item in parser.options('shutters'):
            item = string.strip(item)
            pv = string.strip( parser.get('shutters', item) )            
            beamline['shutters'][item] = Shutter(pv)
            print '...', item
        
    #provide some reasonable values for simulation     
    # 2theta not yet implemented so using simulator always    
    beamline['motors']['detector_2th'] = FakeMotor('2th')   
    beamline['motors']['detector_dist'] =   beamline['motors']['detector_z']
    if mode == 'simulation':
        beamline['variables']['beam_x'].move_to(320)
        beamline['variables']['beam_y'].move_to(240)
        beamline['motors']['zoom'].move_to(3)
        beamline['motors']['energy'].move_to(12.65)
        beamline['motors']['detector_dist'].set_position(200)
        beamline['motors']['gslits_hgap'].move_to(0.3)
        beamline['motors']['gslits_vgap'].set_position(0.3)
        
initialize()
print "Beamline Loaded"
