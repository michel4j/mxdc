from bcm.engine.scripting import Script

class SetMountMode(Script):
    description = "Prepare for manual sample mounting."
    def run(self):
        safe_distance = 700
        safe_beamstop = self.beamline.config['safe_beamstop']
        self.beamline.detector_z.move_to(safe_distance)
        self.beamline.goniometer.set_mode('MOUNTING', wait=True)
        self.beamline.beamstop_z.move_to(safe_beamstop)
        self.beamline.cryojet.nozzle.open()
        self.beamline.beamstop_z.wait()
        
        
        
class SetCenteringMode(Script):
    description = "Prepare for crystal centering."
    def run(self):
        safe_beamstop = self.beamline.config['default_beamstop']
        save_distance = 300
        self.beamline.goniometer.set_mode('CENTERING', wait=True)
        self.beamline.beamstop_z.move_to(safe_beamstop)
        self.beamline.detector_z.move_to(save_distance)
        self.beamline.cryojet.nozzle.close()
        

class SetCollectMode(Script):
    description = "Prepare for data collection."
    def run(self):
        self.beamline.goniometer.set_mode('COLLECT', wait=True)
        beamstop_pos = self.beamline.config['default_beamstop']
        self.beamline.beamstop_z.move_to(beamstop_pos)
        self.beamline.cryojet.nozzle.close()

class SetBeamMode(Script):
    description = "Switch to Beam Inspection Mode."
    def run(self):
        self.beamline.goniometer.set_mode('BEAM', wait=True)
        #FIXME: should we open the shutter here? Who is responsible for
        # closing it

        
myscript0 = SetCenteringMode()
myscript1 = SetMountMode()
myscript2 = SetCollectMode()
myscript3 = SetBeamMode()