import gtk, gobject
import sys, os
from mxdc.widgets.predictor import Predictor
from mxdc.widgets.sampleviewer import SampleViewer
from mxdc.widgets.ptzviewer import AxisViewer
from mxdc.widgets.samplepicker import SamplePicker
from mxdc.widgets.misc import *
from bcm.engine.scripting import get_scripts
from bcm.utils.log import get_module_logger
_logger = get_module_logger('mxdc.hutchmanager')

(
  COLUMN_NAME,
  COLUMN_DESCRIPTION,
  COLUMN_AVAILABLE
) = range(3)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'share')

class HutchManager(gtk.VBox):
    def __init__(self, beamline):
        gtk.VBox.__init__(self)
        hbox1 = gtk.HBox(False,6)
        hbox2 = gtk.HBox(False,6)
        hbox3 = gtk.HBox(False,6)
        hbox1.set_border_width(6)
        hbox2.set_border_width(6)
        hbox3.set_border_width(6)
        
        self.beamline = beamline
        self.scripts = get_scripts()
        self.predictor = Predictor(self.beamline.detector.resolution, 
                                   self.beamline.detector.size)
        self.predictor.set_size_request(170,170)

        videobook = gtk.Notebook()
        video_size = 0.7
        self.sample_viewer = SampleViewer()
        self.hutch_viewer = AxisViewer(self.beamline.registry['hutch_video'])
        videobook.insert_page( self.sample_viewer, tab_label=gtk.Label('Sample Camera') )
        videobook.insert_page( self.hutch_viewer, tab_label=gtk.Label('Hutch Camera') )
        
        self.entry = {
            'energy':       MotorEntry(self.beamline.monochromator.energy, 'Energy', format="%0.4f"),
            'attenuation':  ActiveEntry(self.beamline.attenuator, 'Attenuation', format="%0.1f"),
            'angle':        MotorEntry(self.beamline.goniometer.omega, 'Omega', format="%0.3f"),
            'beam_width':   MotorEntry(self.beamline.collimator.width, 'Beam width', format="%0.3f"),
            'beam_height':  MotorEntry(self.beamline.collimator.height, 'Beam height', format="%0.3f"),
            'distance':     MotorEntry(self.beamline.diffractometer.distance, 'Detector Distance', format="%0.2f"),
            'beam_stop':    MotorEntry(self.beamline.beam_stop.z, 'Beam-stop', format="%0.2f"),
            'two_theta':    MotorEntry(self.beamline.diffractometer.two_theta, 'Detector TwoTheta', format="%0.2f")
        }
        self.beamline.diffractometer.distance.connect('changed', self.update_predictor)
        self.beamline.diffractometer.two_theta.connect('changed', self.update_predictor)
        self.beamline.monochromator.energy.connect('changed', self.update_predictor)
        
        motor_vbox1 = gtk.VBox(False,0)
        for key in ['energy','attenuation','beam_width','beam_height']:
            motor_vbox1.pack_start(self.entry[key], expand=True, fill=False)

        motor_vbox2 = gtk.VBox(False,0)        
        for key in ['angle','beam_stop','distance','two_theta']:
            motor_vbox2.pack_start(self.entry[key], expand=True, fill=False)
        
        self.device_box = gtk.HBox(True,0)
           
        diagram = gtk.Image()
        diag_frame = gtk.Frame()
        diag_frame.set_shadow_type(gtk.SHADOW_IN)
        diag_frame.set_border_width(0)
        diag_frame.add(diagram)
        diagram.set_from_file(os.path.join(DATA_DIR, 'diagram.png'))
        
        control_box = gtk.VButtonBox()
        control_box.set_border_width(0)
        control_box.set_spacing(0)
        self.front_end_btn = ShutterButton(self.beamline.photon_shutter, 'Front End')
        self.shutter_btn = ShutterButton(self.beamline.exposure_shutter, 'Shutter')
        self.optimize_btn = gtk.Button('Optimize Beam')
        self.optimize_btn.connect('clicked', self.optimize_energy)
        self.mount_btn = gtk.Button('Mount Crystal')
        self.mount_btn.connect('clicked', self.prepare_mounting)
        self.reset_btn = gtk.Button('Finished Mounting')
        self.reset_btn.connect('clicked',self.restore_beamstop)
        
        control_box.pack_start(self.front_end_btn)
        control_box.pack_start(self.shutter_btn)
        control_box.pack_start(self.optimize_btn)
        control_box.pack_start(self.mount_btn)
        control_box.pack_start(self.reset_btn)

        for w in [self.front_end_btn, self.shutter_btn, self.optimize_btn, self.mount_btn, self.reset_btn]:
            w.set_property('can-focus', False)
        
        self.device_box.pack_start(motor_vbox1,expand=True,fill=True)
        self.device_box.pack_start(motor_vbox2,expand=True,fill=True)
        
        hbox1.pack_start(control_box, expand=False, fill=False)
        hbox1.pack_start(diag_frame, expand=False, fill=False)
        hbox1.pack_start(self.device_box,expand=True,fill=True)
        
        self.pack_start(hbox1, expand=False, fill=False)
        hbox3.pack_start(videobook, expand=True,fill=True)
        pred_frame = gtk.Frame('Detector Resolution')
        pred_align = gtk.Alignment(0.5,0.5, 0, 0)
        pred_align.add(self.predictor)
        pred_align.set_border_width(3)
        pred_frame.add(pred_align)
        self.sample_picker = SamplePicker()
        self.sample_picker.set_border_width(6)
        self.sample_picker.set_sensitive(False)
        
        hbox1.pack_end(pred_frame, expand=False, fill=False)
        
        sample_frame = gtk.Notebook()
        
        #self.cryo_controller = CryojetWidget(self.beamline.cryojet)
        #cryo_align = gtk.Alignment(0.5,0.5, 0, 0)
        #cryo_align.set_border_width(12)
        #cryo_align.add(self.cryo_controller)
        #self.cryo_controller.set_border_width(6)
        
        #sample_frame.insert_page(cryo_align, tab_label=gtk.Label(' Cryojet Control '))
        sample_frame.insert_page(self.sample_picker, tab_label=gtk.Label(' Sample Auto-mounting '))
 
        hbox3.pack_start(sample_frame, expand=True,fill=True)
        
        self.pack_start(hbox3, expand=True, fill=True)
        self.pack_start(gtk.Label(), expand=True, fill=True)
        self.show_all()
        
        #connect script actions
        for sc in ['OptimizeBeam', 'FinishedMounting']:
            self.scripts[sc].connect('done', lambda x: self.device_box.set_sensitive(True))

    def update_predictor(self, widget, val=None):
        self.predictor.configure(energy=self.beamline.monochromator.energy.get_position(),
                                 distance=self.beamline.diffractometer.distance.get_position(),
                                 two_theta=self.beamline.diffractometer.two_theta.get_position())
        
    def prepare_mounting(self, widget):
        self.device_box.set_sensitive(False)
        script = self.scripts['PrepareMounting']
        script.start()

    def optimize_energy(self, widget):
        self.device_box.set_sensitive(False)
        script = self.scripts['OptimizeBeam']
        script.start()

    def restore_beamstop(self, widget):
        script = self.scripts['FinishedMounting']
        script.start()
                        
def main():
    import bcm.beamline.mx
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("Hutch Demo")
    config_file = '/home/michel/Code/eclipse-ws/beamline-control-module/etc/08id1.conf'
    bl = bcm.beamline.mx.MXBeamline(config_file)
    hutch = HutchManager(bl)
    win.add(hutch)    
    win.show_all()

    try:
        gtk.main()
    finally: 
        print "Quiting..."

if __name__ == '__main__':
    main()
