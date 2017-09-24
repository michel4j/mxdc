from mxdc.engines.centering import auto_center_loop, auto_center_crystal, auto_center_capillary
from mxdc.engines.scripting import Script


class CenterSample(Script):
    description = "Centering automatically."

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


class SetMountMode(Script):
    description = "Preparing for manual sample mounting."

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
    description = "Preparing for crystal centering."

    def run(self):
        if not (self.beamline.automounter.is_busy() or self.beamline.automounter.is_preparing()):
            self.beamline.cryojet.nozzle.close()
            default_beamstop = self.beamline.config['default_beamstop']

            # needed by 08ID
            if self.beamline.beamstop_z.get_position() < default_beamstop:
                self.beamline.beamstop_z.move_to(default_beamstop, wait=True)

            self.beamline.goniometer.set_mode('CENTERING', wait=False)
            if self.beamline.distance.target_changed_state:
                restore_distance = self.beamline.distance.target_changed_state[1]
                if restore_distance and restore_distance < self.beamline.detector_z.get_position():
                    self.beamline.detector_z.move_to(restore_distance, wait=False)

    def run_after(self):
        default_beamstop = self.beamline.config['default_beamstop']
        self.beamline.goniometer.wait(start=False, stop=True, timeout=20)
        self.beamline.beamstop_z.move_to(default_beamstop, wait=False)


class SetCollectMode(Script):
    description = "Preparing for data collection."

    def run(self):
        if not (self.beamline.automounter.is_busy() or self.beamline.automounter.is_preparing()):
            self.beamline.goniometer.set_mode('COLLECT', wait=True)
            self.beamline.cryojet.nozzle.close()


class SetBeamMode(Script):
    description = "Switching to BEAM inspection mode."

    def run(self):
        if not (self.beamline.automounter.is_busy() or self.beamline.automounter.is_preparing()):
            self.beamline.goniometer.set_mode('BEAM', wait=True)


class SetFreezeMode(Script):
    description = "Re-Orienting gonio position for freezing."

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


class OptimizeBeam(Script):
    description = 'Optimizing the beam.'

    def run(self):
        self.beamline.mostab.start()
        self.beamline.mostab.wait()
        return


class RestoreBeam(Script):
    description = 'Restoring the beam after injection.'

    def run(self):
        if not self.beamline.all_shutters.is_open():
            self.beamline.all_shutters.open()
        pos = self.beamline.energy.get_position()
        self.beamline.energy.move_to(pos, wait=True, force=True)
        return


class DeiceGonio(Script):
    description = 'Deice Goniometer'

    def run(self):
        if 'deicer' in self.beamline.registry:
            pos = self.beamline.omega.get_position()
            self.beamline.goniometer.configure(delta=360, time=60, angle=pos)
            self.beamline.deicer.on()
            self.beamline.goniometer.scan(wait=True)
            self.beamline.omega.move_to(pos)
            self.beamline.deicer.off()
            self.beamline.goniometer.set_mode('MOUNTING', wait=True)
        return

__all__ = [
    'RestoreBeam', 'OptimizeBeam', 'SetFreezeMode', 'SetBeamMode',
    'SetCollectMode', 'SetMountMode', 'SetCenteringMode', 'DeiceGonio',
]
