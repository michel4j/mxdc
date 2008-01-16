#!/usr/bin/env python

import os, sys
from Motors import *
from Detectors import *
from PseudoMotors import *
from VideoSources import *
from Shutters import *
from MarCCD import *
import xmlrpclib

from ConfigParser import ConfigParser
import string

BEAMLINE = 'bl08id'
beamline = {}

class Progress:
    def __init__(self, pbar):
        self.pbar = pbar
        self.count = 0
        self.total = 41

    def __call__(self, text=''):
        self.count +=  1
        fraction = float(self.count)/float(self.total)
        if fraction > 1.0:
            fraction = 1.0
        if self.pbar:
            self.pbar.set_fraction( fraction )
            self.pbar.set_text( 'Setting up: %s' % text )
        while gtk.events_pending():
            gtk.main_iteration()
            
def init_beamline(pbar=None):
    global beamline
    
    note_progress = Progress(pbar)
    parser = ConfigParser()
    if sys.path[0] == '':
        file_path = os.getcwd()
    else:
        file_path = sys.path[0]
    filename =file_path + "/data/%s.dat" % BEAMLINE
    parser.read(filename)

    mode = parser.get('config','mode')
    if mode == 'simulation':
        note_progress("Entering Simulation Mode")
        Motor       = FakeMotor 
        OldMotor    = FakeMotor 
        EnergyMotor = FakeMotor
        Variable    = Positioner 
        VideoCamera = FakeCamera
        MCA         = FakeMCA
        Shutter     = FakeShutter
        CCD         = CCDDetector
        
    else:
        note_progress( "Entering Live Mode")
        Motor       = CLSMotor 
        OldMotor    = OldCLSMotor 
        EnergyMotor = AutoEnergyMotor
        Variable    = EpicsPositioner 
        VideoCamera = EpicsCamera
        MCA         = EpicsMCA
        CCD         = MarCCD
        Shutter     = EpicsShutter
                
    beamline['motors'] = {}
    beamline['detectors'] = {}
    note_progress('Motors')
    if 'motors' in parser.sections():
        for item in parser.options('motors'):
            pv = string.strip( parser.get('motors', item) )
            item = string.strip(item)
            note_progress(item)
            beamline['motors'][item] = Motor(pv)
    if 'old_motors' in parser.sections():
        for item in parser.options('old_motors'):
            pv = string.strip( parser.get('old_motors', item) )
            item = string.strip(item)
            note_progress(item)
            beamline['motors'][item] = OldMotor(pv)
    energy_motors = [beamline['motors']['bragg'],
                     beamline['motors']['c2_t1'],
                     beamline['motors']['c2_t2']]
    beamline['motors']['energy'] = EnergyMotor()
    beamline['motors']['bragg_energy'] = DCMEnergy(energy_motors)
    twotheta_motors = [beamline['motors']['detector_z'],
                     beamline['motors']['detector_y1'],
                     beamline['motors']['detector_y2']]

    #beamline['motors']['detector_2th'] = TwoThetaMotor( twotheta_motors )            
    #beamline['motors']['detector_dist'] = DistanceMotor( twotheta_motors )            
    note_progress('energy')
    note_progress('Misc')
    if 'misc' in parser.sections():
        if 'attenuator' in parser.options('misc'):
            bits = parser.get('misc', 'attenuator').split('|')
            bit_positioners = []
            for bit in bits:
                bit_positioners.append( Variable(bit) )
            beamline['attenuator'] = Attenuator(bit_positioners, beamline['motors']['energy'])
            note_progress('attenuator')
        if 'mca' in parser.options('misc'):
            pv =  parser.get('misc', 'mca')
            beamline['detectors']['mca'] = MCA(pv)
            note_progress('mca')
        if 'gonio' in parser.options('misc'):
            pv =  parser.get('misc', 'gonio')
            beamline['goniometer'] = Gonio(pv)
            note_progress('goniometer')      
    
    note_progress('Cameras')
    beamline['cameras'] = {}
    if 'cameras' in parser.sections():
        if 'sample' in parser.options('cameras'):
            name = string.strip( parser.get('cameras', 'sample') )            
            beamline['cameras']['sample'] = VideoCamera(name)
            note_progress('Sample Camera')
        if 'hutch' in parser.options('cameras'):           
            name = string.strip( parser.get('cameras', 'hutch') )            
            beamline['cameras']['hutch'] = AxisServer(name)
            note_progress('Hutch Camera')
        
    note_progress('Detectors')
    if 'detectors' in parser.sections():
        for item in parser.options('detectors'):
            pv = string.strip( parser.get('detectors', item) )
            item = string.strip(item)
            beamline['detectors'][item] = EpicsDetector(pv)
            note_progress(item)

    note_progress('Other Variables')
    beamline['variables'] = {}
    if 'variables' in parser.sections():
        for item in parser.options('variables'):
            item = string.strip(item)
            pv = string.strip( parser.get('variables', item) )            
            beamline['variables'][item] = Variable(pv)
            note_progress(item)

    note_progress('Shutters')
    beamline['shutters'] = {}
    if 'shutters'  in parser.sections():
        for item in parser.options('shutters'):
            item = string.strip(item)
            pv = string.strip( parser.get('shutters', item) )            
            beamline['shutters'][item] = EpicsShutter(pv)
            note_progress(item)
    note_progress('CCD detectors')
    if 'ccds'  in parser.sections():
        for item in parser.options('ccds'):
            item = string.strip(item)
            pv = string.strip( parser.get('ccds', item) )  
            beamline['detectors']['ccd'] = CCD(pv)
               
    #provide some reasonable values for simulation     
    # 2theta not yet implemented so using simulator always    
    beamline['motors']['detector_2th'] = FakeMotor('2th')   
    beamline['motors']['detector_dist'] =   beamline['motors']['detector_z']
    for motor in ['sample_x','sample_y','sample_z', 'omega','bragg']:
        beamline['motors'][motor].set_calibrated(True)

    #MarCCD image server
    beamline['image_server'] = xmlrpclib.ServerProxy("http://cmcf-marccd.cs.cls:8888")

    if mode == 'simulation':
        beamline['variables']['beam_x'].move_to(320)
        beamline['variables']['beam_y'].move_to(240)
        beamline['motors']['zoom'].move_to(3)
        beamline['motors']['energy'].move_to(12.65)
        beamline['motors']['detector_dist'].set_position(200)
        beamline['motors']['gslits_hgap'].move_to(0.3)
        beamline['motors']['gslits_vgap'].set_position(0.3)
    note_progress('Beamline configured, launching MXDC')
    
