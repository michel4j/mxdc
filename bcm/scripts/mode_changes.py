from bcm.engine.scripting import Script

class SetMountMode(Script):
    description = "Prepare for manual sample mounting."
    def run(self):
        safe_distance = self.beamline.config['safe_distance']
        self.beamline.config['_prev_distance'] = self.beamline.detector_z.get_position()
        if self.beamline.detector_z.get_position() < safe_distance:
            self.beamline.detector_z.move_to(safe_distance)
        self.beamline.goniometer.set_mode('MOUNTING', wait=True)
        self.beamline.beamstop_z.move_to(self.beamline.config['safe_beamstop'])
        self.beamline.cryojet.nozzle.open()
        self.beamline.beamstop_z.wait()
        
        
        
class SetCenteringMode(Script):
    description = "Prepare for crystal centering."
    def run(self):
        if not self.beamline.automounter.is_busy():
            self.beamline.cryojet.nozzle.close()
            self.beamline.goniometer.set_mode('CENTERING', wait=True)
            safe_beamstop = self.beamline.config['default_beamstop']
            restore_distance = self.beamline.config.get('_prev_distance', self.beamline.config['default_distance'])
            if self.beamline.detector_z.get_position() > restore_distance:
                self.beamline.detector_z.move_to(restore_distance, wait=False)
            #self.beamline.beamstop_z.move_to(safe_beamstop, wait=False)
        

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
