from bcm.engine.scripting import Script

class OptimizeBeam(Script):
    def run(self):
        self.beamline.mostab.start()
        self.beamline.mostab.wait()
        return


opt_script1 = OptimizeBeam()
