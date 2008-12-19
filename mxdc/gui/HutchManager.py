import gtk, gobject
import sys, os
from Predictor import Predictor
from SampleViewer import SampleViewer
from HutchViewer import HutchViewer
from SamplePicker import SamplePicker
from LogView import LogView
from ActiveWidgets import *
from bcm.tools.scripting import Script
from bcm.scripts.misc import prepare_for_mounting, restore_beamstop, optimize_energy

(
  COLUMN_NAME,
  COLUMN_DESCRIPTION,
  COLUMN_AVAILABLE
) = range(3)

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
        self.predictor = Predictor(self.beamline.config['pixel_size'], self.beamline.config['detector_size'])
        self.predictor.set_size_request(170,170)

        videobook = gtk.Notebook()
        video_size = 0.7
        self.sample_viewer = SampleViewer(self.beamline)
        self.hutch_viewer = HutchViewer(self.beamline)
        videobook.insert_page( self.sample_viewer, tab_label=gtk.Label('Sample Camera') )
        videobook.insert_page( self.hutch_viewer, tab_label=gtk.Label('Hutch Camera') )
        
        self.entry = {
            'energy':       MotorEntry(self.beamline.energy, 'Energy', format="%0.4f"),
            'attenuation':  PositionerEntry(self.beamline.attenuator, 'Attenuation', format="%0.1f"),
            'angle':        MotorEntry(self.beamline.omega, 'Omega', format="%0.3f"),
            'beam_width':   MotorEntry(self.beamline.beam_w, 'Beam width', format="%0.3f"),
            'beam_height':  MotorEntry(self.beamline.beam_h, 'Beam height', format="%0.3f"),
            'distance':     MotorEntry(self.beamline.det_d, 'Detector Distance', format="%0.2f"),
            'beam_stop':    MotorEntry(self.beamline.bst_z, 'Beam-stop', format="%0.2f"),
            'two_theta':    MotorEntry(self.beamline.det_2th, 'Detector TwoTheta', format="%0.2f")
        }
        self.beamline.det_d.connect('changed', self.predictor.on_distance_changed)
        self.beamline.det_2th.connect('changed', self.predictor.on_two_theta_changed)
        self.beamline.energy.connect('changed', self.predictor.on_energy_changed)
        
        self.predictor.set_energy( self.beamline.energy.get_position() )        
        self.predictor.set_distance( self.beamline.det_d.get_position() )
        self.predictor.set_twotheta( self.beamline.det_2th.get_position() )
        self.predictor.update(force=True)           
        self.predictor.connect('realize',self.update_pred)

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
        diagram.set_from_file(self.beamline.config['diagram'])
        
        control_box = gtk.VButtonBox()
        control_box.set_border_width(0)
        control_box.set_spacing(0)
        self.front_end_btn = ShutterButton(self.beamline.psh2, 'Front End')
        self.shutter_btn = ShutterButton(self.beamline.shutter, 'Shutter')
        self.optimize_btn = gtk.Button('Optimize Beam')
        self.optimize_btn.connect('clicked', self.optimize_energy)
        self.mount_btn = gtk.Button('Mount Crystal')
        self.mount_btn.connect('clicked', self.prepare_mounting)
        self.reset_btn = gtk.Button('Finished Mounting')
        self.reset_btn.connect('clicked',self.restore_beamstop)
        
        #self.front_end_btn.set_sensitive(False)
        #self.optimize_btn.set_sensitive(False)
        #self.shutter_btn.set_sensitive(False)
        
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
        hbox3.pack_start(videobook, expand=False,fill=False)
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
        
        self.cryo_controller = CryojetWidget(self.beamline.cryojet, self.beamline.cryo_x)
        cryo_align = gtk.Alignment(0.5,0.5, 0, 0)
        #cryo_align.set_border_width(12)
        cryo_align.add(self.cryo_controller)
        self.cryo_controller.set_border_width(6)
        
        sample_frame.insert_page(cryo_align, tab_label=gtk.Label(' Cryojet Control '))
        sample_frame.insert_page(self.sample_picker, tab_label=gtk.Label(' Sample Auto-mounting '))
 
        hbox3.pack_start(sample_frame, expand=True,fill=True)
        
        self.pack_start(hbox3, expand=False, fill=False)
        self.pack_start(gtk.Label(), expand=True, fill=True)
        self.show_all()

    def update_pred(self, widget):
        self.predictor.update()
        return True
        
    def prepare_mounting(self, widget):
        self.device_box.set_sensitive(False)
        script = Script(prepare_for_mounting, self.beamline)
        script.start()

    def optimize_energy(self, widget):
        self.device_box.set_sensitive(False)
        script = Script(optimize_energy, self.beamline)
        script.connect('done', lambda x: self.device_box.set_sensitive(True))
        script.start()

    def restore_beamstop(self, widget):
        script = Script(restore_beamstop, self.beamline)
        script.connect('done', lambda x: self.device_box.set_sensitive(True))
        script.start()

    def stop(self):
        self.sample_viewer.stop()
        self.hutch_viewer.stop()
                        
def main():
    win = gtk.Window()
    win.connect("destroy", lambda x: gtk.main_quit())
    win.set_border_width(0)
    win.set_title("Hutch Demo")
    
    hutch = HutchManager()
    win.add(hutch)    
    win.show_all()

    try:
        gtk.main()
    finally: 
        print "Quiting..."
        hutch.stop()

if __name__ == '__main__':
    main()
