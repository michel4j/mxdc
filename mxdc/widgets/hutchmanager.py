import logging
import os

from gi.repository import GObject
from gi.repository import Gtk
from mxdc.beamline.mx import IBeamline
from mxdc.engine.scripting import get_scripts
from mxdc.utils import gui
from mxdc.utils.log import get_module_logger
from mxdc.widgets import misc
from mxdc.widgets.diagnostics import DiagnosticsViewer
from mxdc.widgets.textviewer import TextViewer, GUIHandler
from ptzvideo import AxisViewer
from twisted.python.components import globalRegistry

_logger = get_module_logger(__name__)

(
    COLUMN_NAME,
    COLUMN_DESCRIPTION,
    COLUMN_AVAILABLE
) = range(3)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


class HutchManager(Gtk.Alignment, gui.BuilderMixin):
    __gsignals__ = {
        'beam-change': (GObject.SignalFlags.RUN_LAST, None, [bool, ]),
    }
    gui_roots = {
        'data/hutch_manager': ['hutch_widget'],
    }

    def __init__(self):
        super(HutchManager, self).__init__()
        self.setup_gui()

        self.scripts = get_scripts()
        self.build_gui()
        # Some scripts need to reactivate settings frame on completion
        for sc in ['OptimizeBeam', 'SetMountMode', 'SetCenteringMode', 'SetCollectMode', 'RestoreBeam', 'SetBeamMode']:
            self.scripts[sc].connect('started', self.on_scripts_started)
            self.scripts[sc].connect('done', self.on_scripts_done)

    def build_gui(self):
        self.beamline = globalRegistry.lookup([], IBeamline)

        # diagram file name if one exists
        diagram_file = os.path.join(
            os.environ.get('MXDC_PATH'), 'etc', 'data', self.beamline.name, 'diagram.png'
        )
        if not os.path.exists(diagram_file):
            diagram_file = os.path.join(DATA_DIR, 'diagram.png')
        self.hutch_diagram.set_from_file(diagram_file)

        self.hutch_viewer = AxisViewer(self.beamline.registry['hutch_video'])
        self.hutch_box.pack_end(self.hutch_viewer, True, True, 0)

        # create and pack devices into settings frame
        entry_list = [
            'energy',
            'attenuation',
            'omega',
            'distance',
            'beam_stop',
            'two_theta',
            'beam_size',
            'phi',
            'kappa',
            'chi'
        ]
        self.entries = {
            'energy': misc.MotorEntry(self.beamline.energy, 'Energy', fmt="%0.3f"),
            'attenuation': misc.ActiveEntry(self.beamline.attenuator, 'Attenuation', fmt="%0.1f"),
            'omega': misc.MotorEntry(self.beamline.omega, 'Gonio Omega', fmt="%0.2f"),
            'distance': misc.MotorEntry(self.beamline.distance, 'Detector Distance', fmt="%0.1f"),
            'beam_stop': misc.MotorEntry(self.beamline.beamstop_z, 'Beam-stop', fmt="%0.1f"),
            'two_theta': misc.MotorEntry(self.beamline.two_theta, 'Detector 2-Theta', fmt="%0.1f"),
            'beam_size': misc.ActiveEntry(self.beamline.aperture, 'Beam Aperture', fmt="%0.2f"),
        }
        if 'phi' in self.beamline.registry:
            self.entries['phi'] = misc.MotorEntry(self.beamline.phi, 'Gonio Phi', fmt="%0.2f")
        if 'chi' in self.beamline.registry:
            self.entries['chi'] = misc.MotorEntry(self.beamline.chi, 'Gonio Chi', fmt="%0.2f")
            del self.entries['beam_size']
        if 'kappa' in self.beamline.registry:
            self.entries['kappa'] = misc.MotorEntry(self.beamline.kappa, 'Gonio Kappa', fmt="%0.2f")

        for i, key in enumerate(entry_list):
            if key in self.entries:
                self.device_box.insert(self.entries[key], i)

        # disable mode change buttons while automounter is busy
        self.beamline.automounter.connect('preparing', self.on_devices_busy)
        self.beamline.automounter.connect('busy', self.on_devices_busy)
        self.beamline.goniometer.connect('busy', self.on_devices_busy)

        # status, cryo, log
        self.diagnostics = DiagnosticsViewer()
        self.status_box.pack_end(self.diagnostics, True, True, 0)
        self.cryo_controller = misc.CryojetWidget(self.beamline.cryojet)
        self.cryo_box.pack_start(self.cryo_controller, True, True, 0)

        # logging
        self.log_viewer = TextViewer(self.log_view, 'Candara 7')
        log_handler = GUIHandler(self.log_viewer)
        log_handler.setLevel(logging.NOTSET)
        formatter = logging.Formatter('%(asctime)s %(levelname)-8s: %(message)s', '%b-%d %H:%M:%S')
        log_handler.setFormatter(formatter)
        logging.getLogger('').addHandler(log_handler)

        self.add(self.hutch_widget)
        self.show_all()

    def do_beam_change(self, state):
        pass

    def on_devices_busy(self, obj, state):
        states = [self.beamline.goniometer.busy_state, self.beamline.automounter.preparing_state,
                  self.beamline.automounter.busy_state]
        combined_state = any(states)
        script_names = ['SetCenteringMode', 'SetBeamMode', 'SetCollectMode', 'SetMountMode']
        if combined_state:
            _logger.debug('Disabling commands. Reason: Gonio: %s, Robot: %s, %s' % tuple(
                [{True: 'busy', False: 'idle'}[s] for s in states]))
            for script_name in script_names:
                self.scripts[script_name].disable()
        else:
            _logger.debug('Enabling commands. Reason: Gonio: %s, Robot: %s, %s' % tuple(
                [{True: 'busy', False: 'idle'}[s] for s in states]))
            for script_name in script_names:
                self.scripts[script_name].enable()

    def on_scripts_started(self, obj, event=None):
        self.device_box.set_sensitive(False)

    def on_scripts_done(self, obj, event=None):
        self.device_box.set_sensitive(True)

    def update_predictor(self, widget, val=None):
        self.predictor.configure(
            energy=self.beamline.energy.get_position(),
            distance=self.beamline.distance.get_position(),
            two_theta=self.beamline.two_theta.get_position()
        )
