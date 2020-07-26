import logging

from mxdc import Registry, IBeamline

from mxdc.controllers.diagnostics import DiagnosticsController
from mxdc.engines.scripting import get_scripts
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import sci_fmt
from mxdc.widgets import misc
from mxdc.controllers.common import GUIHandler
from mxdc.widgets.ticker import ChartManager
from .ptzvideo import AxisController
from . import common
from mxdc.devices.goniometer import GonioFeatures

logger = get_module_logger(__name__)


class SetupController(object):
    gui_roots = {
        'data/hutch_manager': ['hutch_widget'],
    }

    def __init__(self, widget):
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.scripts = get_scripts()
        self.hutch_viewer = None
        self.setup()

    def setup(self):
        self.hutch_viewer = AxisController(self.widget, self.beamline.registry['hutch_video'])

        # create and pack devices into settings frame
        entry_list = [
            'energy', 'attenuation', 'beam_size',
            'distance', 'beam_stop', 'two_theta',
            'omega', 'kappa', 'chi', 'phi'
        ]
        entries = {
            'energy': misc.MotorEntry(self.beamline.energy, 'Energy', fmt="%0.3f"),
            'attenuation': misc.ActiveEntry(self.beamline.attenuator, 'Attenuation', fmt="%0.1f"),
            'omega': misc.MotorEntry(self.beamline.goniometer.omega, 'Gonio Omega', fmt="%0.2f"),
            'distance': misc.MotorEntry(self.beamline.distance, 'Detector Distance', fmt="%0.1f"),
            'beam_stop': misc.MotorEntry(self.beamline.beamstop_z, 'Beam-stop', fmt="%0.1f"),
            'two_theta': misc.MotorEntry(self.beamline.two_theta, 'Detector 2-Theta', fmt="%0.1f"),
            'beam_size': misc.ActiveMenu(self.beamline.aperture, 'Beam Aperture', fmt="%0.0f"),
        }
        if self.beamline.goniometer.supports(GonioFeatures.KAPPA):
            entries['phi'] = misc.MotorEntry(self.beamline.goniometer.phi, 'Gonio Phi', fmt="%0.2f")
            entries['chi'] = misc.MotorEntry(self.beamline.goniometer.chi, 'Gonio Chi', fmt="%0.2f")
            entries['kappa'] = misc.MotorEntry(self.beamline.goniometer.kappa, 'Gonio Kappa', fmt="%0.2f")

        for i, key in enumerate(entry_list):
            if key in entries:
                self.widget.setup_device_box.insert(entries[key], i)

        # status, cryo, log
        self.diagnostics = DiagnosticsController(self.widget, self.widget.diagnostics_box)

        # logging
        self.log_viewer = common.LogMonitor(self.widget.setup_log_box)
        log_handler = GUIHandler(self.log_viewer)
        log_handler.setLevel(logging.NOTSET)
        formatter = logging.Formatter('%(asctime)s [%(name)s] %(message)s', '%b/%d %H:%M:%S')
        log_handler.setFormatter(formatter)
        logging.getLogger('').addHandler(log_handler)

        # Beam Tuner
        self.tuner = ChartManager(interval=100, view=10)
        self.widget.tuner_box.pack_start(self.tuner.chart, True, True, 0)
        self.tuner.add_plot(self.beamline.beam_tuner, 'Beam Intensity (%)', signal='percent')
        self.tuner_monitors = [
            common.DeviceMonitor(self.beamline.beam_tuner, self.widget.tuner_left_lbl, format=sci_fmt),
            common.DeviceMonitor(
                self.beamline.beam_tuner, self.widget.tuner_right_lbl, format='{:6.1f} %',
                signal='percent', warning=80.0, error=60.0
            ),
            common.Tuner(
                self.beamline.beam_tuner, self.widget.tuner_up_btn, self.widget.tuner_dn_btn,
                reset_btn=self.widget.tuner_reset_btn, repeat_interval=100,
            )
        ]

        # Some scripts need to reactivate settings frame on completion
        for sc in ['OptimizeBeam', 'SetMountMode', 'SetCenterMode', 'SetCollectMode', 'RestoreBeam', 'SetAlignMode']:
            self.scripts[sc].connect('busy', self.on_scripts_busy)

        self.beamline.all_shutters.connect('changed', self.on_shutter)

    def on_scripts_busy(self, obj, busy):
        if busy:
            self.widget.setup_device_box.set_sensitive(False)
        else:
            self.widget.setup_device_box.set_sensitive(True)

    def on_shutter(self, obj, state):
        self.widget.tuner_control_box.set_sensitive(
            self.beamline.beam_tuner.is_tunable() and self.beamline.all_shutters.is_open())
