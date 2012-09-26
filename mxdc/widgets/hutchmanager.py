import gtk, gobject
import sys, os
import logging
from twisted.python.components import globalRegistry
from bcm.beamline.mx import IBeamline
from bcm.engine.scripting import get_scripts
from bcm.utils.log import get_module_logger

from mxdc.widgets.predictor import Predictor
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.ptzviewer import AxisViewer
from mxdc.widgets.simplevideo import SimpleVideo
from mxdc.widgets.diagnostics import DiagnosticsViewer
from mxdc.widgets.textviewer import TextViewer, GUIHandler
from mxdc.widgets.misc import *
from mxdc.utils import gui

_logger = get_module_logger('mxdc.hutchmanager')

(
  COLUMN_NAME,
  COLUMN_DESCRIPTION,
  COLUMN_AVAILABLE
) = range(3)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class ToggleBoss:
    def __init__(self):
        self.called = {}
    
    def __call__(self, obj, busy, boss):
        if not obj in self.called:
            self.called[obj] = busy
        if busy and len(self.called.keys()) == 1:
            try:
                boss.stop()
            except:
                _logger.warn('Could not disable BOSS')
        elif not busy:
            self.called.pop(obj)
            if not self.called.keys():
                try:
                    boss.start()
                except:
                    _logger.warn('Could not enable BOSS')

