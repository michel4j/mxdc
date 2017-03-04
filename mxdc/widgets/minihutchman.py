import logging
import os

from gi.repository import GObject
from gi.repository import Gtk
from twisted.python.components import globalRegistry

from mxdc.beamline.mx import IBeamline
from mxdc.engine.scripting import get_scripts
from mxdc.utils import gui
from mxdc.utils.log import get_module_logger
from mxdc.widgets import misc
from mxdc.widgets.controllers.ptzvideo import AxisViewer
from mxdc.widgets.diagnostics import DiagnosticsViewer
from mxdc.widgets.predictor import Predictor
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.simplevideo import SimpleVideo
from mxdc.widgets.textviewer import TextViewer, GUIHandler

_logger = get_module_logger('mxdc.hutchmanager')

(
  COLUMN_NAME,
  COLUMN_DESCRIPTION,
  COLUMN_AVAILABLE
) = range(3)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


class MiniHutchManager(Gtk.Alignment):
    __gsignals__ = {
        'beam-change': (GObject.SignalFlags.RUN_LAST, None, [GObject.TYPE_BOOLEAN,]),
    }
    def __init__(self):

        super(MiniHutchManager, self).__init__()
        self.set(0.5, 0.5, 1, 1)
        self._xml = gui.GUIFile(os.path.join(DATA_DIR, 'mini_hutch_widget'), 'hutch_widget')
        
        self.scripts = get_scripts()
        self._create_widgets()
        # Some scripts need to reactivate settings frame on completion
        for sc in ['OptimizeBeam', 'SetMountMode', 'SetCenteringMode', 'SetCollectMode', 'RestoreBeam','SetBeamMode']:
            self.scripts[sc].connect('started', self.on_scripts_started)
            self.scripts[sc].connect('done', self.on_scripts_done)
    
    def __getattr__(self, key):
        try:
            return super(MiniHutchManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
        
    def _create_widgets(self):
        self.beamline = globalRegistry.lookup([], IBeamline)
        
        # diagram file name if one exists
        diagram_file = os.path.join(os.environ.get('MXDC_CONFIG_PATH'), 'data', self.beamline.name, 'diagram.png')
        if not os.path.exists(diagram_file):
            diagram_file = os.path.join(DATA_DIR, 'diagram.png')
        self.hutch_diagram.set_from_file(diagram_file)

        # video
        def _mk_lbl(txt):
            lbl = Gtk.Label(label=txt)
            lbl.set_padding(6,0)
            return lbl

        self.sample_viewer = SampleViewer()
        self.hutch_viewer = AxisViewer(self.beamline.registry['hutch_video'])
        self.video_book.append_page(self.hutch_viewer, tab_label=_mk_lbl('Hutch Camera'))
        self.video_book.append_page(self.sample_viewer, tab_label=_mk_lbl('Sample Camera'))
        self.video_book.connect('realize', lambda x: self.video_book.set_current_page(0))
        if self.beamline.registry.get('beam_video'):
            self.beam_viewer = SimpleVideo(self.beamline.registry['beam_video'])
            self.video_book.append_page(self.beam_viewer, tab_label=_mk_lbl('Beam Camera'))

        
        # create and pack devices into settings frame
        _entry_locs = {
            'energy': (0,0),
            'attenuation': (1,0),
            'omega': (0,2),
            'distance': (2,0),
            'beam_stop': (0,1),
            'two_theta': (1,1),
            'beam_size': (1,2),
            'phi': (0,3),
            'kappa': (1,3),
            'chi': (1,2)
        }
        self.entries = {
            'energy':       misc.MotorEntry(self.beamline.monochromator.energy, 'Energy', fmt="%0.3f"),
            'attenuation':  misc.ActiveEntry(self.beamline.attenuator, 'Attenuation', fmt="%0.1f"),
            'omega':        misc.MotorEntry(self.beamline.omega, 'Gonio Omega', fmt="%0.2f"),
            'distance':     misc.MotorEntry(self.beamline.diffractometer.distance, 'Detector Distance', fmt="%0.1f"),
            'beam_stop':    misc.MotorEntry(self.beamline.beamstop_z, 'Beam-stop', fmt="%0.1f"),
            'two_theta':    misc.MotorEntry(self.beamline.diffractometer.two_theta, 'Detector 2-Theta', fmt="%0.1f"),
            'beam_size':    misc.ActiveEntry(self.beamline.aperture, 'Beam Aperture', fmt="%0.2f"),
        }
        if 'phi' in self.beamline.registry:
            self.entries['phi'] = misc.MotorEntry(self.beamline.phi, 'Gonio Phi', fmt="%0.2f")
        if 'chi' in self.beamline.registry:
            self.entries['chi'] = misc.MotorEntry(self.beamline.chi, 'Gonio Chi', fmt="%0.2f")
            del self.entries['beam_size']
        if 'kappa' in self.beamline.registry:
            self.entries['kappa'] = misc.MotorEntry(self.beamline.kappa, 'Gonio Kappa', fmt="%0.2f")

               
        for key in self.entries.keys():
            l, t = _entry_locs[key]
            self.device_box.attach(self.entries[key], l, l+1, t, t+1)

        # Predictor
        self.predictor = Predictor(self.beamline.detector.resolution, 
                                   self.beamline.detector.size)
        self.predictor.set(0.5, 0.5, 1, 1)
        self.predictor_frame.add(self.predictor)
        self.beamline.diffractometer.distance.connect('changed', self.update_predictor)
        self.beamline.diffractometer.two_theta.connect('changed', self.update_predictor)
        self.beamline.monochromator.energy.connect('changed', self.update_predictor)
        
        # BOSS enable/disable if a boss has been defined
        if 'boss' in self.beamline.registry:
            self.beamline.energy.connect('starting', lambda x: self.beamline.boss.stop())
            self.beamline.energy.connect('done', lambda x: self.beamline.boss.start())
       
        # Button commands
        self.front_end_btn = misc.ShutterButton(self.beamline.all_shutters, 'Restore Beam', open_only=True)
        self.front_end_btn.connect('clicked', self.on_restore_beam)
        
        self.optimize_btn = misc.ScriptButton(self.scripts['OptimizeBeam'], 'Optimize Beam')
        self.mount_btn = misc.ScriptButton(self.scripts['SetMountMode'], 'Mounting Mode')
        self.cent_btn = misc.ScriptButton(self.scripts['SetCenteringMode'], 'Centering Mode')
        
        # Not currently displayed but used      
        #self.collect_btn = misc.ScriptButton(self.scripts['SetCollectMode'], 'Collect Mode')        
        #self.beam_btn = misc.ScriptButton(self.scripts['SetBeamMode'], 'Beam Mode')
        
        self.commands_box.pack_start(self.front_end_btn, True, True, 0)
        #self.commands_box.pack_start(self.optimize_btn, True, True, 0)
        
        # disable mode change buttons while automounter is busy
        self.beamline.automounter.connect('preparing', self.on_devices_busy)
        self.beamline.automounter.connect('busy', self.on_devices_busy)
        self.beamline.goniometer.connect('busy', self.on_devices_busy)

        # Monitor beam changes
        self.beamline.storage_ring.connect('beam', self.on_beam_change)
        
        self.commands_box.pack_start(Gtk.Label(''), True, True, 0)
        _map = {'MOUNTING':'blue',
                'CENTERING':'orange',
                'SCANNING':'green',
                'COLLECT': 'green',
                'BEAM': 'red',
                'MOVING': 'gray',
                'INIT':'gray',
                'ALIGN': 'gray',
                }
        gonio_mode = misc.StatusBox(self.beamline.goniometer, signal='mode', color_map=_map, background=True)
        gonio_mode.set_border_width(3)
        self.commands_box.pack_start(gonio_mode, True, True, 0)
        #self.commands_box.pack_start(Gtk.Label('', True, True, 0))
        
        for btn in [self.mount_btn, self.cent_btn]:
            self.commands_box.pack_end(btn, True, True, 0)
        
        # tool book, diagnostics  etc
        self.diagnostics = DiagnosticsViewer()
        self.tool_book.append_page(self.diagnostics, tab_label=Gtk.Label(label=' Beamline Status Checks '))
        self.tool_book.connect('realize', lambda x: self.tool_book.set_current_page(0))       
        
        self.cryo_controller = misc.CryojetWidget(self.beamline.cryojet)
        self.tool_book.append_page(self.cryo_controller, tab_label=Gtk.Label(label=' Cryojet Stream '))

        
        #logging
        self.log_viewer = TextViewer(self._xml.get_widget('log_view'), 'Candara 7')
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
        _states = [self.beamline.goniometer.busy_state, self.beamline.automounter.preparing_state, self.beamline.automounter.busy_state]
        combined_state = any(_states)
        _script_names = ['SetCenteringMode', 'SetBeamMode', 'SetCollectMode', 'SetMountMode']
        if combined_state:
            _logger.debug('Disabling commands. Reason: Gonio: %s, Robot: %s, %s' % tuple([{True:'busy', False:'idle'}[s] for s in _states]))
            for script_name in _script_names:
                self.scripts[script_name].disable()
        else:
            _logger.debug('Enabling commands. Reason: Gonio: %s, Robot: %s, %s' % tuple([{True:'busy', False:'idle'}[s] for s in _states]))
            for script_name in _script_names:
                self.scripts[script_name].enable()

        
    def on_beam_change(self, obj, beam_available):
        self.emit('beam-change', beam_available)
    
    def on_restore_beam(self,obj):
        script = self.scripts['RestoreBeam']
        script.start()
    
    def on_mounting(self, obj):
        script = self.scripts['SetMountMode']
        script.start()
    
    def on_beam_mode(self, obj):
        script = self.scripts['SetBeamMode']
        script.start()

    def on_centering(self, obj):
        script = self.scripts['SetCenteringMode']
        script.start()
    
    def on_collection(self, obj):
        script = self.scripts['SetCollectMode']
        script.start()
    
    def on_open_shutter(self, obj):
        self.beamline.exposure_shutter.open()
    
    def on_close_shutter(self, obj):
        self.beamline.exposure_shutter.close()

    def on_scripts_started(self, obj, event=None):
        self.device_box.set_sensitive(False)
        self.commands_box.set_sensitive(False)    
    
    def on_scripts_done(self, obj, event=None):
        self.device_box.set_sensitive(True)
        self.commands_box.set_sensitive(True)
        
    def update_predictor(self, widget, val=None):
        self.predictor.configure(energy=self.beamline.monochromator.energy.get_position(),
                                 distance=self.beamline.diffractometer.distance.get_position(),
                                 two_theta=self.beamline.diffractometer.two_theta.get_position())
        
