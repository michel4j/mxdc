from mxdc.engine.centering import auto_center_loop, auto_center_crystal, auto_center_capillary
from mxdc.engine.scripting import Script


class CenterSample(Script):

    def run(self, crystal=False, loop=False, capillary=False):
        if crystal:
            results = auto_center_crystal()
        elif loop:
            results = auto_center_loop()
        elif capillary:
            results = auto_center_capillary()
        else:
            results = {}
        return results

script1 = CenterSample()