class HutchManager(gtk.Frame):
    __gsignals__ = {
        'beam-change': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, [gobject.TYPE_BOOLEAN,]),
    }
    def __init__(self):
        gtk.Frame.__init__(self)
        self._xml = gui.GUIFile(os.path.join(DATA_DIR, 'hutch_widget'), 'hutch_widget')
        self.set_shadow_type(gtk.SHADOW_NONE)
        
        self.scripts = get_scripts()
        self._create_widgets()
        # Some scripts need to reactivate settings frame on completion
        for sc in ['OptimizeBeam', 'SetMountMode', 'SetCenteringMode', 'SetCollectMode', 'RestoreBeam','SetBeamMode']:
            self.scripts[sc].connect('started', self.on_scripts_started)
            self.scripts[sc].connect('done', self.on_scripts_done)
    
    def __getattr__(self, key):
        try:
            return super(HutchManager).__getattr__(self, key)
        except AttributeError:
            return self._xml.get_widget(key)
        
    def _create_widgets(self):
        self.switch_boss = ToggleBoss()       
        self.beamline = globalRegistry.lookup([], IBeamline)
        
        # diagram file name if one exists
        diagram_file = os.path.join(os.environ.get('BCM_CONFIG_PATH'), 'data', self.beamline.name, 'diagram.png')
        if not os.path.exists(diagram_file):
            diagram_file = os.path.join(DATA_DIR, 'diagram.png')
        self.hutch_diagram.set_from_file(diagram_file)

        # video
        def _mk_lbl(txt):
            lbl = gtk.Label(txt)
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
            'energy': (2,0),
            'attenuation': (3,0),
            'omega': (3,2),
            'distance': (4,0),
            'beam_stop': (3,1),
            'two_theta': (4,1),
            'beam_size': (4,2),
            'phi': (3,3),
            'kappa': (4,3),
            'chi': (4,2)
        }
        self.entries = {
            'energy':       MotorEntry(self.beamline.monochromator.energy, 'Energy', format="%0.3f"),
            'attenuation':  ActiveEntry(self.beamline.attenuator, 'Attenuation', format="%0.1f"),
            'omega':        MotorEntry(self.beamline.omega, 'Gonio Omega', format="%0.2f"),
            'distance':     MotorEntry(self.beamline.diffractometer.distance, 'Detector Distance', format="%0.1f"),
            'beam_stop':    MotorEntry(self.beamline.beamstop_z, 'Beam-stop', format="%0.1f"),
            'two_theta':    MotorEntry(self.beamline.diffractometer.two_theta, 'Detector 2-Theta', format="%0.1f"),
            'beam_size':    ActiveEntry(self.beamline.aperture, 'Beam Aperture', format="%0.2f"),
        }
        if 'phi' in self.beamline.registry:
            self.entries['phi'] = MotorEntry(self.beamline.phi, 'Gonio Phi', format="%0.2f")
        if 'chi' in self.beamline.registry:
            self.entries['chi'] = MotorEntry(self.beamline.chi, 'Gonio Chi', format="%0.2f")
            del self.entries['beam_size']
        if 'kappa' in self.beamline.registry:
            self.entries['kappa'] = MotorEntry(self.beamline.kappa, 'Gonio Kappa', format="%0.2f")

               
        for key in self.entries.keys():
            l, t = _entry_locs[key]
            self.device_box.attach(self.entries[key], l, l+1, t, t+1)

        # Predictor
        self.predictor = Predictor(self.beamline.detector.resolution, 
                                   self.beamline.detector.size)
        self.predictor.set(xalign=1.0, yalign=0.5)
        self.predictor_frame.add(self.predictor)
        self.beamline.diffractometer.distance.connect('changed', self.update_predictor)
        self.beamline.diffractometer.two_theta.connect('changed', self.update_predictor)
        self.beamline.monochromator.energy.connect('changed', self.update_predictor)
        self.beamline.detector_z.connect('target-changed', self._track_ztarget)
        
        # BOSS enable/disable if a boss has been defined
        if 'boss' in self.beamline.registry:
            self.beamline.monochromator.energy.connect('busy', self.switch_boss, self.beamline.boss)
            self.beamline.mostab.connect('busy', self.switch_boss, self.beamline.boss)
       
        # Button commands
        self.front_end_btn = ShutterButton(self.beamline.all_shutters, 'Restore Beam', open_only=True)
        self.front_end_btn.connect('clicked', self.on_restore_beam)
        
        self.optimize_btn = ScriptButton(self.scripts['OptimizeBeam'], 'Optimize Beam')
        self.mount_btn = ScriptButton(self.scripts['SetMountMode'], 'Mounting Mode')
        self.cent_btn = ScriptButton(self.scripts['SetCenteringMode'], 'Centering Mode')
        
        # Not currently displayed but used      
        #self.collect_btn = ScriptButton(self.scripts['SetCollectMode'], 'Collect Mode')        
        #self.beam_btn = ScriptButton(self.scripts['SetBeamMode'], 'Beam Mode')
        
        self.commands_box.pack_start(self.front_end_btn)
        self.commands_box.pack_start(self.optimize_btn)
        
        # disable mode change buttons while automounter is busy
        self.beamline.automounter.connect('busy', self.on_automounter_busy)

        # Monitor beam changes
        self.beamline.storage_ring.connect('beam', self.on_beam_change)
        
        self.commands_box.pack_start(gtk.Label(''))
        self.commands_box.pack_start(gtk.Label(''))
        
        for btn in [self.mount_btn, self.cent_btn]:
            self.commands_box.pack_end(btn)
        
        # tool book, diagnostics  etc
        self.diagnostics = DiagnosticsViewer()
        self.tool_book.append_page(self.diagnostics, tab_label=gtk.Label(' Beamline Status Checks '))
        self.tool_book.connect('realize', lambda x: self.tool_book.set_current_page(0))       
        
        self.cryo_controller = CryojetWidget(self.beamline.cryojet)
        self.tool_book.append_page(self.cryo_controller, tab_label=gtk.Label(' Cryojet Stream '))

        
        #logging
        self.log_viewer = TextViewer(self._xml.get_widget('log_view'), 'Candara 7')
        log_handler = GUIHandler(self.log_viewer)
        log_handler.setLevel(logging.NOTSET)
        formatter = logging.Formatter('%(asctime)s %(levelname)-8s: %(message)s', '%b-%d %H:%M:%S')
        log_handler.setFormatter(formatter)
        logging.getLogger('').addHandler(log_handler)
        
        
        self.add(self.hutch_widget)
        self.show_all()
    
    def _track_ztarget(self, obj, targets):
        prev, this = targets
        self.beamline.config['_prev_distance'] = prev
    
    def on_automounter_busy(self, obj, state):
        self.mount_btn.set_sensitive(not state)
        self.cent_btn.set_sensitive(not state)
        #self.collect_btn.set_sensitive(not state)  
        #self.beam_btn.set_sensitive(not state)  
        
    
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
        
                        
def junk():
    import bcm.beamline.mx
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("Hutch Demo")
    bl = bcm.beamline.mx.MXBeamline()
    hutch = HutchManager()
    win.add(hutch)    
    win.show_all()

    try:
        gtk.main()
    finally: 
        print "Quiting..."

if __name__ == '__main__':
    junk()
