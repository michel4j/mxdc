from bcm.engine.scripting import Script

class SetMountMode(Script):
    description = "Prepare for manual sample mounting."
    def run(self):
        if not (self.beamline.automounter.is_busy() or self.beamline.automounter.is_preparing()):
            safe_distance = self.beamline.config['safe_distance']
            if self.beamline.detector_z.get_position() < safe_distance:
                self.beamline.detector_z.move_to(safe_distance)

            self.beamline.goniometer.set_mode('MOUNTING', wait=True)
            self.beamline.beamstop_z.move_to(self.beamline.config['safe_beamstop'])
            self.beamline.cryojet.nozzle.open()
            self.beamline.beamstop_z.wait()
              
        
class SetCenteringMode(Script):
    description = "Prepare for crystal centering."
    def run(self):
        if not (self.beamline.automounter.is_busy() or self.beamline.automounter.is_preparing()):
            self.beamline.cryojet.nozzle.close()
            default_beamstop = self.beamline.config['default_beamstop']
            
            # needed by 08ID
            if self.beamline.beamstop_z.get_position() < default_beamstop:
                self.beamline.beamstop_z.move_to(default_beamstop, wait=True)
                
            self.beamline.goniometer.set_mode('CENTERING', wait=False)
            restore_distance = self.beamline.distance.target_changed_state[1]
            if restore_distance and restore_distance < self.beamline.detector_z.get_position():
                self.beamline.detector_z.move_to(restore_distance, wait=False)
    
    def run_after(self):
        default_beamstop = self.beamline.config['default_beamstop']
        self.beamline.goniometer.wait(start=False, stop=True, timeout=20)
        self.beamline.beamstop_z.move_to(default_beamstop, wait=False)
        

class SetCollectMode(Script):
    description = "Prepare for data collection."
    def run(self):
        if not (self.beamline.automounter.is_busy() or self.beamline.automounter.is_preparing()):
            self.beamline.goniometer.set_mode('COLLECT', wait=True)
            self.beamline.cryojet.nozzle.close()

class SetBeamMode(Script):
    description = "Switch to Beam Inspection Mode."
    def run(self):
        if not (self.beamline.automounter.is_busy() or self.beamline.automounter.is_preparing()):
            self.beamline.goniometer.set_mode('BEAM', wait=True)
            #FIXME: should we open the shutter here? Who is responsible for
            # closing it

class SetFreezeMode(Script):
    description = "Orient Sample for Manual Freezing."
    def run(self):
        if not (self.beamline.automounter.is_busy() or self.beamline.automounter.is_preparing()):
            safe_distance = self.beamline.config['safe_distance']
            if self.beamline.detector_z.get_position() < safe_distance:
                self.beamline.detector_z.move_to(safe_distance)

            self.beamline.goniometer.set_mode('MOUNTING', wait=True)
            self.beamline.beamstop_z.move_to(self.beamline.config['safe_beamstop'], wait=True)
            if 'kappa' in self.beamline.registry:
                self.beamline.omega.move_to(32.5, wait=True)
                self.beamline.chi.move_to(45)

myscript0 = SetCenteringMode()
myscript1 = SetMountMode()
myscript2 = SetCollectMode()
myscript3 = SetBeamMode()
myscript4 = SetFreezeMode()
