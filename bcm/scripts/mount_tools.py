from bcm.engine.scripting import Script

class prepare_for_mounting(Script):
    def run(self):
        safe_distance = 700
        safe_beamstop = 45      
        self.beamline.devices['det_z'].move_to(safe_distance, wait=True)
        self.beamline.devices['bst_z'].move_to(safe_beamstop, wait=True)
prepare = prepare_for_mounting()

class restore_for_collecting(Script):
    def run(self):
        safe_distance = 300
        safe_beamstop = 30
        safe_distance = 700
        safe_beamstop = 45      
        self.beamline.devices['bst_z'].move_to(safe_beamstop, wait=True)
        self.beamline.devices['det_z'].move_to(safe_distance, wait=True)
restore = restore_for_collecting()

