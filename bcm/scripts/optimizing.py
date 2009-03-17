from bcm.engine.scripting import Script

class OptimizeBeam(Script):
    def run(self):
        self.beamline.registry['mostab'].start()
        self.beamline.registry['mostab'].wait()
        return


opt_script1 = OptimizeBeam()
