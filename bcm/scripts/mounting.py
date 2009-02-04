from bcm.engine.scripting import Script

class PrepareMounting(Script):
    def run(self):
        safe_distance = 700
        safe_beamstop = 45      
        self.beamline.devices['det_z'].move_to(safe_distance, wait=True)
        self.beamline.devices['bst_z'].move_to(safe_beamstop, wait=True)
        

class FinishedMounting(Script):
    def run(self):
        safe_distance = 300
        safe_beamstop = 30
        self.beamline.devices['bst_z'].move_to(safe_beamstop, wait=True)
        self.beamline.devices['det_z'].move_to(safe_distance, wait=True)
        

myscript1 = PrepareMounting()
myscript2 = FinishedMounting()