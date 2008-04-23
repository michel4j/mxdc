import gtk, gobject
import sys, os
from Predictor import Predictor
from SampleViewer import SampleViewer
from HutchViewer import HutchViewer
from LogView import LogView
from ActiveWidgets import *
from bcm.tools.scripting import Script
from bcm.scripts.misc import prepare_for_mounting, restore_beamstop

(
  COLUMN_NAME,
  COLUMN_DESCRIPTION,
  COLUMN_AVAILABLE
) = range(3)

class HutchManager(gtk.VBox):
    def __init__(self, beamline):
        gtk.VBox.__init__(self)
        hbox1 = gtk.HBox(False,0)
        hbox2 = gtk.HBox(False,6)
        hbox3 = gtk.HBox(False,6)
        self.beamline = beamline
        self.predictor = Predictor()
        self.predictor.set_size_request(300,300)

        videobook = gtk.Notebook()
        video_size = 0.7
        self.sample_viewer = SampleViewer(self.beamline)
        self.hutch_viewer = HutchViewer(self.beamline)
        videobook.insert_page( self.sample_viewer, tab_label=gtk.Label('Sample Camera') )
        videobook.insert_page( self.hutch_viewer, tab_label=gtk.Label('Hutch Camera') )
        
        self.entry = {
            'energy':       MotorEntry(self.beamline.energy, 'Energy', format="%0.4f"),
            'attenuation':  PositionerEntry(self.beamline.attenuator, 'Attenuation', format="%0.2g"),
            'angle':        MotorEntry(self.beamline.omega, 'Omega', format="%0.3f"),
            'beam_width':   MotorEntry(self.beamline.beam_h, 'Beam width', format="%0.3f"),
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

        motor_vbox1 = gtk.VBox(False,0)
        for key in ['energy','attenuation','beam_width','beam_height']:
            motor_vbox1.pack_start(self.entry[key], expand=True, fill=False)

        motor_vbox2 = gtk.VBox(False,0)        
        for key in ['angle','beam_stop','distance','two_theta']:
            motor_vbox2.pack_start(self.entry[key], expand=True, fill=False)
        
        self.device_box = gtk.HBox(True,6)
           
        diagram = gtk.Image()
        diag_frame = gtk.Frame()
        diag_frame.set_shadow_type(gtk.SHADOW_IN)
        diag_frame.set_border_width(6)
        diag_frame.add(diagram)
        diagram.set_from_file(self.beamline.config['diagram'])
        
        control_box = gtk.VButtonBox()
        control_box.set_border_width(6)
        self.front_end_btn = ShutterButton(self.beamline.psh1, 'Front End')
        self.shutter_btn = ShutterButton(self.beamline.shutter, 'Shutter')
        self.shutter_btn.set_sensitive(False)
        self.optimize_btn = gtk.Button('Optimize Beam')
        self.mount_btn = gtk.Button('Mount Crystal')
        self.mount_btn.connect('clicked', self.prepare_mounting)
        self.reset_btn = gtk.Button('Finished Mounting')
        self.reset_btn.connect('clicked',self.restore_beamstop)
        self.front_end_btn.set_sensitive(False)
        self.optimize_btn.set_sensitive(False)
        self.shutter_btn.set_sensitive(False)
        control_box.pack_start(self.front_end_btn)
        control_box.pack_start(self.shutter_btn)
        control_box.pack_start(self.optimize_btn)
        control_box.pack_start(self.mount_btn)
        control_box.pack_start(self.reset_btn)
        
        hbox1.pack_start(control_box, expand=False, fill=False)
        hbox1.pack_end(diag_frame, expand=False, fill=True)
        self.device_box.pack_start(motor_vbox1,expand=False,fill=True)
        self.device_box.pack_start(motor_vbox2,expand=False,fill=True)
        
        hbox1.pack_end(self.device_box,expand=False,fill=True)
        
        self.pack_start(hbox1)
        hbox3.pack_start(videobook, expand=False,fill=False)
        hbox3.set_border_width(6)
        predictor_frame = gtk.Notebook()
        pred_align = gtk.Alignment(0.5,0.5, 0, 0)
        pred_align.add(self.predictor)
        pred_align.set_border_width(6)
        predictor_frame.insert_page(pred_align,tab_label=gtk.Label('Resolution Predictor'))
        self.predictor.connect('realize',self.update_pred)
        hbox3.pack_start(predictor_frame, expand=True,fill=True)
        
        self.pack_start(hbox3)
        self.show_all()

    def update_pred(self, widget):
        self.predictor.update()
        return True
        
    def prepare_mounting(self, widget):
        self.device_box.set_sensitive(False)
        script = Script(prepare_for_mounting, self.beamline)
        script.start()

    def restore_beamstop(self, widget):
        script = Script(restore_beamstop, self.beamline)
        script.start()
        script.connect('done', lambda x: self.device_box.set_sensitive(True))

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
