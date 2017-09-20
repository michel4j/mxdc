import logging

import common
from gi.repository import GObject
from mxdc.beamline.mx import IBeamline
from mxdc.engine.scripting import get_scripts
from mxdc.utils.log import get_module_logger
from mxdc.widgets import misc
from mxdc.widgets.diagnostics import DiagnosticsViewer
from mxdc.widgets.textviewer import GUIHandler
from mxdc.widgets.ticker import ChartManager
from ptzvideo import AxisController
from twisted.python.components import globalRegistry

logger = get_module_logger(__name__)


class SetupController(object):
    __gsignals__ = {
        'beam-change': (GObject.SignalFlags.RUN_LAST, None, [bool, ]),
    }
    gui_roots = {
        'data/hutch_manager': ['hutch_widget'],
    }

    def __init__(self, widget):
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.scripts = get_scripts()
        self.hutch_viewer = None
        self.setup()

    def setup(self):
        self.hutch_viewer = AxisController(self.widget, self.beamline.registry['hutch_video'])
        # Some scripts need to reactivate settings frame on completion
        for sc in ['OptimizeBeam', 'SetMountMode', 'SetCenteringMode', 'SetCollectMode', 'RestoreBeam', 'SetBeamMode']:
            self.scripts[sc].connect('busy', self.on_scripts_busy)

        # create and pack devices into settings frame
        entry_list = [
            'energy', 'attenuation', 'beam_size',
            'distance', 'beam_stop', 'two_theta',
            'omega', 'kappa', 'chi', 'phi'
        ]
        entries = {
            'energy': misc.MotorEntry(self.beamline.energy, 'Energy', fmt="%0.3f"),
            'attenuation': misc.ActiveEntry(self.beamline.attenuator, 'Attenuation', fmt="%0.1f"),
            'omega': misc.MotorEntry(self.beamline.omega, 'Gonio Omega', fmt="%0.2f"),
            'distance': misc.MotorEntry(self.beamline.distance, 'Detector Distance', fmt="%0.1f"),
            'beam_stop': misc.MotorEntry(self.beamline.beamstop_z, 'Beam-stop', fmt="%0.1f"),
            'two_theta': misc.MotorEntry(self.beamline.two_theta, 'Detector 2-Theta', fmt="%0.1f"),
            'beam_size': misc.ActiveMenu(self.beamline.aperture, 'Beam Aperture', fmt="%0.0f"),
        }
        if 'phi' in self.beamline.registry:
            entries['phi'] = misc.MotorEntry(self.beamline.phi, 'Gonio Phi', fmt="%0.2f")
        if 'chi' in self.beamline.registry:
            entries['chi'] = misc.MotorEntry(self.beamline.chi, 'Gonio Chi', fmt="%0.2f")
        if 'kappa' in self.beamline.registry:
            entries['kappa'] = misc.MotorEntry(self.beamline.kappa, 'Gonio Kappa', fmt="%0.2f")

        for i, key in enumerate(entry_list):
            if key in entries:
                self.widget.setup_device_box.insert(entries[key], i)

        # disable mode change buttons while automounter is busy
        self.beamline.automounter.connect('preparing', self.on_devices_busy)
        self.beamline.automounter.connect('busy', self.on_devices_busy)
        self.beamline.goniometer.connect('busy', self.on_devices_busy)

        # status, cryo, log
        self.diagnostics = DiagnosticsViewer()
        self.widget.setup_status_box.pack_end(self.diagnostics, True, True, 0)

        # logging
        self.log_viewer = common.LogMonitor(self.widget.setup_log_box, 'Candara 7')
        log_handler = GUIHandler(self.log_viewer)
        log_handler.setLevel(logging.NOTSET)
        formatter = logging.Formatter('%(asctime)s [%(name)s] %(message)s', '%b/%d %H:%M:%S')
        log_handler.setFormatter(formatter)
        logging.getLogger('').addHandler(log_handler)

        # Beam Tuner
        self.tuner = ChartManager(interval=100, view=10)
        self.widget.tuner_box.pack_start(self.tuner.chart, True, True, 0)
        self.tuner.add_plot(self.beamline.beam_tuner, 'Beam Intensity')
        self.tuner_monitors = [
            common.DeviceMonitor(self.beamline.beam_tuner, self.widget.tuner_left_lbl),
            common.DeviceMonitor(
                self.beamline.beam_tuner, self.widget.tuner_right_lbl, format='{:0.1f} %',
                signal='percent', warning=90.0, error=80.0
            )
        ]
        self.widget.tuner_control_box.set_sensitive(self.beamline.beam_tuner.tunable)
        self.widget.tuner_up_btn.connect('clicked', lambda x: self.beamline.beam_tuner.tune_up())
        self.widget.tuner_dn_btn.connect('clicked', lambda x: self.beamline.beam_tuner.tune_down())
        self.widget.tuner_reset_btn.connect('clicked', lambda x: self.beamline.beam_tuner.reset())

    def do_beam_change(self, state):
        pass

    def on_devices_busy(self, obj, state):
        states = [self.beamline.goniometer.busy_state, self.beamline.automounter.preparing_state,
                  self.beamline.automounter.busy_state]
        combined_state = any(states)
        script_names = ['SetCenteringMode', 'SetBeamMode', 'SetCollectMode', 'SetMountMode']
        if combined_state:
            logger.debug('Disabling commands. Reason: Gonio: %s, Robot: %s, %s' % tuple(
                [{True: 'busy', False: 'idle'}[s] for s in states]))
            for script_name in script_names:
                self.scripts[script_name].disable()
        else:
            logger.debug('Enabling commands. Reason: Gonio: %s, Robot: %s, %s' % tuple(
                [{True: 'busy', False: 'idle'}[s] for s in states]))
            for script_name in script_names:
                self.scripts[script_name].enable()

    def on_scripts_busy(self, obj, busy):
        if busy:
            self.widget.setup_device_box.set_sensitive(False)
        else:
            self.widget.setup_device_box.set_sensitive(True)
