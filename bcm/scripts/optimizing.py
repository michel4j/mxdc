from bcm.engine.scripting import Script

class RestoreBeam(Script):
    description = 'Restore the beam after injection.'
    def run(self):
        if not self.beamline.photon_shutter.get_state():
            self.beamline.photon_shutter.open()
        pos  = self.beamline.monochromator.energy.get_position()
        self.beamline.monochromator.energy.move_to(pos, wait=True, force=True)
        return

rest_script1 = RestoreBeam()
