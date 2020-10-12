from mxdc.engines.scripting import Script


class SetMountMode(Script):
    description = "Preparing for manual sample mounting."

    def run(self):
        with self.beamline.lock:
            safe_distance = self.beamline.config['safe_distance']
            if self.beamline.detector_z.get_position() < safe_distance:
                self.beamline.detector_z.move_to(safe_distance)

            self.beamline.manager.mount(wait=True)
            self.beamline.beamstop_z.move_to(self.beamline.config['safe_beamstop'], wait=False)


class SetCenterMode(Script):
    description = "Preparing for crystal centering."

    def run(self):
        with self.beamline.lock:
            default_beamstop = self.beamline.config['default_beamstop']

            # needed by 08ID
            if self.beamline.beamstop_z.get_position() < default_beamstop:
                self.beamline.beamstop_z.move_to(default_beamstop)
            target = self.beamline.distance.get_state("target")
            if target:
                restore_distance = target[1]
                if restore_distance and restore_distance < self.beamline.detector_z.get_position():
                    self.beamline.detector_z.move_to(restore_distance, wait=False)
            self.beamline.manager.center(wait=True)


class SetCollectMode(Script):
    description = "Preparing for data collection."

    def run(self):
        with self.beamline.lock:
            self.beamline.manager.collect(wait=True)


class SetAlignMode(Script):
    description = "Switch to beam alignment/inspection mode."

    def run(self):
        with self.beamline.lock:
            self.beamline.manager.align(wait=True)


class SetFreezeMode(Script):
    description = "Re-Orienting gonio position for freezing."

    def run(self):
        with self.beamline.lock:
            safe_distance = self.beamline.config['safe_distance']
            if self.beamline.detector_z.get_position() < safe_distance:
                self.beamline.detector_z.move_to(safe_distance)

            self.beamline.manager.mount(wait=True)
            self.beamline.beamstop_z.move_to(self.beamline.config['safe_beamstop'], wait=True)
            if 'kappa' in self.beamline.registry:
                self.beamline.goniometer.omega.move_to(32.5, wait=True)
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
    description = 'Deice BaseGoniometer'

    def run(self):
        if 'deicer' in self.beamline.registry:
            self.beamline.deicer.on()
            config = self.beamline.goniometer.omega.get_config()
            self.beamline.goniometer.configure(speed=1)
            for i in range(5):
                self.beamline.goniometer.omega.move_by(270, wait=True)
                self.beamline.goniometer.omega.move_by(-270, wait=True)
            self.beamline.goniometer.configure(**config)
            self.beamline.deicer.off()
            self.beamline.manager.mount(wait=True)
        return


__all__ = [
    'RestoreBeam', 'OptimizeBeam', 'SetFreezeMode', 'SetAlignMode',
    'SetCollectMode', 'SetMountMode', 'SetCenterMode', 'DeiceGonio',
]
