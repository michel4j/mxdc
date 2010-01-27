from bcm.engine.centering import auto_center_loop, auto_center_crystal
from bcm.engine.scripting import Script


class CenterSample(Script):

    def run(self, crystal=False):
        if crystal:
            results = auto_center_crystal()
        else:
            results = auto_center_loop()
        return results

script1 = CenterSample()
