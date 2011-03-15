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

_logger = get_module_logger('mxdc.hutchmanager')

(
  COLUMN_NAME,
  COLUMN_DESCRIPTION,
  COLUMN_AVAILABLE
) = range(3)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

class HutchManager(gtk.Frame):
    def __init__(self):
        gtk.Frame.__init__(self)
        self.set_shadow_type(gtk.SHADOW_NONE)
        
        self.scripts = get_scripts()
        self._create_widgets()
        # Some scripts need to reactivate settings frame on completion
        for sc in ['OptimizeBeam', 'SetMountMode', 'SetCenteringMode', 'SetCollectMode', 'RestoreBeam']:
            self.scripts[sc].connect('started', self.on_scripts_started)
            self.scripts[sc].connect('done', self.on_scripts_done)
    
    def _create_widgets(self):
        self._xml = gtk.glade.XML(os.path.join(DATA_DIR, 'hutch_widget.glade'), 
                                  'hutch_widget')
        self.hutch_widget = self._xml.get_widget('hutch_widget')
        self.commands_box = self._xml.get_widget('commands_box')
        self.settings_frame = self._xml.get_widget('settings_frame')
        self.predictor_frame = self._xml.get_widget('predictor_frame')       
        self.video_book = self._xml.get_widget('video_book')
        self.tool_book = self._xml.get_widget('tool_book')        
        self.device_box = self._xml.get_widget('device_box')
        
        self.beamline = globalRegistry.lookup([], IBeamline)
        
        
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
        self.entries = {
            'energy':       MotorEntry(self.beamline.monochromator.energy, 'Energy', format="%0.3f"),
            'attenuation':  ActiveEntry(self.beamline.attenuator, 'Attenuation', format="%0.1f"),
            'angle':        MotorEntry(self.beamline.goniometer.omega, 'Omega', format="%0.2f"),
            'beam_width':   MotorEntry(self.beamline.beam_w, 'Beam width', format="%0.2f"),
            'beam_height':  MotorEntry(self.beamline.beam_h, 'Beam height', format="%0.2f"),
            'distance':     MotorEntry(self.beamline.diffractometer.distance, 'Detector Distance', format="%0.1f"),
            'beam_stop':    MotorEntry(self.beamline.beam_stop.z, 'Beam-stop', format="%0.1f"),
            'two_theta':    MotorEntry(self.beamline.diffractometer.two_theta, 'Detector 2-Theta', format="%0.1f")
        }
        motor_box1 = gtk.VBox(False,0)
        for key in ['energy','attenuation','beam_width','beam_height']:
            motor_box1.pack_start(self.entries[key], expand=True, fill=False)
        motor_box2 = gtk.VBox(False,0)        
        for key in ['angle','beam_stop','distance','two_theta']:
            motor_box2.pack_start(self.entries[key], expand=True, fill=False)
        self.device_box.pack_start(motor_box1, expand=True, fill=True)
        self.device_box.pack_start(motor_box2, expand=True, fill=True)

        # Predictor
        self.predictor = Predictor(self.beamline.detector.resolution, 
                                   self.beamline.detector.size)
        self.predictor.set(xalign=1.0, yalign=0.5)
        self.predictor_frame.add(self.predictor)
        self.beamline.diffractometer.distance.connect('changed', self.update_predictor)
        self.beamline.diffractometer.two_theta.connect('changed', self.update_predictor)
        self.beamline.monochromator.energy.connect('changed', self.update_predictor)
        
        # Button commands
        self.front_end_btn = ShutterButton(self.beamline.all_shutters, 'Restore Beam', open_only=True)
        self.front_end_btn.connect('clicked', self.on_restore_beam)
        
        #self.front_end_btn = ScriptButton(self.scripts['RestoreBeam'], 'Restore Beam')
        #self.shutter_btn = ShutterButton(self.beamline.exposure_shutter, 'Shutter')
        self.optimize_btn = ScriptButton(self.scripts['OptimizeBeam'], 'Optimize Beam')
        self.mount_btn = ScriptButton(self.scripts['SetMountMode'], 'Mounting Mode')
        self.cent_btn = ScriptButton(self.scripts['SetCenteringMode'], 'Centering Mode')
        self.collect_btn = ScriptButton(self.scripts['SetCollectMode'], 'Collect Mode')
        
        
        
        self.commands_box.pack_start(self.front_end_btn)
        #self.commands_box.pack_start(self.shutter_btn)
        self.commands_box.pack_start(self.optimize_btn)
        self.commands_box.pack_start(gtk.Label(''))
        
        for btn in [self.mount_btn, self.cent_btn, self.collect_btn]:
            self.commands_box.pack_end(btn)
            
        for w in [self.front_end_btn, self.optimize_btn, self.mount_btn, self.cent_btn, self.collect_btn]:
            w.set_property('can-focus', False)
        
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
        
    def on_restore_beam(self,obj):
        script = self.scripts['RestoreBeam']
        script.start()
    
    def on_mounting(self, obj):
        self.mount_btn.clicked()
    
    def on_centering(self, obj):
        self.cent_btn.clicked()
    
    def on_collection(self, obj):
        self.collect_btn.clicked()
    
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
    config_file = '/media/seagate/beamline-control-module/etc/08id1.conf'
    bl = bcm.beamline.mx.MXBeamline(config_file)
    hutch = HutchManager()
    win.add(hutch)    
    win.show_all()

    try:
        gtk.main()
    finally: 
        print "Quiting..."

if __name__ == '__main__':
    junk()
