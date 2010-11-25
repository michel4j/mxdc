from bcm.engine.scripting import Script

class SetMountMode(Script):
    description = "Prepare for sample mounting."
    def run(self):
        safe_distance = 700
        safe_beamstop = 80
        self.beamline.distance.move_to(safe_distance)
        self.beamline.goniometer.set_mode('MOUNTING', wait=True)
        self.beamline.beamstop_z.move_to(safe_beamstop)
        self.beamline.beamstop_z.wait()
        self.beamline.distance.wait()
        
        
class SetCenteringMode(Script):
    description = "Prepare for crystal centering."
    def run(self):
        safe_beamstop = 50
        save_distance = 300
        self.beamline.goniometer.set_mode('CENTERING', wait=True)
        self.beamline.beamstop_z.move_to(safe_beamstop)
        self.beamline.distance.move_to(save_distance)
        

class SetCollectMode(Script):
    description = "Prepare for data collection."
    def run(self):
        self.beamline.goniometer.set_mode('COLLECT', wait=True)
        
myscript0 = SetCenteringMode()
myscript1 = SetMountMode()
myscript2 = SetCollectMode()
