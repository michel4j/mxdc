from bcm.engine.scripting import Script

class SetMountMode(Script):
    description = "Prepare for manual sample mounting."
    def run(self):
        #if not self.beamline.automounter.is_busy():
        safe_distance = 700
        if self.beamline.detector_z.get_position() < safe_distance:
            self.beamline.detector_z.move_to(safe_distance)
        safe_beamstop = self.beamline.config['safe_beamstop']
        self.beamline.goniometer.set_mode('MOUNTING', wait=True)
        self.beamline.beamstop_z.move_to(safe_beamstop)
        self.beamline.cryojet.nozzle.open()
        self.beamline.beamstop_z.wait()
        
        
        
class SetCenteringMode(Script):
    description = "Prepare for crystal centering."
    def run(self):
        if not self.beamline.automounter.is_busy():
            safe_beamstop = self.beamline.config['default_beamstop']
            safe_distance = 300
            
            mount_distance = 700 # Should be the same as the 'safe_distance' from SetMountMode
            
            self.beamline.beamstop_z.move_to(safe_beamstop, wait=True)
            self.beamline.goniometer.set_mode('CENTERING', wait=False)
            if abs(self.beamline.detector_z.get_position() - mount_distance) < 1:
                self.beamline.detector_z.move_to(safe_distance)
            self.beamline.cryojet.nozzle.close()
        

class SetCollectMode(Script):
    description = "Prepare for data collection."
    def run(self):
        if not self.beamline.automounter.is_busy():
            self.beamline.goniometer.set_mode('COLLECT', wait=True)
            beamstop_pos = self.beamline.config['default_beamstop']
            self.beamline.beamstop_z.move_to(beamstop_pos)
            self.beamline.cryojet.nozzle.close()

class SetBeamMode(Script):
    description = "Switch to Beam Inspection Mode."
    def run(self):
        if not self.beamline.automounter.is_busy():
            self.beamline.goniometer.set_mode('BEAM', wait=True)
            #FIXME: should we open the shutter here? Who is responsible for
            # closing it

        
myscript0 = SetCenteringMode()
myscript1 = SetMountMode()
myscript2 = SetCollectMode()
myscript3 = SetBeamMode()
