from bcm.engine.scripting import Script

class SetMountMode(Script):
    description = "Prepare for sample mounting."
    def run(self):
        safe_distance = 700
        safe_beamstop = 45
        self.beamline.detector_z.move_to(safe_distance)
        self.beamline.beamstop_z.move_to(safe_beamstop)
        self.beamline.goniometer.set_mode('MOUNTING', wait=True)
        self.beamline.beamstop_z.wait()
        self.beamline.detector_z.wait()
        
        
class SetCenteringMode(Script):
    description = "Prepare for crystal centering."
    def run(self):
        safe_beamstop = 30
        self.beamline.goniometer.set_mode('CENTERING', wait=True)
        self.beamline.registry['beamstop_z'].move_to(safe_beamstop)
        

class SetCollectMode(Script):
    description = "Prepare for data collection."
    def run(self):
        self.beamline.goniometer.set_mode('COLLECT', wait=True)
        
myscript0 = SetCenteringMode()
myscript1 = SetMountMode()
myscript2 = SetCollectMode()